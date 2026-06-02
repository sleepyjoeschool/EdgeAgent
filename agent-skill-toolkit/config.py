"""Configuration for the Agent Skill Toolkit.

All secrets and API keys are read from environment variables.
Copy the example config or set the variables before launching.
"""

import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PROMPT_JSON_DIR = ROOT_DIR / "prompt-content-json"

# ── DeepSeek API ────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get(
    "SKILL_DEEPSEEK_API_KEY",
    "",
)
DEEPSEEK_BASE_URL = os.environ.get(
    "SKILL_DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
)
DEEPSEEK_MODEL = os.environ.get(
    "SKILL_DEEPSEEK_MODEL",
    "deepseek-v4-pro",
)

# Reasoning effort for DeepSeek thinking mode: "low", "medium", "high", or "max"
# Only applies when thinking is enabled in the API call.
REASONING_EFFORT = os.environ.get(
    "SKILL_REASONING_EFFORT",
    "high",
)

# ── YOLO v8 model ──────────────────────────────────────────────────────
# Inference mode: "local" (use local .pt file) or "cloud" (use remote API).
YOLO_INFERENCE_MODE = os.environ.get(
    "SKILL_YOLO_INFERENCE_MODE",
    "cloud",
)

# Path to the YOLO v8 .pt / .onnx weights file (local mode).
YOLO_MODEL_PATH = os.environ.get(
    "SKILL_YOLO_MODEL",
    str(ROOT_DIR / "agent-skill-toolkit" / "models" / "yolo_placeholder.pt"),
)

# ── Cloud YOLO API (used when YOLO_INFERENCE_MODE == "cloud") ─────────
YOLO_CLOUD_API_URL = os.environ.get(
    "SKILL_YOLO_CLOUD_URL",
    "",
)
YOLO_CLOUD_API_KEY = os.environ.get(
    "SKILL_YOLO_CLOUD_API_KEY",
    "",
)

# ── Qwen-VL 多模态推理服务 ─────────────────────────────────────────
VLM_API_URL = os.environ.get(
    "SKILL_VLM_API_URL",
    "",
)
VLM_AUTH_KEY = os.environ.get(
    "SKILL_VLM_AUTH_KEY",
    "",
)

# SSL certificate verification for VLM connections.
# Set to False to disable (insecure — dev use only).
VLM_SSL_VERIFY = True

# Custom CA certificate in PEM format for pinning the VLM server cert.
# Leave empty to use the system trust store.
VLM_PINNED_CERT_PEM = ""

# ── UMNI OCR ───────────────────────────────────────────────────────────
OCR_URL = os.environ.get(
    "SKILL_OCR_URL",
    "http://127.0.0.1:35001/api/ocr",
)

# Safety limits
# Maximum total steps (cycles) per task. Each step completes one operation.
# The agent auto-continues until TASK_COMPLETE or this limit is reached.
MAX_STEPS = 50

# ── Web control panel ───────────────────────────────────────────────────
WEB_PANEL_PASSWORD = os.environ.get(
    "SKILL_WEB_PANEL_PASSWORD",
    "",
)

# Set to True to enable remote desktop viewing in the web control panel.
# When enabled, the sidebar shows a "View Desktop" tab and the Command
# section offers an "include screenshot" option.
WEB_PANEL_DESKTOP_VIEW = True

# ── Config overrides (loaded from config_override.json if present) ──────
_OVERRIDE_FILE = Path(__file__).with_name("config_override.json")
if _OVERRIDE_FILE.exists():
    try:
        _overrides = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        for _key, _value in _overrides.items():
            if _key in globals() and not _key.startswith("_"):
                globals()[_key] = _value
    except (json.JSONDecodeError, OSError):
        pass
