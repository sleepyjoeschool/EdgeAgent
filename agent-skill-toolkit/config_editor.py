"""
Configuration Editor GUI
=========================
A dark-themed Tkinter window for editing config.py settings.

- Reads current effective values from config (including config_override.json).
- Saves user changes to config_override.json.
- Sensitive fields (API keys, passwords) are masked by default with a
  show/hide toggle.
- Fields backed by environment variables show the env-var name and a notice
  that the value is read-only unless the env var is unset.
- The override file only contains values the user has explicitly changed
  from the hard-coded default.

Usage (standalone):
    python config_editor.py

Usage (embedded):
    from config_editor import ConfigEditor
    editor = ConfigEditor(parent_window)
    editor.show()
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

# ── Path setup ────────────────────────────────────────────────────────────
_TOOLKIT_DIR = Path(__file__).resolve().parent
if str(_TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLKIT_DIR))

import tkinter as tk
from tkinter import filedialog, messagebox

import config

# ── Colour constants (match gui.py) ────────────────────────────────────────
BG = "#000000"
FG_CONTENT = "#ffffff"
FG_THINKING = "#888888"
FG_TOOL = "#00bfff"
FG_USER = "#66cc66"
FG_SYSTEM = "#cc6666"
FG_DIM = "#666666"
BG_WIDGET = "#111111"
BG_HOVER = "#1a1a2e"
BG_SECTION = "#141428"

FONT = ("Consolas", 11)
FONT_BOLD = ("Consolas", 11, "bold")
FONT_HEADER = ("Consolas", 13, "bold")
FONT_SMALL = ("Consolas", 9)

OVERRIDE_FILE = _TOOLKIT_DIR / "config_override.json"


# ── Field definitions ─────────────────────────────────────────────────────
# Each entry: (config_key, label, field_type, extra)
#   field_type: "string" | "password" | "int" | "choice" | "bool" | "path"
#   extra: for "choice" → list of choices; unused otherwise (or ())
#   section: category name for grouping
#   env_var: environment variable name (or "" if none)
#   default: hard-coded default as written in config.py

FIELD_DEFS = [
    # ── DeepSeek API ───────────────────────────────────────────────────
    {
        "key": "DEEPSEEK_API_KEY",
        "label": "API Key",
        "type": "password",
        "section": "DeepSeek API",
        "env_var": "SKILL_DEEPSEEK_API_KEY",
        "default": "",
        "tip": "DeepSeek API authentication key (set via SKILL_DEEPSEEK_API_KEY env var)",
    },
    {
        "key": "DEEPSEEK_BASE_URL",
        "label": "Base URL",
        "type": "string",
        "section": "DeepSeek API",
        "env_var": "SKILL_DEEPSEEK_BASE_URL",
        "default": "https://api.deepseek.com",
        "tip": "DeepSeek API endpoint base URL",
    },
    {
        "key": "DEEPSEEK_MODEL",
        "label": "Model",
        "type": "string",
        "section": "DeepSeek API",
        "env_var": "SKILL_DEEPSEEK_MODEL",
        "default": "deepseek-v4-pro",
        "tip": "Model identifier (e.g. deepseek-v4-pro, deepseek-chat)",
    },
    {
        "key": "REASONING_EFFORT",
        "label": "Reasoning Effort",
        "type": "choice",
        "choices": ["low", "medium", "high", "max"],
        "section": "DeepSeek API",
        "env_var": "SKILL_REASONING_EFFORT",
        "default": "high",
        "tip": 'Reasoning effort for DeepSeek thinking mode (only applies when thinking is enabled)',
    },

    # ── YOLO v8 ────────────────────────────────────────────────────────
    {
        "key": "YOLO_INFERENCE_MODE",
        "label": "Inference Mode",
        "type": "choice",
        "choices": ["local", "cloud"],
        "section": "YOLO v8",
        "env_var": "SKILL_YOLO_INFERENCE_MODE",
        "default": "cloud",
        "tip": '"local" = use on-device .pt model; "cloud" = use remote API',
    },
    {
        "key": "YOLO_MODEL_PATH",
        "label": "Model Path (.pt/.onnx)",
        "type": "path",
        "section": "YOLO v8",
        "env_var": "SKILL_YOLO_MODEL",
        "default": str(
            Path(config.ROOT_DIR) / "agent-skill-toolkit" / "models" / "yolo_placeholder.pt"
        ),
        "tip": "Path to YOLO v8 weights file (used when inference mode is 'local')",
    },
    {
        "key": "YOLO_CLOUD_API_URL",
        "label": "Cloud API URL",
        "type": "string",
        "section": "YOLO v8",
        "env_var": "SKILL_YOLO_CLOUD_URL",
        "default": "",
        "tip": "Remote YOLO inference endpoint (used when inference mode is 'cloud')",
    },
    {
        "key": "YOLO_CLOUD_API_KEY",
        "label": "Cloud API Key",
        "type": "password",
        "section": "YOLO v8",
        "env_var": "SKILL_YOLO_CLOUD_API_KEY",
        "default": "",
        "tip": "Authentication key for the cloud YOLO service",
    },

    # ── VLM (Qwen-VL) ──────────────────────────────────────────────────
    {
        "key": "VLM_API_URL",
        "label": "VLM API URL",
        "type": "string",
        "section": "VLM & OCR",
        "env_var": "SKILL_VLM_API_URL",
        "default": "",
        "tip": "Qwen-VL multimodal inference service endpoint",
    },
    {
        "key": "VLM_AUTH_KEY",
        "label": "VLM Auth Key",
        "type": "password",
        "section": "VLM & OCR",
        "env_var": "SKILL_VLM_AUTH_KEY",
        "default": "",
        "tip": "Authentication key for the VLM service",
    },
    {
        "key": "VLM_SSL_VERIFY",
        "label": "SSL Verify",
        "type": "bool",
        "section": "VLM & OCR",
        "env_var": "",
        "default": True,
        "tip": "Enable SSL certificate verification for VLM connections (disable only for dev)",
    },
    {
        "key": "VLM_PINNED_CERT_PEM",
        "label": "Pinned Certificate (PEM)",
        "type": "multiline",
        "section": "VLM & OCR",
        "env_var": "",
        "default": "",
        "tip": "Custom CA certificate in PEM format for VLM server (leave empty to use system trust store)",
    },

    # ── OCR ─────────────────────────────────────────────────────────────
    {
        "key": "OCR_URL",
        "label": "OCR Service URL",
        "type": "string",
        "section": "VLM & OCR",
        "env_var": "SKILL_OCR_URL",
        "default": "http://127.0.0.1:35001/api/ocr",
        "tip": "UMNI OCR service endpoint",
    },

    # ── Safety ──────────────────────────────────────────────────────────
    {
        "key": "MAX_STEPS",
        "label": "Max Steps",
        "type": "int",
        "section": "Safety & Limits",
        "env_var": "",
        "default": 50,
        "tip": "Maximum number of steps (cycles) per task — the agent auto-continues until TASK_COMPLETE or this limit",
        "min": 1,
        "max": 500,
    },

    # ── Web Panel ───────────────────────────────────────────────────────
    {
        "key": "WEB_PANEL_PASSWORD",
        "label": "Panel Password",
        "type": "password",
        "section": "Web Panel",
        "env_var": "SKILL_WEB_PANEL_PASSWORD",
        "default": "",
        "tip": "Password for logging into the web control panel (set via SKILL_WEB_PANEL_PASSWORD env var)",
    },
    {
        "key": "WEB_PANEL_DESKTOP_VIEW",
        "label": "Desktop View",
        "type": "bool",
        "section": "Web Panel",
        "env_var": "",
        "default": True,
        "tip": "Enable remote desktop viewing in the web control panel sidebar",
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────

def _get_hardcoded_defaults() -> dict[str, Any]:
    """Extract the hard-coded defaults from config.py source.

    Falls back to FIELD_DEFS defaults if the source is unreadable.
    """
    defaults: dict[str, Any] = {}
    config_path = _TOOLKIT_DIR / "config.py"
    try:
        source = config_path.read_text(encoding="utf-8")
    except OSError:
        return {fd["key"]: fd["default"] for fd in FIELD_DEFS}

    for fd in FIELD_DEFS:
        key = fd["key"]
        # Try to find `KEY = value` in the source
        import re
        pattern = rf'^{key}\s*=\s*(.+?)$'
        for line in source.splitlines():
            m = re.match(pattern, line.strip())
            if m:
                raw = m.group(1).strip()
                # Strip enclosing parentheses (used for grouping in config.py)
                if raw.startswith("(") and raw.endswith(")"):
                    raw = raw[1:-1].strip()
                # Try to eval simple literals
                try:
                    val = eval(raw, {"__builtins__": {}})
                    defaults[key] = val
                except Exception:
                    defaults[key] = fd["default"]
                break
        else:
            defaults[key] = fd["default"]
    return defaults


def _get_effective_value(key: str) -> Any:
    """Get the current effective value of a config key (already overridden)."""
    try:
        return getattr(config, key)
    except AttributeError:
        return _get_hardcoded_defaults().get(key, "")


def _env_is_set(env_var: str) -> bool:
    """Check whether an environment variable is explicitly set."""
    return bool(env_var and os.environ.get(env_var) is not None)


def _load_overrides() -> dict[str, Any]:
    """Load the current config_override.json."""
    if OVERRIDE_FILE.exists():
        try:
            return json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_overrides(overrides: dict[str, Any]) -> None:
    """Write overrides to config_override.json."""
    if overrides:
        OVERRIDE_FILE.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        # Remove the file if empty
        if OVERRIDE_FILE.exists():
            OVERRIDE_FILE.unlink()


# ── Config Editor Window ────────────────────────────────────────────────

class ConfigEditor:
    """Modal configuration editor window.

    Instantiate with a parent Tk widget, then call .show() to open.
    """

    def __init__(self, parent: tk.Misc | None = None) -> None:
        self._parent = parent
        self._window: tk.Toplevel | None = None
        self._field_widgets: dict[str, dict[str, Any]] = {}  # key → widget info
        self._show_sensitive: bool = False
        self._hardcoded: dict[str, Any] = _get_hardcoded_defaults()
        self._overrides: dict[str, Any] = _load_overrides()
        self._modified_keys: set[str] = set()

        # Build section → fields mapping
        self._sections: dict[str, list[dict]] = {}
        for fd in FIELD_DEFS:
            sec = fd["section"]
            self._sections.setdefault(sec, []).append(fd)

    # ── Public API ─────────────────────────────────────────────────────

    def _reload_config(self) -> None:
        """Reload the config module so we pick up any external changes."""
        importlib.reload(config)
        self._overrides = _load_overrides()

    def show(self) -> None:
        """Create and display the editor window (modal)."""
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            return

        self._reload_config()
        self._window = tk.Toplevel(self._parent)
        self._window.title("Configuration Editor")
        self._window.configure(bg=BG)
        self._window.geometry("680x720")
        self._window.minsize(480, 500)
        self._window.transient(self._parent)
        if self._parent:
            self._window.grab_set()

        self._build_ui()
        self._populate_fields()
        self._fill_all_fields()
        self._bind_all_changes()

        self._window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._window.bind("<Escape>", lambda e: self._on_close())

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        w = self._window

        # ── Title bar ──────────────────────────────────────────────────
        title_frame = tk.Frame(w, bg=BG)
        title_frame.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(14, 4))

        tk.Label(
            title_frame,
            text="Configuration Editor",
            font=FONT_HEADER,
            bg=BG,
            fg=FG_TOOL,
        ).pack(side=tk.LEFT)

        # Show/hide sensitive toggle
        self._show_btn = tk.Button(
            title_frame,
            text="Show Secrets",
            font=FONT_SMALL,
            bg=BG_WIDGET,
            fg=FG_THINKING,
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=2,
            command=self._toggle_sensitive,
            activebackground=BG_HOVER,
            activeforeground=FG_CONTENT,
            cursor="hand2",
        )
        self._show_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # ── Separator ──────────────────────────────────────────────────
        sep = tk.Frame(w, bg="#222222", height=1)
        sep.pack(side=tk.TOP, fill=tk.X, padx=12)

        # ── Scrollable content area ────────────────────────────────────
        self._canvas = tk.Canvas(w, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(w, orient=tk.VERTICAL, command=self._canvas.yview)
        self._scroll_frame = tk.Frame(self._canvas, bg=BG)

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )

        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor=tk.NW, tags="inner"
        )

        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=8)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=8, padx=(0, 4))

        # Mouse wheel scrolling
        def _on_mousewheel(e):
            self._canvas.yview_scroll(-1 * (e.delta // 120), "units")

        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # Resize inner frame width to match canvas
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # ── Section containers ─────────────────────────────────────────
        self._section_frames: dict[str, tk.Frame] = {}
        for section_name in self._sections:
            sf = self._build_section(self._scroll_frame, section_name)
            sf.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(2, 8))
            self._section_frames[section_name] = sf

        # ── Bottom button bar ──────────────────────────────────────────
        btn_frame = tk.Frame(w, bg=BG)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(4, 12))

        self._status_label = tk.Label(
            btn_frame,
            text="",
            font=FONT_SMALL,
            bg=BG,
            fg=FG_USER,
            anchor=tk.W,
        )
        self._status_label.pack(side=tk.LEFT)

        for text, color, cmd in [
            ("Reset All", FG_SYSTEM, self._reset_all),
            ("Save", FG_USER, self._save),
            ("Close", FG_DIM, self._on_close),
        ]:
            btn = tk.Button(
                btn_frame,
                text=text,
                font=FONT_BOLD,
                bg=BG_WIDGET,
                fg=color,
                relief=tk.FLAT,
                borderwidth=0,
                padx=16,
                pady=6,
                command=cmd,
                activebackground=BG_HOVER,
                activeforeground=FG_CONTENT,
                cursor="hand2",
            )
            btn.pack(side=tk.RIGHT, padx=(8, 0))

    def _build_section(self, parent: tk.Frame, title: str) -> tk.Frame:
        """Build a collapsible section frame with a header."""
        section = tk.Frame(parent, bg=BG, bd=0)

        # Header
        header = tk.Frame(section, bg=BG_SECTION)
        header.pack(side=tk.TOP, fill=tk.X)

        tk.Label(
            header,
            text=f"  {title}",
            font=FONT_BOLD,
            bg=BG_SECTION,
            fg=FG_TOOL,
            anchor=tk.W,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(6, 6))

        # Fields container
        fields_frame = tk.Frame(section, bg=BG, bd=0)
        fields_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(4, 2))
        section._fields_frame = fields_frame  # type: ignore[attr-defined]

        return section

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Keep the inner frame width equal to the canvas width."""
        w = event.width
        self._canvas.itemconfig(self._canvas_window, width=w)

    # ── Field population ───────────────────────────────────────────────

    def _populate_fields(self) -> None:
        """Create input widgets for every field definition."""
        for fd in FIELD_DEFS:
            sec_name = fd["section"]
            parent = self._section_frames[sec_name]._fields_frame
            self._create_field_row(parent, fd)

    def _create_field_row(self, parent: tk.Frame, fd: dict) -> None:
        """Create a single field row: description label on top, widget below."""
        key = fd["key"]

        row = tk.Frame(parent, bg=BG)
        row.pack(side=tk.TOP, fill=tk.X, pady=(4, 6))

        # ── Description line ───────────────────────────────────────────
        desc_frame = tk.Frame(row, bg=BG)
        desc_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(
            desc_frame,
            text=fd["label"],
            font=FONT_BOLD,
            bg=BG,
            fg=FG_CONTENT,
            anchor=tk.W,
        ).pack(side=tk.LEFT)

        # Env var badge (inline after label)
        if fd["env_var"]:
            env_set = _env_is_set(fd["env_var"])
            badge_color = "#997a00" if env_set else FG_DIM
            badge_text = f"  env: {fd['env_var']}" + (" (set)" if env_set else "")
            tk.Label(
                desc_frame,
                text=badge_text,
                font=FONT_SMALL,
                bg=BG,
                fg=badge_color,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

        # Tip shown as subtle hint below the label
        if fd.get("tip"):
            tk.Label(
                row,
                text=fd["tip"],
                font=FONT_SMALL,
                bg=BG,
                fg=FG_DIM,
                anchor=tk.W,
            ).pack(side=tk.TOP, anchor=tk.W, pady=(1, 0))

        # ── Widget ─────────────────────────────────────────────────────
        if fd["type"] == "bool":
            widget = self._make_bool_widget(row, fd)
        elif fd["type"] == "choice":
            widget = self._make_choice_widget(row, fd)
        elif fd["type"] == "int":
            widget = self._make_int_widget(row, fd)
        elif fd["type"] == "path":
            widget = self._make_path_widget(row, fd)
        elif fd["type"] == "multiline":
            widget = self._make_multiline_widget(row, fd)
        elif fd["type"] == "password":
            widget = self._make_password_widget(row, fd)
        else:
            widget = self._make_string_widget(row, fd)

        # ── Status badge (modified / override) ─────────────────────────
        badge_lbl = tk.Label(
            row,
            text="",
            font=FONT_SMALL,
            bg=BG,
            fg=FG_USER,
            anchor=tk.W,
        )
        badge_lbl.pack(side=tk.TOP, anchor=tk.W, pady=(2, 0))

        self._field_widgets[key] = {
            "widget": widget,
            "def": fd,
            "badge": badge_lbl,
            "frame": row,
        }

    # ── Widget factories ───────────────────────────────────────────────

    @staticmethod
    def _wrap_entry(entry: tk.Entry, parent: tk.Frame) -> tk.Frame:
        """Wrap an Entry in a Frame with real padding for text inset.

        tkinter's ipadx only affects requested width — it does NOT add
        visible padding inside the Entry.  Wrapping in a Frame with padx
        guarantees actual text-to-border spacing.
        """
        frame = tk.Frame(parent, bg=BG_WIDGET)
        frame.pack(side=tk.TOP, fill=tk.X)
        entry.pack(side=tk.TOP, fill=tk.X, padx=6, pady=5)
        frame._entry = entry  # type: ignore[attr-defined]  # so get/set can reach it
        return frame

    def _make_string_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        entry = tk.Entry(
            parent,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        return self._wrap_entry(entry, parent)

    def _make_password_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        entry = tk.Entry(
            parent,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            show="*",
        )
        return self._wrap_entry(entry, parent)

    def _make_bool_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        var = tk.BooleanVar()
        frame = tk.Frame(parent, bg=BG)
        frame.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))
        cb = tk.Checkbutton(
            frame,
            text="On / Off",
            variable=var,
            bg=BG,
            fg=FG_CONTENT,
            selectcolor=BG_WIDGET,
            activebackground=BG,
            activeforeground=FG_TOOL,
            font=FONT,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
        )
        cb.pack(side=tk.LEFT, anchor=tk.W)
        frame._var = var  # type: ignore[attr-defined]
        frame._cb = cb     # type: ignore[attr-defined]
        return frame

    def _make_choice_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        """Pure-tk dropdown — avoids ttk native-theme text issues on Windows."""
        frame = tk.Frame(parent, bg=BG)
        frame.pack(side=tk.TOP, fill=tk.X)

        var = tk.StringVar()
        btn = tk.Menubutton(
            frame,
            textvariable=var,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            activebackground=BG_HOVER,
            activeforeground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=4,
            anchor=tk.W,
            direction="below",
            cursor="hand2",
        )
        btn.pack(side=tk.TOP, fill=tk.X)

        menu = tk.Menu(
            btn,
            tearoff=0,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            activebackground=BG_HOVER,
            activeforeground=FG_TOOL,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=1,
        )
        for choice in fd["choices"]:
            menu.add_radiobutton(
                label=choice,
                variable=var,
                value=choice,
                selectcolor=BG_WIDGET,
            )
        btn.configure(menu=menu)

        # Arrow indicator
        arrow = tk.Label(
            frame,
            text="",
            bg=BG_WIDGET,
            fg=FG_TOOL,
            font=FONT,
            padx=6,
        )
        arrow.place(relx=1.0, x=-6, rely=0.5, anchor=tk.E)
        arrow.bind("<Button-1>", lambda e: menu.post(
            btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height()))

        frame._var = var       # type: ignore[attr-defined]
        frame._btn = btn       # type: ignore[attr-defined]
        frame._menu = menu     # type: ignore[attr-defined]
        return frame

    def _make_int_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        lo = fd.get("min", 1)
        hi = fd.get("max", 9999)
        sb = tk.Spinbox(
            parent,
            from_=lo,
            to=hi,
            increment=1,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            readonlybackground=BG_WIDGET,
        )
        frame = tk.Frame(parent, bg=BG_WIDGET)
        frame.pack(side=tk.TOP, fill=tk.X)
        sb.pack(side=tk.TOP, fill=tk.X, padx=6, pady=5)
        frame._entry = sb  # type: ignore[attr-defined]
        return frame

    def _make_path_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        outer = tk.Frame(parent, bg=BG)
        outer.pack(side=tk.TOP, fill=tk.X)

        # Entry wrapper with padding
        entry_frame = tk.Frame(outer, bg=BG_WIDGET)
        entry_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        entry = tk.Entry(
            entry_frame,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        entry.pack(side=tk.TOP, fill=tk.X, padx=6, pady=5)

        def browse():
            path = filedialog.askopenfilename(
                title=f"Select {fd['label']}",
                filetypes=[
                    ("Model files", "*.pt *.onnx *.pth *.bin"),
                    ("All files", "*.*"),
                ],
            )
            if path:
                entry.delete(0, tk.END)
                entry.insert(0, path)
                self._mark_modified(fd["key"])

        btn = tk.Button(
            outer,
            text="...",
            font=FONT_BOLD,
            bg=BG_WIDGET,
            fg=FG_TOOL,
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=5,
            command=browse,
            activebackground=BG_HOVER,
            activeforeground=FG_CONTENT,
            cursor="hand2",
        )
        btn.pack(side=tk.RIGHT, padx=(4, 0))

        outer._entry = entry  # type: ignore[attr-defined]
        return outer

    def _make_multiline_widget(self, parent: tk.Frame, fd: dict) -> tk.Frame:
        """A small text area with a vertical scrollbar."""
        frame = tk.Frame(parent, bg=BG_WIDGET)
        frame.pack(side=tk.TOP, fill=tk.X)

        text = tk.Text(
            frame,
            bg=BG_WIDGET,
            fg=FG_CONTENT,
            insertbackground=FG_CONTENT,
            font=FONT,
            relief=tk.FLAT,
            borderwidth=0,
            wrap=tk.WORD,
            height=4,
            padx=4,
            pady=4,
        )
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=sb.set)

        frame._text = text  # type: ignore[attr-defined]
        return frame

    # ── Tooltip ────────────────────────────────────────────────────────

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Attach a hover tooltip to a widget."""
        tip_window: tk.Toplevel | None = None

        def show(_e):
            nonlocal tip_window
            if tip_window is not None:
                return
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip_window = tk.Toplevel(widget)
            tip_window.wm_overrideredirect(True)
            tip_window.wm_geometry(f"+{x}+{y}")
            tip_window.attributes("-topmost", True)
            lbl = tk.Label(
                tip_window,
                text=text,
                bg="#333333",
                fg="#dddddd",
                font=FONT_SMALL,
                relief=tk.FLAT,
                borderwidth=0,
                padx=6,
                pady=3,
            )
            lbl.pack()

        def hide(_e):
            nonlocal tip_window
            if tip_window is not None:
                tip_window.destroy()
                tip_window = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    # ── Read / Write field values ──────────────────────────────────────

    def _set_widget_value(self, key: str, value: Any) -> None:
        """Set the widget display value for a given config key."""
        info = self._field_widgets.get(key)
        if not info:
            return
        w = info["widget"]
        fd = info["def"]
        ftype = fd["type"]

        if ftype == "bool":
            w._var.set(bool(value))
        elif ftype == "choice":
            w._var.set(str(value))
        elif ftype == "multiline":
            w._text.delete("1.0", tk.END)
            w._text.insert("1.0", str(value) if value else "")
        elif ftype in ("string", "password", "int", "path"):
            # These are Frames wrapping an Entry or Spinbox
            w._entry.delete(0, tk.END)
            w._entry.insert(0, str(value))
        else:
            w.delete(0, tk.END)
            w.insert(0, str(value))

        self._refresh_badge(key)

    def _get_widget_value(self, key: str) -> Any:
        """Read the current value from the widget for a config key."""
        info = self._field_widgets.get(key)
        if not info:
            return None
        w = info["widget"]
        fd = info["def"]
        ftype = fd["type"]

        if ftype == "bool":
            return bool(w._var.get())
        elif ftype == "choice":
            return w._var.get()
        elif ftype == "multiline":
            return w._text.get("1.0", tk.END).strip()
        elif ftype in ("string", "password", "int", "path"):
            val = w._entry.get().strip()
            if ftype == "int":
                try:
                    return int(val)
                except ValueError:
                    return fd["default"]
            return val
        else:
            return w.get().strip()

    def _fill_all_fields(self) -> None:
        """Populate all widgets with current effective values."""
        for key in self._field_widgets:
            value = _get_effective_value(key)
            self._set_widget_value(key, value)

    # ── Badge / status helpers ─────────────────────────────────────────

    def _refresh_badge(self, key: str) -> None:
        """Update the override/env badge for a field."""
        info = self._field_widgets.get(key)
        if not info:
            return
        fd = info["def"]
        badge = info["badge"]

        if fd["env_var"] and _env_is_set(fd["env_var"]):
            badge.configure(text="Set by environment variable (read-only)", fg="#997a00")
            # Disable the widget
            self._set_widget_enabled(key, False)
        elif key in self._modified_keys:
            badge.configure(text="Modified — will be saved", fg=FG_USER)
            self._set_widget_enabled(key, True)
        elif key in self._overrides:
            badge.configure(text="Override active", fg=FG_TOOL)
            self._set_widget_enabled(key, True)
        else:
            badge.configure(text="", fg=FG_DIM)
            self._set_widget_enabled(key, True)

    def _set_widget_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable editing of a widget.

        IMPORTANT: We NEVER use tkinter's 'readonly' or 'disabled' states
        because on Windows those force a system-default background (light
        gray/white) which makes white text invisible on a dark theme.

        Instead we keep state='normal' and manually block/unblock input.
        """
        info = self._field_widgets.get(key)
        if not info:
            return
        w = info["widget"]
        fd = info["def"]

        if enabled:
            # Restore normal widget properties
            if fd["type"] == "bool":
                w._cb.configure(state=tk.NORMAL)
            elif fd["type"] == "multiline":
                w._text.unbind("<Key>")
                w._text.configure(state=tk.NORMAL, bg=BG_WIDGET, fg=FG_CONTENT)
            elif fd["type"] == "choice":
                w._btn.configure(state=tk.NORMAL)
            elif fd["type"] in ("string", "password", "int", "path"):
                w._entry.unbind("<Key>")
                w._entry.configure(state=tk.NORMAL, bg=BG_WIDGET, fg=FG_CONTENT)
                # Also restore wrapper frame bg
                w.configure(bg=BG_WIDGET)
        else:
            # Disable: keep state='normal' but block keyboard input
            if fd["type"] == "bool":
                w._cb.configure(state=tk.DISABLED)
            elif fd["type"] == "multiline":
                w._text.bind("<Key>", lambda e: "break")
                w._text.configure(state=tk.NORMAL, bg="#1a1a1a", fg=FG_DIM)
            elif fd["type"] == "choice":
                w._btn.configure(state=tk.DISABLED)
            elif fd["type"] in ("string", "password", "int", "path"):
                w._entry.bind("<Key>", lambda e: "break")
                w._entry.configure(state=tk.NORMAL, bg="#1a1a1a", fg=FG_DIM)
                w.configure(bg="#1a1a1a")

    def _mark_modified(self, key: str) -> None:
        """Mark a field as modified by the user."""
        effective = _get_effective_value(key)
        current = self._get_widget_value(key)
        if current != effective:
            self._modified_keys.add(key)
        else:
            self._modified_keys.discard(key)
        self._refresh_badge(key)

    # ── Actions ────────────────────────────────────────────────────────

    def _toggle_sensitive(self) -> None:
        """Toggle password field visibility."""
        self._show_sensitive = not self._show_sensitive
        show_char = "" if self._show_sensitive else "*"
        btn_text = "Hide Secrets" if self._show_sensitive else "Show Secrets"
        self._show_btn.configure(text=btn_text)

        for info in self._field_widgets.values():
            if info["def"]["type"] == "password":
                info["widget"]._entry.configure(show=show_char)

    def _save(self) -> None:
        """Collect modified values and write to config_override.json."""
        new_overrides: dict[str, Any] = {}

        # Start with existing overrides
        new_overrides.update(self._overrides)

        # Apply modifications
        for key in self._modified_keys:
            value = self._get_widget_value(key)
            default = self._hardcoded.get(key)
            if value != default:
                new_overrides[key] = value
            elif key in new_overrides:
                del new_overrides[key]

        # Remove keys that match the hard-coded default
        keys_to_remove = [
            k for k, v in new_overrides.items()
            if v == self._hardcoded.get(k)
        ]
        for k in keys_to_remove:
            del new_overrides[k]

        _save_overrides(new_overrides)
        self._overrides = new_overrides
        self._modified_keys.clear()

        # Update badges
        for key in self._field_widgets:
            self._refresh_badge(key)

        self._status_label.configure(text="Settings saved to config_override.json")
        self._window.after(3000, lambda: self._status_label.configure(text=""))

    def _reset_all(self) -> None:
        """Reset all fields to hard-coded defaults and remove the override file."""
        if not messagebox.askyesno(
            "Reset All Settings",
            "This will:\n\n"
            "  1. Reset all fields to their hard-coded defaults\n"
            "  2. Delete config_override.json\n\n"
            "This cannot be undone. Continue?",
            parent=self._window,
            icon="warning",
        ):
            return

        self._overrides = {}
        self._modified_keys.clear()

        if OVERRIDE_FILE.exists():
            OVERRIDE_FILE.unlink()

        for key in self._field_widgets:
            default = self._hardcoded.get(key, "")
            self._set_widget_value(key, default)

        self._status_label.configure(text="All settings reset to defaults")
        self._window.after(3000, lambda: self._status_label.configure(text=""))

    def _on_close(self) -> None:
        """Close the editor window."""
        if self._modified_keys:
            if messagebox.askyesno(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=self._window,
                icon="question",
            ):
                self._save()

        if self._window:
            self._window.grab_release()
            self._window.destroy()
            self._window = None

    # ── Event binding helpers ──────────────────────────────────────────

    def _bind_change(self, key: str, widget: tk.Widget, event: str = "<KeyRelease>") -> None:
        """Bind a change event to mark a field as modified."""
        def handler(_e=None):
            self._mark_modified(key)

        # path/string/password/int widgets are Frames wrapping an Entry
        if isinstance(widget, tk.Frame) and hasattr(widget, "_entry"):
            widget._entry.bind(event, handler)
        # multiline widget is a Frame wrapping a Text
        elif isinstance(widget, tk.Frame) and hasattr(widget, "_text"):
            widget._text.bind(event, handler)
        # bool widget — checkbutton in a Frame
        elif isinstance(widget, tk.Frame) and hasattr(widget, "_cb"):
            widget._cb.configure(command=lambda: self._mark_modified(key))
        # choice widget — menubutton in a Frame with StringVar
        elif isinstance(widget, tk.Frame) and hasattr(widget, "_var") and hasattr(widget, "_btn"):
            widget._var.trace_add("write", handler)
        else:
            widget.bind(event, handler)

    def _bind_all_changes(self) -> None:
        """Bind change handlers to all field widgets."""
        for key, info in self._field_widgets.items():
            self._bind_change(key, info["widget"])


# ── Standalone entry point ─────────────────────────────────────────────

def main() -> None:
    """Open the config editor as a standalone window."""
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    editor = ConfigEditor()
    editor.show()

    # When the editor closes, destroy the hidden root
    def on_editor_close():
        root.destroy()

    if editor._window:
        editor._window.protocol("WM_DELETE_WINDOW", lambda: (editor._on_close(), on_editor_close()))
        editor._window.bind("<Escape>", lambda e: (editor._on_close(), on_editor_close()))

    root.mainloop()


if __name__ == "__main__":
    main()
