"""VLM executor — calls the Qwen-VL multimodal reasoning service over HTTPS with certificate pinning."""

import base64
import io
import tempfile
from typing import Optional

import config
import pyautogui
import requests


_VLM_SESSION: Optional[requests.Session] = None
_LAST_CERT_HASH: Optional[int] = None


def _get_vlm_session() -> requests.Session:
    """Build or reuse an HTTPS session with certificate pinning applied.

    Returns a `requests.Session` whose `verify` parameter is set to either:
    - **a temp file** containing the pinned CA certificate (PEM), so non-
      public CAs (self-signed / enterprise PKI) are trusted *only* for that
      session; or
    - **True** (default system trust store) when no pinned cert is configured
      but SSL verification is enabled; or
    - **False** when SSL verification is explicitly disabled (insecure — dev
      use only).
    """
    global _VLM_SESSION, _LAST_CERT_HASH

    cert_pem = config.VLM_PINNED_CERT_PEM
    cert_hash = hash(cert_pem) if cert_pem else None

    if _VLM_SESSION is not None and cert_hash == _LAST_CERT_HASH:
        return _VLM_SESSION

    session = requests.Session()
    session.trust_env = False

    if not config.VLM_SSL_VERIFY:
        session.verify = False
    elif cert_pem and cert_pem.strip():
        # Write the pinned cert to a temp file so requests can use it.
        # The file is kept for the lifetime of the session (the process).
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False, encoding="utf-8"
        )
        tmp.write(cert_pem.strip())
        tmp.close()
        session.verify = tmp.name
    else:
        session.verify = True

    _VLM_SESSION = session
    _LAST_CERT_HASH = cert_hash
    return session


def execute(function_name: str, arguments: dict) -> str:
    if function_name == "VLM_Action_AnalyzeScreen":
        prompt = arguments.get("PromptString", "")
        return _analyze_screen(prompt)
    if function_name == "VLM_Action_AnalyzeImage":
        img_b64 = arguments.get("ImgBase64", "")
        prompt = arguments.get("PromptString", "")
        return _analyze_image(img_b64, prompt)
    return f"Error: unknown VLM function '{function_name}'"


def _call_vlm(img_b64: str, prompt: str) -> str:
    """Send image + prompt to the Qwen-VL HTTPS inference API with cert pinning."""
    payload = {
        "AuthKey": config.VLM_AUTH_KEY,
        "ImgBase64": img_b64,
        "PromptString": prompt,
    }

    session = _get_vlm_session()

    try:
        resp = session.post(config.VLM_API_URL, json=payload, timeout=120)
    except requests.exceptions.SSLError as e:
        return (
            f"Error: SSL certificate verification failed. "
            f"Verify that VLM_PINNED_CERT_PEM in vlm_config.json matches "
            f"the server certificate. Details: {e}"
        )
    except requests.exceptions.ConnectionError:
        return f"Error: cannot connect to VLM service at {config.VLM_API_URL}"
    except requests.exceptions.Timeout:
        return "Error: VLM inference request timed out (120s)"

    if resp.status_code == 401:
        return "Error: VLM authentication failed — check VLM_AUTH_KEY in config"
    if not resp.ok:
        return f"Error: VLM service returned {resp.status_code} — {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return f"Error: invalid JSON from VLM service — {resp.text[:300]}"

    reasoning = data.get("reasoning", "")
    answer = data.get("answer", "")
    if not answer:
        return "Error: VLM returned empty answer"

    if reasoning:
        return f"[推理]\n{reasoning}\n\n[回答]\n{answer}"
    return f"[回答]\n{answer}"


def _analyze_screen(prompt: str) -> str:
    """Capture the screen and send it to the VLM for analysis."""
    try:
        screenshot = pyautogui.screenshot()
    except Exception as e:
        return f"Error: failed to capture screen — {e}"

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return _call_vlm(img_b64, prompt)


def _analyze_image(img_b64: str, prompt: str) -> str:
    """Send a provided Base64 image to the VLM for analysis."""
    if not img_b64:
        return "Error: ImgBase64 is empty"
    if not prompt:
        return "Error: PromptString is empty"
    return _call_vlm(img_b64, prompt)
