"""
Configuration Editor Launcher
=============================
Standalone GUI for editing the Agent Skill Toolkit configuration.

Usage:
    python run_config.py

This opens the config editor as an independent window — the main
Desktop Agent does not need to be running.
"""

import importlib.util
import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent / "agent-skill-toolkit"

# Load config_editor.py as a module
editor_path = TOOLKIT_DIR / "config_editor.py"
spec = importlib.util.spec_from_file_location("config_editor", editor_path)
editor_mod = importlib.util.module_from_spec(spec)
sys.modules["config_editor"] = editor_mod
spec.loader.exec_module(editor_mod)

editor_mod.main()
