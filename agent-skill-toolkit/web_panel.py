"""
Web Control Panel for Agent Skill Toolkit
==========================================
Flask-based web dashboard with dark theme.  Provides:
- Password-protected login
- Command input → LLM agent execution with SSE streaming
- Configuration management (LLM, YOLO, OCR) with token write-only masking
"""

from __future__ import annotations

import json
import os
import sys
import difflib
from pathlib import Path

import httpx
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

# Allow imports from the toolkit directory
_TOOLKIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLKIT_DIR not in sys.path:
    sys.path.insert(0, _TOOLKIT_DIR)

from openai import OpenAI

import config
import tool_loader
from executors.basic import execute as exec_basic
from executors.keyboard import execute as exec_keyboard
from executors.vlm import execute as exec_vlm
from executors.mouse import execute as exec_mouse
from executors.screen_capture import execute as exec_screen_capture
from executors.shell import execute as exec_shell

# ── Constants ──────────────────────────────────────────────────────────────

_OVERRIDE_FILE = Path(__file__).with_name("config_override.json")

# Config keys exposed to the web panel for reading (token is masked)
_READABLE_CONFIG_KEYS = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "REASONING_EFFORT",
    "YOLO_INFERENCE_MODE",
    "YOLO_MODEL_PATH",
    "YOLO_CLOUD_API_URL",
    "OCR_URL",
    "WEB_PANEL_DESKTOP_VIEW",
]

# Config keys that the web panel is allowed to write
_WRITABLE_CONFIG_KEYS = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "REASONING_EFFORT",
    "YOLO_INFERENCE_MODE",
    "YOLO_MODEL_PATH",
    "YOLO_CLOUD_API_URL",
    "YOLO_CLOUD_API_KEY",
    "OCR_URL",
]

# Keys considered "secret" — returned masked, only updated (not revealed)
_SECRET_KEYS = {"DEEPSEEK_API_KEY", "YOLO_CLOUD_API_KEY"}

# ── Flask app ──────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()


# ── Config helpers ─────────────────────────────────────────────────────────

def _load_overrides() -> dict:
    """Load the current config override values from the JSON file."""
    if _OVERRIDE_FILE.exists():
        try:
            return json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_overrides(data: dict) -> None:
    """Save config overrides to the JSON file."""
    # Merge with existing overrides to avoid clobbering
    current = _load_overrides()
    current.update(data)
    _OVERRIDE_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_effective_config() -> dict:
    """Build the effective config by merging defaults + overrides."""
    result = {}
    for key in _READABLE_CONFIG_KEYS:
        val = getattr(config, key, None)
        if val is not None:
            result[key] = val
    # Add masked token values
    for key in _SECRET_KEYS:
        val = getattr(config, key, "")
        if val:
            result[key] = _mask_token(val)
        else:
            result[key] = ""
    return result


def _mask_token(token: str) -> str:
    """Mask a token showing only first 4 and last 4 characters."""
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "*" * (len(token) - 8) + token[-4:]


# ── Tool dispatch ──────────────────────────────────────────────────────────

def _dispatch(function_name: str, arguments: dict) -> str:
    """Route a function call to the correct executor."""
    if function_name.startswith("KeyboardAction_"):
        return exec_keyboard(function_name, arguments)
    if function_name.startswith("MouseAction_"):
        return exec_mouse(function_name, arguments)
    if function_name.startswith("ShellAction_"):
        return exec_shell(function_name, arguments)
    if function_name.startswith("ScreenCaptureAction_"):
        return exec_screen_capture(function_name, arguments)
    if function_name.startswith("VLM_Action_"):
        return exec_vlm(function_name, arguments)
    if function_name.startswith("BasicFunction_"):
        return exec_basic(function_name, arguments)
    return f"Error: unrecognized function '{function_name}'"


# ── HTML Templates (inline) ────────────────────────────────────────────────

_LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Control Panel — Login</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: #000; color: #fff;
    font-family: "Consolas","SF Mono","Menlo",monospace;
    display: flex; align-items: center; justify-content: center;
    height: 100vh;
  }
  .login-box {
    background: #111; border: 1px solid #333;
    border-radius: 8px; padding: 40px; width: 380px;
  }
  h1 { font-size: 1.3rem; color: #00bfff; margin-bottom: 8px; text-align: center; }
  .sub { font-size: 0.8rem; color: #666; text-align: center; margin-bottom: 28px; }
  label { display: block; font-size: 0.82rem; color: #aaa; margin-bottom: 6px; }
  input {
    width: 100%; padding: 10px 12px; margin-bottom: 18px;
    background: #000; color: #fff; border: 1px solid #444;
    border-radius: 4px; font-family: inherit; font-size: 0.95rem;
    outline: none;
  }
  input:focus { border-color: #00bfff; }
  button {
    width: 100%; padding: 10px; border: none; border-radius: 4px;
    background: #00bfff; color: #000; font-weight: bold;
    font-family: inherit; font-size: 0.95rem; cursor: pointer;
  }
  button:hover { background: #00a0dd; }
  .error {
    color: #ff4444; font-size: 0.82rem; text-align: center;
    margin-bottom: 14px; min-height: 1.2em;
  }
</style>
</head>
<body>
<div class="login-box">
  <h1>Agent Control Panel</h1>
  <div class="sub">Enter password to continue</div>
  <form method="post" action="/login">
    <label for="pw">Password</label>
    <input id="pw" name="password" type="password" autofocus>
    <div class="error">{{ error or '' }}</div>
    <button type="submit">Sign In</button>
  </form>
</div>
</body>
</html>"""

_DASHBOARD_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Control Panel</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: #000; color: #ccc;
    font-family: "Consolas","SF Mono","Menlo",monospace;
    display: flex; height: 100vh; overflow: hidden;
  }

  /* ── Sidebar ───────────────────────────────────────────── */
  .sidebar {
    width: 200px; min-width: 200px; background: #0a0a0a;
    border-right: 1px solid #222; display: flex; flex-direction: column;
    padding: 16px 0;
  }
  .sidebar h2 {
    font-size: 0.95rem; color: #00bfff; padding: 0 16px 16px;
    border-bottom: 1px solid #222; margin-bottom: 8px;
  }
  .sidebar a {
    display: block; padding: 10px 16px; color: #aaa;
    text-decoration: none; font-size: 0.85rem;
    border-left: 2px solid transparent; transition: 0.15s;
  }
  .sidebar a:hover, .sidebar a.active {
    color: #fff; background: #111; border-left-color: #00bfff;
  }
  .sidebar .logout {
    margin-top: auto; border-top: 1px solid #222; padding-top: 12px;
  }
  .sidebar .logout a { color: #ff6666; }

  /* ── Main ──────────────────────────────────────────────── */
  .main {
    flex: 1; display: flex; flex-direction: column; overflow: hidden;
  }
  .topbar {
    padding: 12px 20px; border-bottom: 1px solid #222;
    font-size: 0.85rem; color: #666;
    display: flex; justify-content: space-between; align-items: center;
  }
  .content {
    flex: 1; overflow-y: auto; padding: 20px;
  }

  /* ── Sections ──────────────────────────────────────────── */
  .section { display: none; }
  .section.active { display: block; }

  h3 { color: #00bfff; font-size: 1rem; margin-bottom: 16px; }

  /* ── Command area ──────────────────────────────────────── */
  #cmd-input {
    width: 100%; padding: 12px; background: #111; color: #fff;
    border: 1px solid #333; border-radius: 4px;
    font-family: inherit; font-size: 0.9rem; resize: vertical;
    min-height: 60px; outline: none; margin-bottom: 10px;
  }
  #cmd-input:focus { border-color: #00bfff; }
  #cmd-send {
    padding: 8px 24px; background: #00bfff; color: #000;
    border: none; border-radius: 4px; font-weight: bold;
    font-family: inherit; cursor: pointer; font-size: 0.85rem;
  }
  #cmd-send:disabled { opacity: 0.5; cursor: not-allowed; }
  #cmd-stop {
    padding: 8px 24px; background: #ff4444; color: #fff;
    border: none; border-radius: 4px; font-weight: bold;
    font-family: inherit; cursor: pointer; font-size: 0.85rem;
    display: none;
  }
  #cmd-output {
    margin-top: 16px; background: #0a0a0a; border: 1px solid #222;
    border-radius: 4px; padding: 14px; min-height: 200px;
    max-height: 500px; overflow-y: auto; white-space: pre-wrap;
    font-size: 0.85rem; line-height: 1.5;
  }
  #cmd-output .thinking { color: #888; }
  #cmd-output .tool { color: #00bfff; }
  #cmd-output .error { color: #ff4444; }
  #desktop-container img {
    max-width: 100%; height: auto; display: block;
    border-radius: 2px;
  }

  /* ── Config forms ──────────────────────────────────────── */
  .form-group { margin-bottom: 16px; }
  .form-group label {
    display: block; font-size: 0.8rem; color: #888; margin-bottom: 5px;
  }
  .form-group input, .form-group select {
    width: 100%; max-width: 520px; padding: 8px 10px;
    background: #111; color: #fff; border: 1px solid #333;
    border-radius: 4px; font-family: inherit; font-size: 0.85rem;
    outline: none;
  }
  .form-group input:focus, .form-group select:focus {
    border-color: #00bfff;
  }
  .form-group .hint { font-size: 0.75rem; color: #555; margin-top: 3px; }
  .form-group input[readonly] { color: #666; }
  .save-btn {
    padding: 8px 24px; background: #00bfff; color: #000;
    border: none; border-radius: 4px; font-weight: bold;
    font-family: inherit; cursor: pointer; font-size: 0.85rem;
    margin-right: 8px;
  }
  .toast {
    position: fixed; top: 16px; right: 16px; padding: 10px 20px;
    border-radius: 4px; font-size: 0.85rem; z-index: 999;
    animation: fadeIn 0.2s;
  }
  .toast.ok { background: #1a3a1a; color: #6f6; border: 1px solid #2a5a2a; }
  .toast.err { background: #3a1a1a; color: #f66; border: 1px solid #5a2a2a; }
  @keyframes fadeIn { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
</style>
</head>
<body>

<!-- Sidebar -->
<div class="sidebar">
  <h2>Control Panel</h2>
  <a href="#" class="active" data-section="command">Command</a>
  <a href="#" data-section="desktop" id="nav-desktop" style="display:none">View Desktop</a>
  <a href="#" data-section="llm">LLM Config</a>
  <a href="#" data-section="yolo">YOLO Config</a>
  <a href="#" data-section="ocr">OCR Config</a>
  <div class="logout"><a href="/logout">Logout</a></div>
</div>

<!-- Main -->
<div class="main">
  <div class="topbar">
    <span>Agent Skill Toolkit &mdash; Web Panel</span>
    <span id="conn-status" style="color:#555;">● idle</span>
  </div>
  <div class="content">

    <!-- Command Section -->
    <div id="sec-command" class="section active">
      <h3>Send Command</h3>
      <textarea id="cmd-input" placeholder="Type a prompt for the agent..."></textarea>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
        <button id="cmd-send" onclick="sendCommand()">Send</button>
        <button id="cmd-stop" onclick="stopCommand()">Stop</button>
        <label id="cmd-screenshot-label" style="display:none;font-size:0.82rem;color:#888;cursor:pointer;">
          <input type="checkbox" id="cmd-include-screenshot"> Include screenshot with prompt
        </label>
      </div>
      <div id="cmd-output"></div>
    </div>

    <!-- Desktop View Section -->
    <div id="sec-desktop" class="section">
      <h3>View Desktop</h3>
      <div style="margin-bottom:10px;">
        <button id="desktop-refresh" class="save-btn" onclick="refreshDesktop()">Refresh</button>
        <label style="margin-left:12px;font-size:0.82rem;color:#888;cursor:pointer;">
          <input type="checkbox" id="desktop-auto-refresh" onchange="toggleAutoRefresh()"> Auto-refresh (3s)
        </label>
        <span id="desktop-status" style="margin-left:12px;font-size:0.8rem;color:#555;"></span>
      </div>
      <div id="desktop-container" style="background:#0a0a0a;border:1px solid #222;border-radius:4px;
           min-height:300px;display:flex;align-items:center;justify-content:center;overflow:auto;">
        <span style="color:#555;">Click Refresh to capture the screen</span>
      </div>
    </div>

    <!-- LLM Config Section -->
    <div id="sec-llm" class="section">
      <h3>LLM Configuration</h3>
      <div class="form-group">
        <label>Endpoint URL</label>
        <input id="cfg-DEEPSEEK_BASE_URL" placeholder="https://api.deepseek.com">
      </div>
      <div class="form-group">
        <label>Model</label>
        <input id="cfg-DEEPSEEK_MODEL" placeholder="deepseek-v4-pro">
      </div>
      <div class="form-group">
        <label>Reasoning Effort</label>
        <select id="cfg-REASONING_EFFORT">
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="max">max</option>
        </select>
      </div>
      <div class="form-group">
        <label>API Token</label>
        <input id="cfg-DEEPSEEK_API_KEY" type="password" autocomplete="new-password" placeholder="sk-...">
        <div class="hint">Token is write-only — current value is never displayed. Leave blank to keep unchanged.</div>
      </div>
      <button class="save-btn" onclick="saveConfig('llm')">Save LLM Config</button>
    </div>

    <!-- YOLO Config Section -->
    <div id="sec-yolo" class="section">
      <h3>YOLO Configuration</h3>
      <div class="form-group">
        <label>Inference Mode</label>
        <select id="cfg-YOLO_INFERENCE_MODE">
          <option value="local">local</option>
          <option value="cloud">cloud</option>
        </select>
      </div>
      <div class="form-group">
        <label>Model Path (local mode)</label>
        <input id="cfg-YOLO_MODEL_PATH" placeholder="path/to/yolo_model.pt">
      </div>
      <div class="form-group">
        <label>Cloud API URL</label>
        <input id="cfg-YOLO_CLOUD_API_URL" placeholder="https://...">
      </div>
      <div class="form-group">
        <label>Cloud API Key</label>
        <input id="cfg-YOLO_CLOUD_API_KEY" type="password" autocomplete="new-password" placeholder="auth-key-...">
        <div class="hint">Key is write-only — current value is never displayed. Leave blank to keep unchanged.</div>
      </div>
      <button class="save-btn" onclick="saveConfig('yolo')">Save YOLO Config</button>
    </div>

    <!-- OCR Config Section -->
    <div id="sec-ocr" class="section">
      <h3>OCR Configuration</h3>
      <div class="form-group">
        <label>OCR Endpoint URL</label>
        <input id="cfg-OCR_URL" placeholder="http://127.0.0.1:35001/api/ocr">
      </div>
      <button class="save-btn" onclick="saveConfig('ocr')">Save OCR Config</button>
    </div>

  </div>
</div>

<div id="toast-container"></div>

<script>
  // ── Navigation ────────────────────────────────────────────
  document.querySelectorAll('.sidebar a[data-section]').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.sidebar a[data-section]').forEach(l => l.classList.remove('active'));
      document.getElementById('sec-' + a.dataset.section).classList.add('active');
      a.classList.add('active');
      if (a.dataset.section !== 'command') loadConfig(a.dataset.section);
    });
  });

  // ── Toast ─────────────────────────────────────────────────
  function toast(msg, ok) {
    const el = document.createElement('div');
    el.className = 'toast ' + (ok ? 'ok' : 'err');
    el.textContent = msg;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  // ── Config loading ────────────────────────────────────────
  async function loadConfig(section) {
    try {
      const resp = await fetch('/api/config');
      const cfg = await resp.json();
      const mapping = {
        llm: ['DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','REASONING_EFFORT'],
        yolo: ['YOLO_INFERENCE_MODE','YOLO_MODEL_PATH','YOLO_CLOUD_API_URL'],
        ocr: ['OCR_URL'],
      };
      for (const key of (mapping[section] || [])) {
        const el = document.getElementById('cfg-' + key);
        if (el && cfg[key] !== undefined) el.value = cfg[key];
      }
      // Secret fields: show masked placeholder if a value exists
      if (section === 'llm' && cfg.DEEPSEEK_API_KEY) {
        const el = document.getElementById('cfg-DEEPSEEK_API_KEY');
        el.placeholder = cfg.DEEPSEEK_API_KEY + ' (masked — enter new value to overwrite)';
      }
      if (section === 'yolo' && cfg.YOLO_CLOUD_API_KEY) {
        const el = document.getElementById('cfg-YOLO_CLOUD_API_KEY');
        el.placeholder = cfg.YOLO_CLOUD_API_KEY + ' (masked — enter new value to overwrite)';
      }
    } catch(e) { /* ignore */ }
  }

  // ── Config saving ─────────────────────────────────────────
  async function saveConfig(section) {
    const keySets = {
      llm: ['DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','REASONING_EFFORT','DEEPSEEK_API_KEY'],
      yolo: ['YOLO_INFERENCE_MODE','YOLO_MODEL_PATH','YOLO_CLOUD_API_URL','YOLO_CLOUD_API_KEY'],
      ocr: ['OCR_URL'],
    };
    const payload = {};
    for (const key of (keySets[section] || [])) {
      const el = document.getElementById('cfg-' + key);
      if (el && el.value) payload[key] = el.value;
    }
    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        toast('Config saved. Restart the agent toolkit for changes to take effect.', true);
        // Clear secret fields after save
        for (const key of (keySets[section] || [])) {
          const el = document.getElementById('cfg-' + key);
          if (el && el.type === 'password') el.value = '';
        }
        loadConfig(section);
      } else {
        const data = await resp.json();
        toast('Save failed: ' + (data.error || 'unknown'), false);
      }
    } catch(e) {
      toast('Network error: ' + e.message, false);
    }
  }

  // ── Command execution ─────────────────────────────────────
  let _cmdAbort = false;
  let _cmdActive = false;

  async function sendCommand() {
    const input = document.getElementById('cmd-input');
    const output = document.getElementById('cmd-output');
    const prompt = input.value.trim();
    if (!prompt || _cmdActive) return;

    _cmdAbort = false;
    _cmdActive = true;
    output.innerHTML = '';
    input.value = '';
    document.getElementById('cmd-send').disabled = true;
    document.getElementById('cmd-stop').style.display = 'inline-block';
    document.getElementById('conn-status').innerHTML = '<span style="color:#00bfff;">● running</span>';

    // Capture desktop screenshot before sending (if enabled)
    const includeSS = document.getElementById('cmd-include-screenshot');
    if (includeSS && includeSS.checked) {
      try {
        const ssResp = await fetch('/api/desktop');
        if (ssResp.ok) {
          const ssData = await ssResp.json();
          output.innerHTML += '<div style="margin-bottom:8px;border:1px solid #333;border-radius:4px;display:inline-block;">'
            + '<img src="data:image/png;base64,' + ssData.image + '" style="max-width:400px;display:block;" alt="Desktop">'
            + '<div style="padding:2px 8px;font-size:0.75rem;color:#666;">Desktop — ' + ssData.width + 'x' + ssData.height + '</div></div>\n';
        }
      } catch(_) {}
    }

    try {
      const resp = await fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({prompt}),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const {done, value} = await reader.read();
        if (done || _cmdAbort) break;
        buf += decoder.decode(value, {stream: true});
        // Process SSE events
        const lines = buf.split('\n');
        buf = lines.pop(); // keep incomplete line
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'thinking') {
                output.innerHTML += '<span class="thinking">' + escHtml(evt.text) + '</span>';
              } else if (evt.type === 'content') {
                output.innerHTML += escHtml(evt.text);
              } else if (evt.type === 'step_begin') {
                output.innerHTML += '\n<hr style="border-color:#333;margin:12px 0 8px">\n';
                output.innerHTML += '<div style="color:#00bfff;font-weight:bold;">Step ' + evt.step + '</div>\n';
              } else if (evt.type === 'step_summary') {
                output.innerHTML += '<div style="color:#fff;margin:8px 0;padding:6px 10px;background:#1a2a1a;border-left:3px solid #0f0;border-radius:2px;">' + escHtml(evt.content) + '</div>\n';
              } else if (evt.type === 'tool_begin') {
                output.innerHTML += '<span class="tool">[tool] ' + escHtml(evt.name) + '</span>\n';
              } else if (evt.type === 'tool_result') {
                const cls = evt.is_error ? 'error' : 'tool';
                output.innerHTML += '<span class="' + cls + '">  ' + escHtml(evt.status) + ' (' + evt.length + ' chars)</span>\n';
              } else if (evt.type === 'done') {
                output.innerHTML += '\n';
              } else if (evt.type === 'error') {
                output.innerHTML += '<span class="error">' + escHtml(evt.text) + '</span>\n';
              }
            } catch(_) {}
          }
        }
        output.scrollTop = output.scrollHeight;
      }
    } catch(e) {
      output.innerHTML += '<span class="error">Connection error: ' + escHtml(e.message) + '</span>';
    }

    _cmdActive = false;
    document.getElementById('cmd-send').disabled = false;
    document.getElementById('cmd-stop').style.display = 'none';
    document.getElementById('conn-status').innerHTML = '<span style="color:#555;">● idle</span>';
  }

  function stopCommand() {
    _cmdAbort = true;
    document.getElementById('conn-status').innerHTML = '<span style="color:#ff6666;">● stopping</span>';
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Enter to send (Ctrl+Enter for newline)
  document.getElementById('cmd-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
      e.preventDefault();
      sendCommand();
    }
  });

  // Load configs on first nav click
  document.querySelectorAll('.sidebar a[data-section]').forEach(a => {
    a.addEventListener('click', () => {
      if (a.dataset.section !== 'command') loadConfig(a.dataset.section);
    }, {once: false});
  });

  // ── Desktop view ──────────────────────────────────────────
  let _desktopAutoTimer = null;

  async function initDesktopFeature() {
    try {
      const resp = await fetch('/api/config');
      const cfg = await resp.json();
      if (cfg.WEB_PANEL_DESKTOP_VIEW) {
        document.getElementById('nav-desktop').style.display = '';
        document.getElementById('cmd-screenshot-label').style.display = '';
      }
    } catch(e) {}
  }
  initDesktopFeature();

  async function refreshDesktop() {
    const container = document.getElementById('desktop-container');
    const status = document.getElementById('desktop-status');
    status.textContent = 'capturing...';
    try {
      const resp = await fetch('/api/desktop');
      if (!resp.ok) {
        const data = await resp.json();
        container.innerHTML = '<span style="color:#ff4444;">' + escHtml(data.error || 'Failed') + '</span>';
        status.textContent = '';
        return;
      }
      const data = await resp.json();
      const ts = new Date().toLocaleTimeString();
      container.innerHTML = '<img src="data:image/png;base64,' + data.image + '" alt="Desktop screenshot">';
      status.textContent = data.width + 'x' + data.height + ' @ ' + ts;
    } catch(e) {
      container.innerHTML = '<span style="color:#ff4444;">' + escHtml(e.message) + '</span>';
      status.textContent = '';
    }
  }

  function toggleAutoRefresh() {
    const checked = document.getElementById('desktop-auto-refresh').checked;
    if (checked) {
      refreshDesktop();
      _desktopAutoTimer = setInterval(refreshDesktop, 3000);
    } else {
      clearInterval(_desktopAutoTimer);
      _desktopAutoTimer = null;
    }
  }

  // Cleanup auto-refresh on page unload
  window.addEventListener('beforeunload', () => {
    if (_desktopAutoTimer) clearInterval(_desktopAutoTimer);
  });
</script>
</body>
</html>"""


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Redirect to dashboard if authenticated, else to login."""
    if session.get("authenticated"):
        return render_template_string(_DASHBOARD_PAGE)
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    """Show login form (GET) or process login (POST)."""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == config.WEB_PANEL_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        return render_template_string(_LOGIN_PAGE, error="Incorrect password")
    return render_template_string(_LOGIN_PAGE, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── API: Config ────────────────────────────────────────────────────────────


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Return current effective config with secret keys masked."""
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(_get_effective_config())


@app.route("/api/config", methods=["POST"])
def api_update_config():
    """Update one or more config values. Secret keys are always overwritten
    when provided; other keys replace the current override value."""
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    updates = {}
    for key, value in data.items():
        if key in _WRITABLE_CONFIG_KEYS and value:
            updates[key] = value

    if not updates:
        return jsonify({"error": "No valid config keys provided"}), 400

    _save_overrides(updates)

    # Reload config module so changes take effect for subsequent requests
    import importlib
    importlib.reload(config)

    return jsonify({"ok": True, "updated": list(updates.keys())})


# ── API: Command (SSE streaming) ───────────────────────────────────────────

# Internal safety limit: max tool-call rounds within a single step.
_MAX_INTERNAL_ROUNDS = 50

# Signal that the overall task is complete.
_TASK_COMPLETE_MARKER = "TASK_COMPLETE"

# Prompt injected after each step to trigger the next one.
_CONTINUE_PROMPT = (
    "Continue with the next logical operation for the original task. "
    "If all steps are complete, reply with 'TASK_COMPLETE' "
    "followed by a summary of what was accomplished."
)


def _strip_to_step_summaries_web(
    messages: list[dict],
    original_request: str,
) -> list[dict]:
    """Strip all intermediate messages, keeping only step summaries."""
    clean: list[dict] = [messages[0]]  # system prompt
    clean.append({"role": "user", "content": original_request})
    for msg in messages[2:]:
        if msg["role"] == "assistant" and msg.get("content") and not msg.get("tool_calls"):
            clean.append(dict(msg))
    return clean


@app.route("/api/command", methods=["POST"])
def api_command():
    """Execute a prompt via the agent using step-by-step execution.

    Each step completes one logical operation.  Intermediate messages
    (thinking, tool calls, tool results) are stripped between steps so
    the next step only sees the original task + past step summaries.
    Streams results as SSE events.
    """
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    def generate():
        """SSE generator that runs the step-by-step agent loop."""
        nonlocal prompt
        try:
            client = OpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
                timeout=httpx.Timeout(connect=10.0, read=12.0, write=10.0, pool=10.0),
            )

            entry = tool_loader.load_entry_point()
            system_prompt = entry["system_prompt"]
            # Start with meta-tools + basic utilities
            default_tools: list[dict] = list(entry["tools"])
            try:
                default_tools.extend(tool_loader.load_category_tools("basic"))
            except Exception:
                pass

            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            original_request = prompt

            # ── Outer step loop ──────────────────────────────────────
            previous_summaries: list[str] = []

            for step_num in range(1, config.MAX_STEPS + 1):
                # Per-step fresh state (tools reset each step)
                active_tools: list[dict] = list(default_tools)
                loaded_categories: set[str] = set()
                work_done = False

                yield _sse({"type": "step_begin", "step": step_num})

                # ── Inner tool-call loop (one step) ──────────────────
                internal_round = 0
                step_succeeded = False
                empty_retries = 0

                while internal_round < _MAX_INTERNAL_ROUNDS:
                    internal_round += 1

                    # ── Stream one LLM call ──────────────────────────
                    try:
                        resp = client.chat.completions.create(
                            model=config.DEEPSEEK_MODEL,
                            messages=messages,
                            tools=active_tools,
                            stream=True,
                            reasoning_effort=config.REASONING_EFFORT,
                            extra_body={"thinking": {"type": "enabled"}},
                        )
                    except (httpx.ReadTimeout, httpx.ReadError):
                        yield _sse({
                            "type": "error",
                            "text": "LLM request timed out — the API connection may be stuck.",
                        })
                        return

                    content_parts: list[str] = []
                    reasoning_parts: list[str] = []
                    tool_call_chunks: dict[int, dict] = {}

                    try:
                        for chunk in resp:
                            delta = chunk.choices[0].delta

                            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                                reasoning_parts.append(delta.reasoning_content)
                                yield _sse({"type": "thinking", "text": delta.reasoning_content})

                            if delta.tool_calls:
                                for tc_delta in delta.tool_calls:
                                    idx = tc_delta.index
                                    if idx not in tool_call_chunks:
                                        tool_call_chunks[idx] = {
                                            "id": tc_delta.id or "",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    entry = tool_call_chunks[idx]
                                    if tc_delta.id:
                                        entry["id"] = tc_delta.id
                                    if tc_delta.function:
                                        if tc_delta.function.name:
                                            entry["function"]["name"] += tc_delta.function.name
                                        if tc_delta.function.arguments:
                                            entry["function"]["arguments"] += tc_delta.function.arguments

                            if delta.content:
                                content_parts.append(delta.content)
                                yield _sse({"type": "content", "text": delta.content})
                    except (httpx.ReadTimeout, httpx.ReadError):
                        yield _sse({
                            "type": "error",
                            "text": "Stream read timed out — the LLM response may be stuck.",
                        })
                        return

                    # Reconstruct tool_calls
                    tool_calls: list[dict] = []
                    for idx in sorted(tool_call_chunks.keys()):
                        tc = tool_call_chunks[idx]
                        tool_calls.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        })

                    # ── Process tool calls ────────────────────────────
                    if tool_calls:
                        reasoning = "".join(reasoning_parts)
                        assistant_msg: dict = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": tool_calls,
                        }
                        if reasoning:
                            assistant_msg["reasoning_content"] = reasoning
                        messages.append(assistant_msg)

                        for tc in tool_calls:
                            fn_name = tc["function"]["name"]
                            try:
                                fn_args = json.loads(tc["function"]["arguments"])
                            except json.JSONDecodeError:
                                fn_args = {}

                            yield _sse({"type": "tool_begin", "name": fn_name})

                            if fn_name == "LoadSkillCategory":
                                category = fn_args.get("category", "")
                                try:
                                    tools = tool_loader.load_category_tools(category)
                                except ValueError as e:
                                    result = str(e)
                                else:
                                    if category not in loaded_categories:
                                        loaded_categories.add(category)
                                        active_tools.extend(tools)
                                    tool_names = [t["function"]["name"] for t in tools]
                                    result = f"Category '{category}' loaded. Available: {', '.join(tool_names)}"
                            else:
                                result = _dispatch(fn_name, fn_args)
                                work_done = True

                            is_error = result.startswith("Error:") or result.startswith("SAFETY BLOCK")
                            yield _sse({
                                "type": "tool_result",
                                "is_error": is_error,
                                "status": "✗ Error" if is_error else "✓ OK",
                                "length": len(result),
                            })

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result,
                            })

                        # When content arrived together with tool_calls,
                        # the model intended to stop — but only treat it as
                        # a step summary when domain tools were actually called.
                        content = "".join(content_parts)
                        if content:
                            if work_done:
                                messages.append({"role": "assistant", "content": content})
                                step_succeeded = True
                                yield _sse({"type": "step_summary", "step": step_num, "content": content})
                                if content.strip().startswith(_TASK_COMPLETE_MARKER):
                                    yield _sse({"type": "done"})
                                    return
                                break  # step done
                            else:
                                # Only meta-tools called — append as context
                                # and let the next round call domain tools.
                                messages.append({"role": "assistant", "content": content})

                        continue  # next internal round

                    # ── Final content (no tool calls) ─────────────────
                    content = "".join(content_parts)
                    if content:
                        messages.append({"role": "assistant", "content": content})
                        step_succeeded = True
                        yield _sse({"type": "step_summary", "step": step_num, "content": content})

                        # Check for task completion
                        if content.strip().startswith(_TASK_COMPLETE_MARKER):
                            yield _sse({"type": "done"})
                            return
                        break  # step done, continue to next step

                    # Empty response — retry once, then abort to avoid infinite loop
                    empty_retries += 1
                    if empty_retries > 1:
                        yield _sse({
                            "type": "error",
                            "text": f"Step {step_num} failed after {empty_retries} empty responses — aborting.",
                        })
                        return
                    messages.append({
                        "role": "user",
                        "content": "There was an error that caused the execution to be interrupted. Please continue with your previous task.",
                    })

                if not step_succeeded:
                    yield _sse({"type": "error", "text": f"Step {step_num} failed — no content produced."})
                    return

                # ── Stuck detection: near-duplicate consecutive step summaries ─
                # *content* was assigned from the step summary above; reference it.
                summary_stripped = content.strip()
                previous_summaries.append(summary_stripped)
                if len(previous_summaries) >= 3:
                    s0, s1, s2 = previous_summaries[-3:]
                    r01 = difflib.SequenceMatcher(None, s0, s1).ratio()
                    r12 = difflib.SequenceMatcher(None, s1, s2).ratio()
                    r02 = difflib.SequenceMatcher(None, s0, s2).ratio()
                    if r01 > 0.8 and r12 > 0.8 and r02 > 0.8:
                        yield _sse({
                            "type": "error",
                            "text": f"Near-duplicate step summaries detected (sim {r01:.2f}/{r12:.2f}/{r02:.2f}) — agent is stuck. Aborting.",
                        })
                        return

                # ── Strip to step summaries for next step ─────────────
                clean = _strip_to_step_summaries_web(messages, original_request)
                messages.clear()
                messages.extend(clean)

                # ── Inject continuation prompt ────────────────────────
                messages.append({"role": "user", "content": _CONTINUE_PROMPT})

            else:
                yield _sse({"type": "error", "text": f"Stopped after {config.MAX_STEPS} steps."})

        except Exception as e:
            yield _sse({"type": "error", "text": str(e)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── API: Desktop screenshot ────────────────────────────────────────────────


@app.route("/api/desktop", methods=["GET"])
def api_desktop():
    """Capture the current screen and return it as a base64-encoded PNG."""
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    if not config.WEB_PANEL_DESKTOP_VIEW:
        return jsonify({"error": "Desktop view is disabled in config"}), 403

    try:
        import base64 as _b64
        import io as _io
        import pyautogui

        screenshot = pyautogui.screenshot()
        buf = _io.BytesIO()
        screenshot.save(buf, format="PNG")
        img_b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        width, height = screenshot.size
        return jsonify({
            "image": img_b64,
            "width": width,
            "height": height,
            "format": "png",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Entry point ────────────────────────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    """Start the Flask development server."""
    print(f"  Server starting on {host}:{port} ...")
    print(f"  Press Ctrl+C to stop\n")
    # threaded=True is the default in newer Flask/Werkzeug; set explicitly
    # for clarity.  use_reloader is off since we're not in debug mode.
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
