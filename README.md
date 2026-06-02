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

Apache License Version 2.0.

## Additional Documents

### Risk Warning & Disclaimer
Your data security and integrity are very important.

This Agent is a Computer Use Agent. The Computer Use Agent is an AI system capable of operating a graphical user interface (GUI) directly like a human. Through technical means (YOLO/OCR based on local localization and multi-modal image understanding capabilities based externally), it recognizes screen content, moves the cursor, clicks buttons, types text, and automates tasks across applications without relying on APIs or specific code interfaces. This AI system can fully operate the currently used computer system.

Due to the unpredictability of AI, we cannot guarantee that the AI's behavior is correct, complete, and safe.

Even with minimal, blacklist-based defensive security measures in place for this agent, this AI system is still very likely to cause severe damage to the system, especially when induced. Furthermore, AI providers will have the ability (and are very likely) to collect transmitted data, including personal privacy data.

The developer strongly recommends running this agent in a new virtual machine (specific configurations can be found below in "Best Practices"), rather than on a physical computer or a cloud server/computer containing important data.

You may wish to click here to view best practices.

Please note that inappropriate protective measures may lead to severe consequences, including but not limited to file loss, malware installation, and privacy leakage. The user shall bear any adverse consequences.

This program is open-source, free software provided "as is" under the MIT License without quality guarantees. The developers have disclosed all known issues as far as possible, but the disclosures here may be incomplete, and this code may contain other flaws. We encourage you to actively submit feedback to allow us to fix them.

The original version of this program does not submit any data to any third party (except designated AI providers). If you find a modified version that does so, stop immediately and do not use it; if possible, thoroughly scan your computer for malware and viruses and report the concern to the hosting provider.

Please note that using this Agent implies your acceptance of its potential risks. You are responsible for any damages caused by using it on unauthorized computers.


### Responsible Disclosure
Although this computer-use agent software is released as open source under the Apache License 2.0, it is not intended for academic use, despite being listed for the AQA External Project Qualification and a part of the high school AI Fair project. The developer firmly believes that academic honesty is a fundamental principle in everything they do, which is reflected in the following disclosure statement related to the software and its source code.

Technical Statement About Misuse
Like many open-source agents, this software can be used unethically. Unfortunately, there is no permanent solution to prevent this issue.

It is strongly advised that the use of the Computer Use agent will be detected by any specialized exam browser and exam environment, including BlueBook. Misuse or abuse may result in the invalidation of qualifications and a ban from any exam boards, including those for digital assessments conducted by Cambridge, AQA, Oxford, and the College Board.

Users are also discouraged from employing this software for unwanted automation, which includes but is not limited to ticket applications and video games. Such misuse could violate terms of service and fair use, leading to account suspension or other legal consequences. Please review your local laws for more details.

Credits: Software Packages Used
We would like to extend our sincere thanks to the developers and businesses behind the following software packages. Without their contributions, this software would not exist:

Python – https://python.org/, PyAutoGUI, Ultralytics (Ultralytics Inc.), YOLOv8 (You Only Look Once version 8), PaddlePaddle (Netcom Science Technology Co., Ltd.), Umi-OCR

LLM Model Provider
This software benefits from the cost-efficient DeepSeek V4 Pro model. Special thanks to:

Liang Wenfeng, High-Flyer

Model Training
The management and training of the YOLO model were conducted on the following platforms:

Credit to:

Roboflow, Google Colab Training Service, SCNet (Supercomputing Network)

### Responsible Disclosure of Language Model Use

This software has been rewritten and improved with the assistance of the DeepSeek model. The following modifications were made:

1. The function-calling implementation has been changed from plain text to JSON format. 
2. A warning message has been added, which will display before the application runs. 
3. The program has been rewritten to fix potential bugs and remove any previous data from development and testing.
4. The generation of Documents (README).
