"""Launcher for agent-skill-toolkit (directory name contains hyphens, so it
cannot be imported as a regular Python package).

Usage:
    python run.py              # interactive REPL
    python run.py "prompt..."  # single-shot
"""

import importlib.util
import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent / "agent-skill-toolkit"

# Load main.py as a module
main_path = TOOLKIT_DIR / "main.py"
spec = importlib.util.spec_from_file_location("agent_skill_toolkit_main", main_path)
main_mod = importlib.util.module_from_spec(spec)
sys.modules["agent_skill_toolkit_main"] = main_mod
spec.loader.exec_module(main_mod)

main_mod.main()
