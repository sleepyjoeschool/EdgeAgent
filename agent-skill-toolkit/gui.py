"""
GUI for the Agent Skill Toolkit
================================
Tkinter-based dark-theme interface with streaming output.

- Black background (#000000)
- Thinking text: gray (#888888)
- Content text: white (#ffffff)
- Tool calls: cyan (#00bfff)
- Tool results: dim gray (#aaaaaa)

The streaming API call runs in a background thread; chunk events are
delivered to the UI thread via a queue.
"""

from __future__ import annotations

import json
import math
import os
import queue
import random
import sys
import threading
import time
from pathlib import Path

import httpx

# Allow direct imports from this directory
_TOOLKIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLKIT_DIR not in sys.path:
    sys.path.insert(0, _TOOLKIT_DIR)

import tkinter as tk
from tkinter import ttk

from openai import OpenAI

import config
import config_editor
import tool_loader
import warning_notice
from executors.keyboard import execute as exec_keyboard
from executors.mouse import execute as exec_mouse
from executors.shell import execute as exec_shell
from executors.screen_capture import execute as exec_screen_capture
from executors.basic import execute as exec_basic
from executors.vlm import execute as exec_vlm

# ── Colour constants ────────────────────────────────────────────────────

BG = "#000000"
FG_CONTENT = "#ffffff"
FG_THINKING = "#888888"
FG_TOOL = "#00bfff"
FG_USER = "#66cc66"
FG_SYSTEM = "#cc6666"
FG_DIM = "#666666"

FONT = ("Consolas", 11)
FONT_BOLD = ("Consolas", 11, "bold")

# ── Settings persistence ──────────────────────────────────────────────────

_SETTINGS_FILE = Path.home() / ".agent_skill_toolkit_settings.json"

def _load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}

