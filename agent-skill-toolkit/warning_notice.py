"""
Security warning notice shown at application startup.

Reads warning.md, displays the full content, and offers Continue / Skip Today /
Never Show Again options.  Preferences are persisted to disk so the user
isn't nagged on every launch.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_WARNING_MD = Path(__file__).resolve().parent.parent.parent.parent / "warning.md"

_PREF_FILE = Path.home() / ".agent_skill_toolkit_warning.json"


def _load_prefs() -> dict:
    if _PREF_FILE.exists():
        try:
            return json.loads(_PREF_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_prefs(prefs: dict) -> None:
    _PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PREF_FILE.write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_warning_text() -> str:
    """Read and return the full content of warning.md."""
    if not _WARNING_MD.exists():
        return (
            "Warning file not found.\n"
            "This is a Computer Use Agent that can directly operate your system.\n"
            "It may cause serious damage. Please review the security documentation."
        )

    return _WARNING_MD.read_text(encoding="utf-8").strip()


# ── Public API ──────────────────────────────────────────────────────────────

def should_show_warning() -> bool:
    prefs = _load_prefs()
    if prefs.get("never_show", False):
        return False
    if prefs.get("skip_today") == str(date.today()):
        return False
    return True


def set_skip_today() -> None:
    prefs = _load_prefs()
    prefs["skip_today"] = str(date.today())
    _save_prefs(prefs)


def set_never_show() -> None:
    prefs = _load_prefs()
    prefs["never_show"] = True
    _save_prefs(prefs)


# ── CLI warning ─────────────────────────────────────────────────────────────

def show_cli_warning() -> bool:
    """Display warning in the terminal.  Returns True to continue, False to exit."""
    if not should_show_warning():
        return True

    full_text = _get_warning_text()
    width = 68

    def _box(text: str) -> str:
        return "║" + text.center(width - 2) + "║"

    def _wrap(text: str, indent: int = 4) -> list[str]:
        """Simple word-wrap for terminal output."""
        out: list[str] = []
        max_w = width - 2 - indent
        for paragraph in text.split("\n"):
            words = paragraph.split()
            cur = ""
            for w in words:
                trial = (cur + " " + w).strip()
                if len(trial) <= max_w:
                    cur = trial
                else:
                    if cur:
                        out.append(cur)
                    cur = w
            if cur:
                out.append(cur)
        return out

    print()
    print("╔" + "═" * (width - 2) + "╗")
    print(_box("⚠  SECURITY NOTICE — Computer Use Agent"))
    print(_box(""))

    for line in _wrap(full_text):
        print("║  " + line.ljust(width - 4) + "║")

    print(_box(""))
    print(_box("[C] Continue   [T] Don't show today   [N] Never show again"))
    print("╚" + "═" * (width - 2) + "╝")
    print()

    while True:
        try:
            choice = input("Choice [C/T/N]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if choice in ("C", ""):
            return True
        if choice == "T":
            set_skip_today()
            return True
        if choice == "N":
            set_never_show()
            return True

        print(f"  Invalid choice '{choice}' — enter C, T, or N")


# ── GUI warning ─────────────────────────────────────────────────────────────

def show_gui_warning(parent) -> bool:
    """Show warning in a tkinter dialog.  Returns True to continue."""
    if not should_show_warning():
        return True

    import tkinter as tk
    from tkinter import ttk

    full_text = _get_warning_text()

    dialog = tk.Toplevel(parent)
    dialog.title("Security Notice")
    dialog.configure(bg="#000000")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    # Centre on parent (fall back to screen centre when parent is tiny/unmapped)
    dialog.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_x()
    py = parent.winfo_y()
    dw, dh = 620, 420
    if pw > 100 and ph > 100:
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
    else:
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        x = (sw - dw) // 2
        y = (sh - dh) // 2
    dialog.geometry(f"{dw}x{dh}+{x}+{y}")

    # Title bar
    title_lbl = tk.Label(
        dialog,
        text="SECURITY NOTICE — Computer Use Agent",
        font=("Consolas", 13, "bold"),
        fg="#ff4444",
        bg="#000000",
        pady=14,
    )
    title_lbl.pack()

    sep = tk.Frame(dialog, bg="#333333", height=1)
    sep.pack(fill=tk.X, padx=24)

    # ── Warning text ──────────────────────────────────────────────────
    text_frame = tk.Frame(dialog, bg="#000000")
    text_frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=(14, 6))

    text_widget = tk.Text(
        text_frame,
        bg="#000000",
        fg="#cccccc",
        font=("Consolas", 10),
        wrap=tk.WORD,
        relief=tk.FLAT,
        borderwidth=0,
        height=10,
    )
    text_widget.insert("1.0", full_text)
    text_widget.configure(state=tk.DISABLED)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    text_widget.configure(yscrollcommand=vsb.set)

    # ── Buttons ────────────────────────────────────────────────────────
    btn_frame = tk.Frame(dialog, bg="#000000", pady=18)
    btn_frame.pack(fill=tk.X, padx=28)

    result: dict[str, bool] = {"continue": False}

    def _on_continue() -> None:
        result["continue"] = True
        dialog.destroy()

    def _on_skip_today() -> None:
        set_skip_today()
        result["continue"] = True
        dialog.destroy()

    def _on_never() -> None:
        set_never_show()
        result["continue"] = True
        dialog.destroy()

    def _on_close() -> None:
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", _on_close)

    btn_base = {
        "font": ("Consolas", 10, "bold"),
        "relief": tk.FLAT,
        "borderwidth": 0,
        "padx": 18,
        "pady": 7,
    }

    continue_btn = tk.Button(
        btn_frame,
        text="Continue",
        command=_on_continue,
        bg="#1a5c1a",
        fg="#ffffff",
        activebackground="#228b22",
        activeforeground="#ffffff",
        **btn_base,
    )
    continue_btn.pack(side=tk.LEFT, padx=(0, 10))

    skip_btn = tk.Button(
        btn_frame,
        text="Don't Show Today",
        command=_on_skip_today,
        bg="#2a2a2a",
        fg="#bbbbbb",
        activebackground="#3a3a3a",
        activeforeground="#ffffff",
        **btn_base,
    )
    skip_btn.pack(side=tk.LEFT, padx=4)

    never_btn = tk.Button(
        btn_frame,
        text="Never Show Again",
        command=_on_never,
        bg="#2a2a2a",
        fg="#888888",
        activebackground="#3a3a3a",
        activeforeground="#ffffff",
        **btn_base,
    )
    never_btn.pack(side=tk.RIGHT)

    # Bind Enter to Continue
    dialog.bind("<Return>", lambda _e: _on_continue())
    continue_btn.focus_set()

    parent.wait_window(dialog)
    return result["continue"]
