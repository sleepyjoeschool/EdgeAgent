"""Launcher for the GUI version of the Agent Skill Toolkit.

Usage:
    python run_gui.py
"""

import importlib.util
import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent / "agent-skill-toolkit"

# Load gui.py as a module
gui_path = TOOLKIT_DIR / "gui.py"
spec = importlib.util.spec_from_file_location("agent_skill_toolkit_gui", gui_path)
gui_mod = importlib.util.module_from_spec(spec)
sys.modules["agent_skill_toolkit_gui"] = gui_mod
spec.loader.exec_module(gui_mod)

gui_mod.main()