def _save_settings(settings: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ── Watchdog constants ───────────────────────────────────────────────────

_STUCK_RECOVERY_MSG = (
    "[Agent Message] Something went wrong resulting in the execution "
    "being stuck and being interrupted. Continue what you were doing."
)

_INTERRUPTED_MSG = (
    "There was an error that caused the execution to be interrupted. "
    "Please continue with your previous task."
)

# ── Queue event types ───────────────────────────────────────────────────

_EVT_REASONING = "reasoning"
_EVT_CONTENT = "content"
_EVT_TOOL_BEGIN = "tool_begin"
_EVT_TOOL_RESULT = "tool_result"
_EVT_DONE = "done"
_EVT_ERROR = "error"
_EVT_STUCK = "stuck"
_EVT_STATUS = "status"
_EVT_STEP_BEGIN = "step_begin"
_EVT_STEP_SUMMARY = "step_summary"

# ── Step-by-step constants ────────────────────────────────────────────────

_MAX_INTERNAL_ROUNDS = 50
_TASK_COMPLETE_MARKER = "TASK_COMPLETE"
_CONTINUE_PROMPT = (
    "Continue to the next step of the original task. "
    "If all steps are complete, reply with 'TASK_COMPLETE' "
    "followed by a summary of what was accomplished."
)

# ── Spinner config ──────────────────────────────────────────────────────

_SPINNER_SIZE = 20          # canvas size in px
_SPINNER_ARC_EXTENT = 270   # arc sweep angle
_SPINNER_WIDTH = 3          # arc outline width
_SPINNER_STEP = 12          # degrees per animation frame
_SPINNER_INTERVAL = 35      # ms between frames → 1.05 s per rotation
_SPINNER_ROTATIONS = 2      # rotations before status text change
_SPINNER_COLOR = "#00bfff"
_SPINNER_BG = "#000000"

# Random status texts (picked when no specific context)
_STATUS_TEXTS = [
    "Thinking…",
    "Perusing…",
    "Analyzing…",
    "Executing…",
    "Refining…",
]


class DesktopAgentGUI:
    """Main GUI window for the Desktop Action LLM Agent."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Desktop Agent — DeepSeek")
        self.root.configure(bg=BG)
        self.root.geometry("900x650")
        self.root.minsize(500, 350)

        self._init_client()
        self._init_state()
        self._build_ui()
        self._bind_keys()

        self._queue: queue.Queue = queue.Queue()
        self._processing = False

        # Settings
        self._settings: dict = _load_settings()
        self._apply_window_topmost()

        # Spinner animation state
        self._spinner_angle: float = 0.0
        self._spinner_rotations: int = 0
        self._spinner_job: str | None = None
        self._status_locked: bool = False  # True while a context status is shown
        self._status_exclude: set[str] = set()  # avoid repeating status text

        # Menu overlay state
        self._menu_visible: bool = False
        self._menu_items: list[tuple[str, str, object]] = []  # (label, desc, action)
        self._menu_selection: int = -1
        self._menu_last_filter: str = ""  # avoid redundant rebuilds

    # ── Initialisation ───────────────────────────────────────────────

    def _init_client(self) -> None:
        self._client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=12.0, write=10.0, pool=10.0),
        )

    def _init_state(self) -> None:
        entry = tool_loader.load_entry_point()
        self._system_prompt = entry["system_prompt"]
        # Start with meta-tools + basic utilities
        self._default_tools: list[dict] = list(entry["tools"])
        try:
            self._default_tools.extend(tool_loader.load_category_tools("basic"))
        except Exception:
            pass
        self._active_tools: list[dict] = list(self._default_tools)
        self._loaded_categories: set[str] = set()
        self._messages: list[dict] = [
            {"role": "system", "content": self._system_prompt},
        ]
        self._last_chunk_time: float = time.time()
        self._last_tool_time: float = time.time()
        self._work_done: bool = False
        self._original_request: str = ""
        self._step_completed: bool = False
        self._step_content: str = ""

    def _strip_to_step_summaries(self, original_request: str) -> None:
        """Strip all intermediate messages, keeping only step summaries."""
        clean: list[dict] = [{"role": "system", "content": self._system_prompt}]
        clean.append({"role": "user", "content": original_request})
        for msg in self._messages[2:]:
            if msg["role"] == "assistant" and msg.get("content") and not msg.get("tool_calls"):
                clean.append(dict(msg))
        self._messages = clean

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Output text area ─────────────────────────────────────────
        self._output = tk.Text(
            self.root,
            bg=BG,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            selectbackground="#333333",
            selectforeground=FG_CONTENT,
            font=FONT,
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            borderwidth=0,
            padx=12,
            pady=10,
        )
        self._output.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Scrollbar
        scrollbar = ttk.Scrollbar(self._output, orient=tk.VERTICAL, command=self._output.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._output.configure(yscrollcommand=scrollbar.set)

        # Tag styles
        self._output.tag_configure("thinking", foreground=FG_THINKING)
        self._output.tag_configure("content", foreground=FG_CONTENT)
        self._output.tag_configure("tool", foreground=FG_TOOL, font=FONT_BOLD)
        self._output.tag_configure("tool_result_success", foreground="#66cc66")
        self._output.tag_configure("tool_result_error", foreground="#ff4444")
        self._output.tag_configure("user", foreground=FG_USER, font=FONT_BOLD)
        self._output.tag_configure("system", foreground=FG_SYSTEM)
        self._output.tag_configure("error", foreground="#ff4444")

        # Welcome message
        self._append_output("Desktop Agent — DeepSeek\n", "system")
        self._append_output(f"Model: {config.DEEPSEEK_MODEL}\n", "system")
        self._append_output("Commands: /help /tools /reset /clear /config /setting /quit\n\n", "system")

        # ── Menu popup (hidden until triggered) ───────────────────────
        self._menu_popup = tk.Toplevel(self.root)
        self._menu_popup.withdraw()
        self._menu_popup.overrideredirect(True)
        self._menu_popup.configure(bg="#1a1a2e")
        self._menu_popup.attributes("-topmost", True)

        self._menu_listbox = tk.Listbox(
            self._menu_popup,
            bg="#1a1a2e",
            fg="#cccccc",
            selectbackground="#2a4a6e",
            selectforeground="#ffffff",
            font=FONT,
            relief=tk.FLAT,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#333355",
            highlightcolor="#5555aa",
            activestyle="none",
            height=6,
        )
        self._menu_listbox.pack(fill=tk.BOTH, expand=True)

        # ── Status bar (spinner + text) ────────────────────────────────
        self._status_frame = tk.Frame(self.root, bg=BG, height=36)
        self._status_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4))
        self._status_frame.pack_forget()  # hidden until processing starts

        self._spinner_canvas = tk.Canvas(
            self._status_frame,
            width=_SPINNER_SIZE,
            height=_SPINNER_SIZE,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self._spinner_canvas.pack(side=tk.LEFT, padx=(0, 8))

        self._status_label = tk.Label(
            self._status_frame,
            text="",
            bg=BG,
            fg=FG_THINKING,
            font=FONT,
            anchor=tk.W,
        )
        self._status_label.pack(side=tk.LEFT)

        # Draw initial spinner
        self._spinner_arc = self._spinner_canvas.create_arc(
            3, 3, _SPINNER_SIZE - 3, _SPINNER_SIZE - 3,
            start=0,
            extent=_SPINNER_ARC_EXTENT,
            outline=_SPINNER_COLOR,
            width=_SPINNER_WIDTH,
            style=tk.ARC,
            tags="spinner",
        )

        # ── Input frame ──────────────────────────────────────────────
        self._input_frame = tk.Frame(self.root, bg=BG)
        self._input_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))

        self._entry = tk.Entry(
            self._input_frame,
            bg="#111111",
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))

        self._send_btn = tk.Button(
            self._input_frame,
            text="Send",
            bg="#1a1a2e",
            fg=FG_CONTENT,
            font=FONT_BOLD,
            relief=tk.FLAT,
            borderwidth=0,
            padx=20,
            pady=4,
            command=self._on_send,
            activebackground="#16213e",
            activeforeground=FG_CONTENT,
        )
        self._send_btn.pack(side=tk.RIGHT)

    def _bind_keys(self) -> None:
        self._entry.bind("<Return>", self._on_entry_return)
        self._entry.bind("<Escape>", self._on_entry_escape)
        self._entry.bind("<Up>", self._on_menu_up)
        self._entry.bind("<Down>", self._on_menu_down)
        self._entry.bind("<KeyRelease>", self._on_entry_keyrelease)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._menu_listbox.bind("<ButtonRelease-1>", self._on_menu_click)

    # ── Settings ──────────────────────────────────────────────────────

    def _apply_window_topmost(self) -> None:
        on = self._settings.get("window_topmost", False)
        self.root.attributes("-topmost", on)

    def _toggle_topmost(self) -> None:
        current = self.root.attributes("-topmost")
        self.root.attributes("-topmost", not current)
        self._settings["window_topmost"] = not current
        _save_settings(self._settings)
        status = "ON" if not current else "OFF"
        self._append_output(
            f"[setting] Window Always on Top: {status}\n", "system"
        )

    # ── Menu system ───────────────────────────────────────────────────

    _SLASH_COMMANDS: dict[str, tuple[str, object]] = {
        "/setting": ("Open settings menu", "_menu_settings"),
        "/config":  ("Open configuration editor", "_cmd_config"),
        "/help":    ("Show help message", "_cmd_help"),
        "/tools":   ("List currently loaded tools", "_cmd_tools"),
        "/reset":   ("Clear conversation and reload entry tools", "_cmd_reset"),
        "/clear":   ("Clear the output display", "_cmd_clear"),
        "/stop":    ("Stop the current generation", "_cmd_stop"),
        "/quit":    ("Exit the application", "_cmd_quit"),
    }

    # Keyword aliases that trigger the menu without a leading /
    _COMMAND_KEYWORDS: dict[str, str] = {
        "setting": "/setting",
        "settings": "/setting",
        "config": "/config",
        "configuration": "/config",
        "help": "/help",
        "tools": "/tools",
        "tool": "/tools",
        "reset": "/reset",
        "clear": "/clear",
        "stop": "/stop",
        "quit": "/quit",
        "exit": "/quit",
    }

    def _show_menu(self, items: list[tuple[str, str, object]]) -> None:
        """Display the popup menu with the given (label, desc, action) items."""
        self._menu_items = items
        self._menu_selection = 0
        self._menu_listbox.delete(0, tk.END)
        for label, desc, _action in items:
            self._menu_listbox.insert(tk.END, f" {label}  —  {desc}")
        self._menu_listbox.selection_clear(0, tk.END)
        self._menu_listbox.selection_set(0)
        self._menu_listbox.activate(0)
        rows = min(len(items), 8)
        self._menu_listbox.configure(height=rows)
        self._position_menu()
        self._menu_popup.deiconify()
        self._menu_popup.lift()
        self._menu_visible = True

    def _hide_menu(self) -> None:
        self._menu_popup.withdraw()
        self._menu_visible = False
        self._menu_items = []
        self._menu_selection = -1
        self._menu_last_filter = ""

    def _position_menu(self) -> None:
        """Position the menu popup just above the input frame."""
        self.root.update_idletasks()
        self._menu_popup.update_idletasks()
        x = self._entry.winfo_rootx()
        y = self._entry.winfo_rooty()
        w = max(self._entry.winfo_width(), 200)
        h = self._menu_listbox.winfo_reqheight()
        self._menu_popup.geometry(f"{w}x{h}+{x}+{y - h - 2}")

    def _filter_menu(self, text: str) -> None:
        """Filter menu items by the typed text. Hide if no match."""
        text_lower = text.lower().lstrip("/").strip()
        if not text_lower:
            self._show_menu([(cmd, desc, act) for cmd, (desc, act)
                            in self._SLASH_COMMANDS.items()])
            return
        matching = [
            (cmd, desc, act) for cmd, (desc, act) in self._SLASH_COMMANDS.items()
            if text_lower in cmd.lower().lstrip("/") or text_lower in desc.lower()
        ]
        if matching:
            self._show_menu(matching)
        else:
            self._hide_menu()

    def _matches_any_command(self, text: str) -> bool:
        """Check whether *text* (without leading /) triggers the command menu."""
        t = text.lower().strip()
        if not t:
            return False
        if t in self._COMMAND_KEYWORDS:
            return True
        # Also match partial command names (>= 2 chars)
        if len(t) >= 2:
            for cmd in self._SLASH_COMMANDS:
                if t in cmd.lower().lstrip("/"):
                    return True
        return False

    def _on_entry_keyrelease(self, event: tk.Event) -> None:
        """Show/filter the slash-command menu as the user types."""
        if self._processing:
            return
        # Ignore navigation keys — they don't change text
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Escape",
                            "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
                            "Alt_L", "Alt_R"):
            return
        text = self._entry.get().strip()
        if text == self._menu_last_filter:
            return
        self._menu_last_filter = text
        if text.startswith("/"):
            self._filter_menu(text)
        elif self._matches_any_command(text):
            self._filter_menu(text)
        elif self._menu_visible:
            self._hide_menu()

    def _on_entry_return(self, event: tk.Event) -> None:
        """Handle Enter: execute menu action if menu is visible, else send."""
        if self._menu_visible and self._menu_selection >= 0:
            self._execute_menu_action()
            return
        self._on_send()

    def _on_entry_escape(self, event: tk.Event) -> None:
        """Handle Escape: hide menu if visible, else stop processing."""
        if self._menu_visible:
            self._hide_menu()
            return
        self._on_stop()

    def _on_menu_up(self, event: tk.Event) -> None:
        if not self._menu_visible:
            return
        self._menu_selection = (self._menu_selection - 1) % len(self._menu_items)
        self._menu_listbox.selection_clear(0, tk.END)
        self._menu_listbox.selection_set(self._menu_selection)
        self._menu_listbox.activate(self._menu_selection)

    def _on_menu_down(self, event: tk.Event) -> None:
        if not self._menu_visible:
            return
        self._menu_selection = (self._menu_selection + 1) % len(self._menu_items)
        self._menu_listbox.selection_clear(0, tk.END)
        self._menu_listbox.selection_set(self._menu_selection)
        self._menu_listbox.activate(self._menu_selection)

    def _on_menu_click(self, event: tk.Event) -> None:
        idx = self._menu_listbox.nearest(event.y)
        if idx >= 0 and idx < len(self._menu_items):
            self._menu_selection = idx
            self._execute_menu_action()

    def _execute_menu_action(self) -> None:
        """Execute the currently selected menu item's action."""
        if not self._menu_visible or self._menu_selection < 0:
            return
        _label, _desc, action = self._menu_items[self._menu_selection]
        self._hide_menu()
        self._entry.delete(0, tk.END)

        if isinstance(action, str) and action.startswith("_menu_"):
            # Submenu: call self.<method>()
            getattr(self, action)()
        elif isinstance(action, str) and action.startswith("_cmd_"):
            # Built-in command: call self.<method>()
            getattr(self, action)()
        elif callable(action):
            action()

    # ── Menu: Settings submenu ───────────────────────────────────────

    def _menu_settings(self) -> None:
        topmost_on = self.root.attributes("-topmost")
        status = "ON" if topmost_on else "OFF"
        items: list[tuple[str, str, object]] = [
            (
                f"Window Always on Top: {status}",
                "Keep the Agent window above all other windows",
                self._toggle_topmost,
            ),
            (
                "Open Config Editor…",
                "Edit API keys, model, YOLO, VLM, OCR, and other settings",
                self._cmd_config,
            ),
        ]
        self._show_menu(items)

    # ── Menu: Built-in command actions ───────────────────────────────

    def _cmd_help(self) -> None:
        self._print_help()

    def _cmd_tools(self) -> None:
        self._print_tools()

    def _cmd_reset(self) -> None:
        self._init_state()
        self._append_output("[reset] Tools and conversation cleared.\n\n", "system")

    def _cmd_clear(self) -> None:
        self._clear_output()

    def _cmd_stop(self) -> None:
        self._on_stop()

    def _cmd_quit(self) -> None:
        self._on_close()

    def _cmd_config(self) -> None:
        """Open the configuration editor window."""
        self._append_output("[config] Opening configuration editor…\n", "system")
        editor = config_editor.ConfigEditor(self.root)
        editor.show()

    # ── Output helpers ───────────────────────────────────────────────

    def _append_output(self, text: str, tag: str = "content") -> None:
        """Append text to the output area and scroll to the end."""
        self._output.configure(state=tk.NORMAL)
        self._output.insert(tk.END, text, tag)
        self._output.see(tk.END)
        self._output.configure(state=tk.DISABLED)

    def _clear_output(self) -> None:
        self._output.configure(state=tk.NORMAL)
        self._output.delete("1.0", tk.END)
        self._output.configure(state=tk.DISABLED)

    # ── Spinner animation ───────────────────────────────────────────────

    def _start_spinner(self, context: str = "") -> None:
        """Show the status bar and begin the rotating-spinner animation."""
        self._spinner_angle = 0.0
        self._spinner_rotations = 0
        self._status_locked = False
        self._status_exclude.clear()
        self._status_frame.pack(
            side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4),
            before=self._input_frame,
        )
        if context:
            self._status_label.configure(text=context)
            self._status_locked = True
        else:
            self._pick_and_set_status()
        self._animate_spinner()

    def _stop_spinner(self) -> None:
        """Stop the animation and hide the status bar."""
        if self._spinner_job is not None:
            self.root.after_cancel(self._spinner_job)
            self._spinner_job = None
        self._status_label.configure(text="")
        self._status_frame.pack_forget()

    def _animate_spinner(self) -> None:
        """Advance the spinner arc by one step.  After every
        _SPINNER_ROTATIONS full turns, pick a new random status text
        (unless the current status is locked by a context override)."""
        self._spinner_angle = (self._spinner_angle + _SPINNER_STEP) % 360
        self._spinner_canvas.itemconfigure(
            self._spinner_arc, start=self._spinner_angle
        )

        # Track completed rotations — only auto-change when not locked
        if self._spinner_angle < _SPINNER_STEP:
            self._spinner_rotations += 1
            if self._spinner_rotations % _SPINNER_ROTATIONS == 0:
                if not self._status_locked:
                    self._pick_and_set_status()

        self._spinner_job = self.root.after(_SPINNER_INTERVAL, self._animate_spinner)

    def _pick_and_set_status(self) -> None:
        """Pick a random status text (avoiding repeats) and display it.
        Unlocks the status so future auto-rotation changes are allowed."""
        self._status_locked = False
        available = [s for s in _STATUS_TEXTS if s not in self._status_exclude]
        if not available:
            self._status_exclude.clear()
            available = list(_STATUS_TEXTS)
        chosen = random.choice(available)
        self._status_exclude.add(chosen)
        if len(self._status_exclude) >= len(_STATUS_TEXTS):
            self._status_exclude.clear()
            self._status_exclude.add(chosen)
        self._status_label.configure(text=chosen)

    def _set_status(self, text: str) -> None:
        """Override the status text with a context string and lock it,
        preventing the rotation timer from replacing it."""
        self._status_locked = True
        self._status_label.configure(text=text)

    # ── Actions ──────────────────────────────────────────────────────

    def _on_send(self) -> None:
        if self._processing:
            return

        user_input = self._entry.get().strip()
        self._entry.delete(0, tk.END)

        if not user_input:
            return

        # Handle slash commands
        if user_input.lower() in ("/quit", "/q", "/exit"):
            self._on_close()
            return
        if user_input.lower() == "/clear":
            self._clear_output()
            return
        if user_input.lower() == "/help":
            self._print_help()
            return
        if user_input.lower() == "/tools":
            self._print_tools()
            return
        if user_input.lower() == "/reset":
            self._init_state()
            self._append_output("[reset] Tools and conversation cleared.\n\n", "system")
            return
        if user_input.lower() == "/stop":
            self._on_stop()
            return
        if user_input.lower() in ("/config", "/configuration"):
            self._cmd_config()
            return

        # Display user message
        self._append_output(f"> {user_input}\n", "user")

        self._original_request = user_input
        self._messages.append({"role": "user", "content": user_input})
        self._processing = True
        self._send_btn.configure(text="Stop", fg="#ff6666",
                                 command=self._on_stop)
        self._start_spinner()

        threading.Thread(target=self._process_turns_thread, daemon=True).start()
        self.root.after(50, self._poll_queue)

    def _on_stop(self) -> None:
        if self._processing:
            self._processing = False
            self._stop_spinner()
            self._append_output("\n[stopped by user]\n\n", "system")
            self._reset_ui_state()

    def _on_close(self) -> None:
        self._processing = False
        self._stop_spinner()
        self.root.destroy()

    def _reset_ui_state(self) -> None:
        self._send_btn.configure(text="Send", fg=FG_CONTENT,
                                 command=self._on_send)

    # ── Queue polling (UI thread) ────────────────────────────────────

    def _poll_queue(self) -> None:
        """Drain the event queue and update the UI."""
        try:
            while True:
                evt = self._queue.get_nowait()
                self._handle_event(evt)
        except queue.Empty:
            pass

        if self._processing:
            self.root.after(50, self._poll_queue)

    def _handle_event(self, evt: dict) -> None:
        kind = evt["type"]

        if kind == _EVT_REASONING:
            text = evt["text"]
            if evt.get("first"):
                self._append_output("\n", "content")  # blank line before thinking
                self._append_output("> ", "thinking")  # thinking indicator
            self._append_output(text, "thinking")

        elif kind == _EVT_CONTENT:
            text = evt["text"]
            if evt.get("first"):
                if evt.get("had_reasoning"):
                    self._append_output("\n\n", "content")  # blank line after thinking
            self._append_output(text, "content")

        elif kind == _EVT_TOOL_BEGIN:
            self._append_output(f"\n[tool] {evt['name']}\n", "tool")
            self._set_status("Applying…")

        elif kind == _EVT_TOOL_RESULT:
            tag = "tool_result_error" if evt.get("is_error") else "tool_result_success"
            status = "✗ Error" if evt.get("is_error") else "✓ OK"
            self._append_output(f"  {status} ({evt['length']} chars)\n", tag)
            self._pick_and_set_status()

        elif kind == _EVT_DONE:
            self._stop_spinner()
            self._append_output("\n\n", "content")
            self._processing = False
            self._reset_ui_state()

        elif kind == _EVT_STUCK:
            self._append_output(f"\n{evt['text']}\n", "system")
            self._pick_and_set_status()

        elif kind == _EVT_ERROR:
            self._stop_spinner()
            self._append_output(f"\n[error] {evt['text']}\n\n", "error")
            self._processing = False
            self._reset_ui_state()

        elif kind == _EVT_STEP_BEGIN:
            self._append_output(f"\n── Step {evt['step']} ──\n", "tool")
            self._set_status(f"Step {evt['step']}…")

        elif kind == _EVT_STEP_SUMMARY:
            self._append_output(f"\n[Step {evt['step']}] {evt['content']}\n", "content")

        elif kind == _EVT_STATUS:
            self._set_status(evt["text"])

    # ── Background processing thread ─────────────────────────────────

    def _process_turns_thread(self) -> None:
        """Run the step-by-step agent loop in a background thread.

        Outer loop: one iteration per step (one logical operation).
        Inner loop: tool-call rounds within a single step.
        Messages are stripped between steps so the next step only sees
        the original request + past step summaries.
        """
        original_request = self._original_request

        for step_num in range(1, config.MAX_STEPS + 1):
            if not self._processing:
                return

            # ── Per-step fresh state ──────────────────────────────────
            self._active_tools = list(self._default_tools)
            self._loaded_categories.clear()
            self._work_done = False
            self._step_completed = False
            self._step_content = ""

            self._queue.put({"type": _EVT_STEP_BEGIN, "step": step_num})

            # ── Internal tool-call loop for one step ───────────────────
            for _internal_round in range(_MAX_INTERNAL_ROUNDS):
                if not self._processing:
                    return
                try:
                    self._stream_and_process()
                except (httpx.ReadTimeout, httpx.ReadError):
                    now = time.time()
                    if (now - self._last_chunk_time > 10 and
                            now - self._last_tool_time > 30):
                        self._queue.put({
                            "type": _EVT_STUCK,
                            "text": _STUCK_RECOVERY_MSG,
                        })
                        self._messages.append({
                            "role": "user",
                            "content": _STUCK_RECOVERY_MSG,
                        })
                        self._last_chunk_time = time.time()
                        self._last_tool_time = time.time()
                        continue
                    raise

                if self._step_completed:
                    break

            if not self._processing:
                return

            if not self._step_completed:
                self._messages.append({"role": "user", "content": _INTERRUPTED_MSG})
                self._queue.put({"type": _EVT_ERROR, "text": f"Step {step_num} failed — no content produced."})
                self._processing = False
                return

            # ── Emit step summary ──────────────────────────────────────
            self._queue.put({
                "type": _EVT_STEP_SUMMARY,
                "step": step_num,
                "content": self._step_content,
            })

            # ── Check for task completion ──────────────────────────────
            if self._step_content.strip().startswith(_TASK_COMPLETE_MARKER):
                self._queue.put({"type": _EVT_DONE})
                self._processing = False
                return

            # ── Strip to step summaries for next step ──────────────────
            self._strip_to_step_summaries(original_request)

            # ── Inject continuation prompt ─────────────────────────────
            self._messages.append({"role": "user", "content": _CONTINUE_PROMPT})

        # Ran out of steps
        self._messages.append({"role": "user", "content": _INTERRUPTED_MSG})
        self._queue.put({
            "type": _EVT_ERROR,
            "text": f"Stopped after {config.MAX_STEPS} steps.",
        })
        self._processing = False

    def _stream_and_process(self) -> None:
        """Stream a response and handle tool calls.  Returns True if the
        conversation should continue (more tool calls), False if done."""
        content, tool_calls, reasoning = self._stream_response()

        if not self._processing:
            return

        # ── Tool calls — execute, then check for concurrent content ──
        if tool_calls:
            assistant_msg: dict = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            }
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            self._messages.append(assistant_msg)

            for tc in tool_calls:
                if not self._processing:
                    return
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                self._queue.put({"type": _EVT_TOOL_BEGIN, "name": fn_name})

                if fn_name == "LoadSkillCategory":
                    result = self._handle_load_category(fn_args)
                else:
                    result = self._dispatch(fn_name, fn_args)
                    self._work_done = True

                is_error = result.startswith("Error:") or result.startswith("SAFETY BLOCK")
                self._queue.put({
                    "type": _EVT_TOOL_RESULT,
                    "is_error": is_error,
                    "length": len(result),
                })

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # When content arrived together with tool_calls, the model
            # intended to stop after these tools — treat as step summary.
            if content:
                self._messages.append({"role": "assistant", "content": content})
                self._step_completed = True
                self._step_content = content
            return  # signal to continue loop

        # ── Final text response (no tool calls) ──────────────────────
        if content:
            self._messages.append({"role": "assistant", "content": content})
            self._step_completed = True
            self._step_content = content
            return

        # Empty response — inject interrupted message and try again
        self._messages.append({"role": "user", "content": _INTERRUPTED_MSG})
        self._queue.put({"type": _EVT_STUCK, "text": _INTERRUPTED_MSG})

    # ── Streaming API call ───────────────────────────────────────────

    def _stream_response(self) -> tuple[str, list[dict], str]:
        """Stream a chat completion.  Queues display events as chunks arrive.
        Returns (full_content, tool_calls, reasoning)."""
        response = self._client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=self._messages,
            tools=self._active_tools,
            stream=True,
            reasoning_effort=config.REASONING_EFFORT,
            extra_body={"thinking": {"type": "enabled"}},
        )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        had_reasoning = False
        had_first_content = False
        had_first_reasoning = False
        tool_call_chunks: dict[int, dict] = {}

        for chunk in response:
            if not self._processing:
                break

            self._last_chunk_time = time.time()
            delta = chunk.choices[0].delta

            # ── Reasoning ────────────────────────────────────────────
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                had_reasoning = True
                reasoning_parts.append(reasoning)
                self._queue.put({
                    "type": _EVT_REASONING,
                    "text": reasoning,
                    "first": not had_first_reasoning,
                })
                had_first_reasoning = True

            # ── Tool call deltas ─────────────────────────────────────
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_chunks:
                        tool_call_chunks[idx] = {
                            "id": tc_delta.id or "",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_call_chunks[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["function"]["arguments"] += tc_delta.function.arguments

            # ── Content ──────────────────────────────────────────────
            if delta.content:
                self._queue.put({
                    "type": _EVT_CONTENT,
                    "text": delta.content,
                    "first": not had_first_content,
                    "had_reasoning": had_reasoning,
                })
                had_first_content = True
                content_parts.append(delta.content)

        # Reconstruct tool_calls
        tool_calls: list[dict] = []
        for idx in sorted(tool_call_chunks.keys()):
            tc = tool_call_chunks[idx]
            tool_calls.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })

        return "".join(content_parts), tool_calls, "".join(reasoning_parts)

    # ── Tool dispatch ────────────────────────────────────────────────

    def _dispatch(self, function_name: str, arguments: dict) -> str:
        result: str
        if function_name.startswith("KeyboardAction_"):
            result = exec_keyboard(function_name, arguments)
        elif function_name.startswith("MouseAction_"):
            result = exec_mouse(function_name, arguments)
        elif function_name.startswith("ShellAction_"):
            self._queue.put({"type": _EVT_STATUS, "text": "Pending Security Check via LLM"})
            result = exec_shell(function_name, arguments)
        elif function_name.startswith("ScreenCaptureAction_"):
            result = exec_screen_capture(function_name, arguments)
        elif function_name.startswith("VLM_Action_"):
            result = exec_vlm(function_name, arguments)
        elif function_name.startswith("BasicFunction_"):
            result = exec_basic(function_name, arguments)
        else:
            return f"Error: unrecognized function '{function_name}'"

        self._last_tool_time = time.time()
        return result

    def _handle_load_category(self, args: dict) -> str:
        category = args.get("category", "")
        try:
            tools = tool_loader.load_category_tools(category)
        except ValueError as e:
            return str(e)

        if category in self._loaded_categories:
            tool_names = [t["function"]["name"] for t in tools]
            return f"Category '{category}' already loaded: {', '.join(tool_names)}"

        self._loaded_categories.add(category)
        self._active_tools.extend(tools)
        desc = tool_loader.get_category_description(category)
        tool_names = [t["function"]["name"] for t in tools]
        return f"Loaded '{category}' ({desc}). Available: {', '.join(tool_names)}"

    # ── Slash commands ───────────────────────────────────────────────

    def _print_help(self) -> None:
        lines = [
            "\n",
            "Commands:\n",
            "  /help     Show this message\n",
            "  /tools    List currently loaded tools\n",
            "  /reset    Clear conversation and reload entry tools\n",
            "  /clear    Clear the output display\n",
            "  /stop     Stop the current generation\n",
            "  /config   Open configuration editor (API keys, model, etc.)\n",
            "  /setting  Open settings (window topmost, etc.)\n",
            "  /quit     Exit\n",
            "\n",
            "Tip: Type / and use Up/Down arrows to navigate the menu.\n",
            "\n",
            "Available categories:\n",
        ]
        self._append_output("".join(lines), "system")

        entry = tool_loader.load_entry_point()
        cats = entry.get("available_categories", {})
        for name, info in cats.items():
            marker = " [loaded]" if name in self._loaded_categories else ""
            self._append_output(
                f"  {name} ({info['tool_count']} tools){marker}: {info['description']}\n",
                "system",
            )
        self._append_output("\n", "system")

    def _print_tools(self) -> None:
        self._append_output("\n", "system")
        if not self._active_tools:
            self._append_output("  (no tools loaded)\n", "system")
            return
        for tool in self._active_tools:
            fn = tool["function"]
            params = list(fn.get("parameters", {}).get("properties", {}).keys())
            self._append_output(
                f"  {fn['name']}({', '.join(params) if params else '—'})\n",
                "system",
            )
        self._append_output("\n", "system")

    # ── Entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        if not warning_notice.show_gui_warning(self.root):
            self.root.destroy()
            return
        self.root.mainloop()


def main() -> None:
    app = DesktopAgentGUI()
    app.run()


if __name__ == "__main__":
    main()
