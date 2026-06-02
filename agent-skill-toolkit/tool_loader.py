"""Loads tool definitions from JSON files and manages the tool registry."""

import json
from typing import Any

import config

PROMPT_JSON_DIR = config.PROMPT_JSON_DIR


def _load_json(filename: str) -> dict[str, Any]:
    path = PROMPT_JSON_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_entry_point() -> dict[str, Any]:
    """Load the entry point definition (system_prompt + LoadSkillCategory tool)."""
    return _load_json("Entry_Point.json")


def load_category_tools(category: str) -> list[dict[str, Any]]:
    """Load the tools array for a given skill category."""
    category_map = {
        "keyboard": "Keyboard_Action.json",
        "mouse": "Mouse_Action.json",
        "shell": "Shell_Action.json",
        "screen_capture": "Screen_Capture.json",
        "vlm": "VLM_Action.json",
        "basic": "Basic_Function.json",
    }
    if category not in category_map:
        raise ValueError(
            f"Unknown category '{category}'. Valid: {list(category_map)}"
        )
    data = _load_json(category_map[category])
    return data["tools"]


def get_category_description(category: str) -> str:
    """Return a human-readable description of a category."""
    entry = load_entry_point()
    cats = entry.get("available_categories", {})
    if category in cats:
        return cats[category]["description"]
    return ""
