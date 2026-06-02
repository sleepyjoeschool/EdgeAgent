# Agent Skill Toolkit

A desktop automation agent powered by the DeepSeek LLM. It provides keyboard/mouse control, shell command execution, screen capture with OCR, YOLO object detection, and VLM (vision-language model) screen analysis — all through natural language prompts.

## Directory Structure

```
publish_clean/
├── run.py                         # CLI launcher (interactive REPL or single-shot)
├── run_gui.py                     # GUI launcher (dark-themed Tkinter interface)
├── run_web.py                     # Web control panel launcher (Flask SSE streaming)
├── run_config.py                  # Standalone configuration editor
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── prompt-content-json/           # LLM tool definitions (system prompts + function schemas)
│   ├── Entry_Point.json
│   ├── Keyboard_Action.json
│   ├── Mouse_Action.json
│   ├── Shell_Action.json
│   ├── Screen_Capture.json
│   ├── VLM_Action.json
│   └── Basic_Function.json
├── examples/                      # Example scripts
│   ├── deepseek-calling.py        # Minimal DeepSeek API streaming example
│   └── umni_ocr.py                # UMNI OCR API usage example
└── agent-skill-toolkit/           # Core package
    ├── config.py                  # Configuration (API keys, model settings)
    ├── config_editor.py           # GUI config editor
    ├── main.py                    # CLI agent loop
    ├── gui.py                     # Tkinter GUI agent
    ├── web_panel.py               # Flask web control panel
    ├── tool_loader.py             # Tool definition loader
    ├── security_check.py          # LLM-based shell command security audit
    ├── warning_notice.py          # Startup security warning
    ├── requirements.txt           # Sub-package dependencies
    └── executors/                 # Skill executors
        ├── keyboard.py            # Keyboard automation (pyautogui)
        ├── mouse.py               # Mouse automation (pyautogui)
        ├── shell.py               # Shell command execution (subprocess)
        ├── screen_capture.py      # Screen capture + OCR + YOLO detection
        ├── vlm.py                 # Qwen-VL multimodal vision analysis
        └── basic.py               # Clipboard, wait, human interaction
```

## Prerequisites

- **Python 3.10+**
- **Windows** (primary platform; keyboard/mouse automation via `pyautogui`)

Optional services (for full functionality):
- **UMNI OCR** — local OCR service on `http://127.0.0.1:35001/api/ocr`
- **YOLO Cloud API** — remote object detection endpoint
- **Qwen-VL server** — multimodal vision-language reasoning
- **YOLO v8 model file** (`.pt` or `.onnx`) — for local object detection

## Installation

### 1. Clone / copy this directory

```powershell
cd publish_clean
```

### 2. Create a virtual environment (recommended)

```powershell
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Set environment variables

All secrets and API keys are configured via environment variables. Set the ones you need before launching:

```powershell
# Required — DeepSeek API key
$env:SKILL_DEEPSEEK_API_KEY = "sk-your-api-key-here"

# Optional — override defaults
$env:SKILL_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:SKILL_DEEPSEEK_MODEL = "deepseek-v4-pro"
$env:SKILL_REASONING_EFFORT = "high"

# Optional — YOLO cloud detection
$env:SKILL_YOLO_CLOUD_URL = "https://your-yolo-api/predict"
$env:SKILL_YOLO_CLOUD_API_KEY = "your-yolo-key"

# Optional — YOLO local model path
$env:SKILL_YOLO_MODEL = "C:\path\to\yolo_model.pt"

# Optional — VLM service
$env:SKILL_VLM_API_URL = "https://your-vlm-server/inference"
$env:SKILL_VLM_AUTH_KEY = "your-vlm-key"

# Optional — UMNI OCR endpoint
$env:SKILL_OCR_URL = "http://127.0.0.1:35001/api/ocr"

# Optional — Web control panel password
$env:SKILL_WEB_PANEL_PASSWORD = "your-password"
```

> **Note:** To persist environment variables across sessions, use `setx`:
> ```powershell
> setx SKILL_DEEPSEEK_API_KEY "sk-your-api-key-here"
> ```

Alternatively, you can use the **Configuration Editor** GUI (`run_config.py`) to modify settings — changes are saved to `config_override.json` and take effect on the next launch.

## Usage

### CLI Mode (interactive REPL)

```powershell
python run.py
```

Type prompts interactively. Commands:
- `/help` — show help
- `/tools` — list loaded tools
- `/results` — list skill execution results
- `/reset` — clear conversation
- `/quit` — exit

Or single-shot:

```powershell
python run.py "Open Notepad and type Hello World"
```

### GUI Mode (dark-themed desktop window)

```powershell
python run_gui.py
```

Features:
- Dark theme (#000000 background)
- Streaming output: thinking (gray), content (white), tools (cyan)
- Slash-command menu with auto-complete
- Always-on-top toggle
- Built-in configuration editor

### Web Control Panel

```powershell
python run_web.py
```

Opens a Flask web server with:
- Password-protected login
- SSE streaming command execution
- Real-time desktop viewing (configurable)
- Web-based configuration editor (LLM, YOLO, OCR)

### Configuration Editor (standalone)

```powershell
python run_config.py
```

Dark-themed GUI for editing all configuration values. Supports:
- String, password, boolean, dropdown, integer, and file-path fields
- Show/hide sensitive values
- Environment variable read-only indicators
- Reset to defaults

## Skill Categories

The agent loads skill categories on demand. Each category provides a set of functions:

| Category | Functions | Description |
|---|---|---|
| `keyboard` | InstantInput, KeyByKeyInput, HotkeyInput | Keyboard typing and hotkey simulation |
| `mouse` | GetPosition, InstantMove, MovementWithDelay, Clicks | Mouse positioning and clicking |
| `shell` | RunShell, RunShellAsync | Synchronous and async command execution |
| `screen_capture` | CaptureScreen, DetectObjects | OCR text extraction + YOLO object detection |
| `vlm` | AnalyzeScreen, AnalyzeImage | Vision-language model screen analysis |
| `basic` | Count, Clipboard, Wait, HumanOperation | Always-loaded utilities |

## Security

Shell command execution goes through a two-layer security review:
1. **Static pattern checks** — blocks known-dangerous patterns (curl-to-bash, registry edits, disk formatting)
2. **LLM-based audit** — each command is sent to a fresh DeepSeek instance for harm analysis

Commands flagged as dangerous trigger a native OS confirmation dialog before execution.

## License

See the project's license file for terms.
