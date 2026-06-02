"""Keyboard action executor using pyautogui."""

import pyautogui

# Safety: add a small pause between pyautogui actions
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def execute(function_name: str, arguments: dict) -> str:
    handlers = {
        "KeyboardAction_InstantInput": _instant_input,
        "KeyboardAction_KeyByKeyInput": _key_by_key_input,
        "KeyboardAction_HotkeyInput": _hotkey_input,
    }
    handler = handlers.get(function_name)
    if handler is None:
        return f"Error: unknown keyboard function '{function_name}'"
    return handler(arguments)


def _instant_input(args: dict) -> str:
    text = args.get("InputContent", "")
    if len(text) < 2:
        return "Error: InputContent length must be greater than 1"
    pyautogui.write(text, interval=0)
    return f"True: instant input '{text}' completed"


def _key_by_key_input(args: dict) -> str:
    text = args.get("InputContent", "")
    if len(text) < 2:
        return "Error: InputContent length must be greater than 1"
    pyautogui.write(text, interval=0.08)
    return f"True: key-by-key input '{text}' completed"


def _hotkey_input(args: dict) -> str:
    keys = args.get("keys", [])
    if not keys:
        return "Error: keys array must not be empty"

    # Map our key identifiers to pyautogui key names
    key_map = {
        "TILDE": "`", "Esc": "escape", "Space": "space",
        "PrtScn": "printscreen", "ScrollLock": "scrolllock", "Pause": "pause",
        "UpArrow": "up", "DownArrow": "down", "LeftArrow": "left", "RightArrow": "right",
        "CapsLock": "capslock", "PageUp": "pageup", "PageDown": "pagedown",
        "NumMultiply": "nummultiply", "NumAdd": "numadd", "NumSubtract": "numsubtract",
        "NumDecimal": "numdecimal", "NumDivide": "numdivide", "NumEnter": "numenter",
        "Num0": "num0", "Num1": "num1", "Num2": "num2", "Num3": "num3", "Num4": "num4",
        "Num5": "num5", "Num6": "num6", "Num7": "num7", "Num8": "num8", "Num9": "num9",
    }

    pyautogui_keys = []
    for k in keys:
        mapped = key_map.get(k, k.lower())
        pyautogui_keys.append(mapped)

    pyautogui.hotkey(*pyautogui_keys)
    return f"True: hotkey '{'+'.join(keys)}' pressed"
