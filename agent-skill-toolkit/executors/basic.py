"""Basic function executor: counting, clipboard, wait, human interaction."""

import time
import tkinter as tk
from tkinter import messagebox, simpledialog

import pyperclip

import config


def execute(function_name: str, arguments: dict) -> str:
    handlers = {
        "BasicFunction_CountInGivenString": _count_in_string,
        "BasicFunction_CountNumbers": _count_numbers,
        "BasicFunction_WriteToClipboard": _write_clipboard,
        "BasicFunction_ReadFromClipboard": _read_clipboard,
        "BasicFunction_Wait": _wait,
        "BasicFunction_HumanOperation": _human_operation,
        "BasicFunction_HumanInput": _human_input,
    }
    handler = handlers.get(function_name)
    if handler is None:
        return f"Error: unknown basic function '{function_name}'"
    return handler(arguments)


# ── Counting ──────────────────────────────────────────────────────────

def _count_in_string(args: dict) -> str:
    full = args.get("full_string", "")
    target = args.get("target", "")
    ignore_case = args.get("ignore_case", False)
    if not full or not target:
        return "Error: full_string and target must not be empty"
    if ignore_case:
        count = full.lower().count(target.lower())
    else:
        count = full.count(target)
    return str(count)


def _count_numbers(args: dict) -> str:
    start = args.get("start", 0)
    end = args.get("end", 0)
    step = args.get("step", 1)
    separator = args.get("separator", ",")
    if step == 0:
        return "Error: step must not be zero"
    numbers = list(range(start, end + (1 if step > 0 else -1), step))
    return separator.join(str(n) for n in numbers)


# ── Clipboard ─────────────────────────────────────────────────────────

def _write_clipboard(args: dict) -> str:
    content = args.get("content", "")
    if not content:
        return "Error: content must not be empty"
    pyperclip.copy(content)
    return "True"


def _read_clipboard(_args: dict) -> str:
    text = pyperclip.paste()
    return text if text else ""


# ── Wait ──────────────────────────────────────────────────────────────

def _wait(args: dict) -> str:
    seconds = args.get("seconds", 1)
    seconds = max(1, min(6000, int(seconds)))
    time.sleep(seconds)
    return f"Waited {seconds} second(s)"


# ── Human interaction (tkinter popups) ─────────────────────────────────

def _human_operation(args: dict) -> str:
    """Show a message dialog asking the user to perform a manual action.

    The dialog has an OK button.  Execution blocks until the user clicks it.
    """
    msg = args.get("message", "")
    if not msg:
        return "Error: message must not be empty"
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showinfo("Manual Operation Required", msg, parent=root)
    root.destroy()
    return "User acknowledged the operation"


def _human_input(args: dict) -> str:
    """Show an input dialog asking the user to type a value.

    Returns the string the user entered, or an error if cancelled.
    """
    msg = args.get("message", "")
    if not msg:
        return "Error: message must not be empty"
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    result = simpledialog.askstring("Input Required", msg, parent=root)
    root.destroy()
    if result is None:
        return "Error: user cancelled the input"
    return result
