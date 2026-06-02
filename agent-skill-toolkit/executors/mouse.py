"""Mouse action executor using pyautogui."""

import pyautogui

pyautogui.FAILSAFE = True


def execute(function_name: str, arguments: dict) -> str:
    handlers = {
        "MouseAction_GetPosition": _get_position,
        "MouseAction_InstantMove": _instant_move,
        "MouseAction_MovementWithDelay": _movement_with_delay,
        "MouseAction_LeftClick": _left_click,
        "MouseAction_RightClick": _right_click,
        "MouseAction_LeftDoubleClick": _left_double_click,
    }
    handler = handlers.get(function_name)
    if handler is None:
        return f"Error: unknown mouse function '{function_name}'"
    return handler(arguments)


def _get_position(_args: dict) -> str:
    x, y = pyautogui.position()
    return f"X:{x}-Y:{y}"


def _instant_move(args: dict) -> str:
    x = args.get("XCoordinate", 0)
    y = args.get("YCoordinate", 0)
    if x < 0 or y < 0:
        return "Error: coordinates must be >= 0"
    pyautogui.moveTo(x, y)
    return "True"


def _movement_with_delay(args: dict) -> str:
    x = args.get("XCoordinate", 0)
    y = args.get("YCoordinate", 0)
    duration = args.get("Duration", 1.0)
    if x < 0 or y < 0:
        return "Error: coordinates must be >= 0"
    if duration <= 0:
        return "Error: Duration must be > 0"
    pyautogui.moveTo(x, y, duration=duration)
    return "True"


def _left_click(_args: dict) -> str:
    pyautogui.click(button="left")
    return "True"


def _right_click(_args: dict) -> str:
    pyautogui.click(button="right")
    return "True"


def _left_double_click(_args: dict) -> str:
    pyautogui.doubleClick(button="left")
    return "True"
