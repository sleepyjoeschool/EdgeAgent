"""Screen capture executor.

OCR  : UMNI OCR (HTTP API)
YOLO : ultralytics (GPU) — model path is configured via config.YOLO_MODEL_PATH.
"""

import base64
import io
import json
from typing import Any

import config
import numpy as np
import pyautogui
import requests

# ── Lazy singletons ───────────────────────────────────────────────────

_yolo = None


def _get_yolo():
    """Lazy-init YOLO (GPU).  Model path is read from config.YOLO_MODEL_PATH."""
    global _yolo
    if _yolo is None:
        from ultralytics import YOLO
        device = "cuda" if _cuda_available() else "cpu"
        _yolo = YOLO(config.YOLO_MODEL_PATH)
        _yolo.to(device)
    return _yolo


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


# ── Public API ────────────────────────────────────────────────────────

LANGUAGE_MAP = {
    "chinese_simplified":  "models/config_chinese.txt",
    "english":             "models/config_en.txt",
    "chinese_traditional": "models/config_chinese_cht.txt",
    "japanese":            "models/config_japan.txt",
    "korean":              "models/config_korean.txt",
    "russian":             "models/config_cyrillic.txt",
}


def execute(function_name: str, arguments: dict) -> str:
    if function_name == "ScreenCaptureAction_CaptureScreen":
        lang = arguments.get("language")
        return _capture_screen(language=lang)
    if function_name == "ScreenCaptureAction_DetectObjects":
        threshold = arguments.get("confidence_threshold", 0.5)
        return detect_objects(confidence_threshold=threshold)
    return f"Error: unknown screen capture function '{function_name}'"


def _capture_screen(language: str | None = None) -> str:
    """Capture the screen and run UMNI OCR via HTTP API on the image.

    Args:
        language: Optional language key (e.g. \"japanese\", \"english\").
                  Omit for auto-detection.
    """
    try:
        screenshot = pyautogui.screenshot()
    except Exception as e:
        return f"Error: failed to capture screen — {e}"

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    # Build OCR options — always enable text-direction correction + multi-para
    options: dict[str, Any] = {
        "ocr.cls": True,
        "tbpu.parser": "multi_para",
    }
    if language and language in LANGUAGE_MAP:
        options["ocr.language"] = LANGUAGE_MAP[language]

    payload: dict[str, Any] = {"base64": img_b64}
    if options:
        payload["options"] = options

    # Use a dedicated session that bypasses system proxy for localhost
    session = requests.Session()
    session.trust_env = False

    try:
        resp = session.post(config.OCR_URL, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
    except requests.exceptions.ConnectionError:
        return f"Error: cannot connect to UMNI OCR service at {config.OCR_URL}"
    except requests.exceptions.Timeout:
        return "Error: UMNI OCR request timed out"
    except Exception as e:
        return f"Error: OCR request failed — {e}"

    data = raw.get("data", raw)
    if not data or (isinstance(data, list) and not data):
        return json.dumps([], ensure_ascii=False)

    results: list[dict[str, Any]] = []
    for item in data:
        text = item.get("text", "")
        confidence = item.get("confidence", item.get("score", 0))
        box = item.get("box", [])

        # Normalize box: Umi-OCR may return [[x1,y1],...] or [x1,y1,x2,y2,...]
        if box and isinstance(box[0], list):
            box = [v for pt in box for v in pt]

        results.append({
            "text": text,
            "confidence": round(confidence, 4),
            "box": box,
        })

    return json.dumps(results, ensure_ascii=False)


def detect_objects(confidence_threshold: float = 0.5) -> str:
    """Run YOLO object detection on the current screen.

    Routes to local or cloud inference based on config.YOLO_INFERENCE_MODE.
    """
    if config.YOLO_INFERENCE_MODE == "cloud":
        return _detect_objects_cloud(confidence_threshold)
    return _detect_objects_local(confidence_threshold)


def _detect_objects_local(confidence_threshold: float = 0.5) -> str:
    """Run YOLO locally (GPU) on the current screen."""
    try:
        screenshot = pyautogui.screenshot()
    except Exception as e:
        return f"Error: failed to capture screen — {e}"

    img = np.array(screenshot)

    try:
        yolo = _get_yolo()
        preds = yolo(img, verbose=False)
    except FileNotFoundError:
        return (
            f"Error: YOLO model not found at '{config.YOLO_MODEL_PATH}'. "
            f"Set SKILL_YOLO_MODEL environment variable or edit "
            f"config.YOLO_MODEL_PATH in config.py to point to a valid "
            f".pt / .onnx weights file."
        )
    except Exception as e:
        return f"Error: YOLO inference failed — {e}"

    results: list[dict[str, Any]] = []
    for pred in preds:
        boxes = pred.boxes
        if boxes is None:
            continue
        for i in range(len(boxes)):
            conf = float(boxes.conf[i])
            if conf < confidence_threshold:
                continue
            cls_id = int(boxes.cls[i])
            name = pred.names.get(cls_id, str(cls_id))
            xyxy = boxes.xyxy[i].tolist()
            results.append({
                "class": name,
                "confidence": round(conf, 4),
                "box": xyxy,
            })

    return json.dumps(results, ensure_ascii=False)


def _detect_objects_cloud(confidence_threshold: float = 0.5) -> str:
    """Run YOLO object detection via cloud API (Base64).

    Workflow:
    1. Capture screen via pyautogui.
    2. Encode screenshot as PNG Base64.
    3. POST to the cloud YOLO API with X-API-Key auth.
    4. Normalise the response to the same format as local inference.
    """
    if not config.YOLO_CLOUD_API_KEY:
        return (
            "Error: YOLO cloud API key is not configured. "
            "Set SKILL_YOLO_CLOUD_KEY environment variable or edit "
            "config.YOLO_CLOUD_API_KEY in config.py."
        )

    try:
        screenshot = pyautogui.screenshot()
    except Exception as e:
        return f"Error: failed to capture screen — {e}"

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": config.YOLO_CLOUD_API_KEY,
    }
    payload = {"image": img_b64}

    session = requests.Session()
    session.trust_env = False

    try:
        resp = session.post(
            config.YOLO_CLOUD_API_URL,
            json=payload,
            headers=headers,
            timeout=60,
        )
        if resp.status_code == 403:
            return "Error: YOLO cloud API returned 403 — invalid API key"
        resp.raise_for_status()
        raw = resp.json()
    except requests.exceptions.ConnectionError:
        return (
            f"Error: cannot connect to YOLO cloud API at "
            f"{config.YOLO_CLOUD_API_URL}"
        )
    except requests.exceptions.Timeout:
        return "Error: YOLO cloud API request timed out"
    except Exception as e:
        return f"Error: YOLO cloud API request failed — {e}"

    detections = raw.get("detections", [])
    if not detections:
        return json.dumps([], ensure_ascii=False)

    results: list[dict[str, Any]] = []
    for d in detections:
        conf = float(d.get("confidence", 0))
        if conf < confidence_threshold:
            continue
        results.append({
            "class": d.get("class_name", str(d.get("class_id", ""))),
            "confidence": round(conf, 4),
            "box": [
                d.get("x1"),
                d.get("y1"),
                d.get("x2"),
                d.get("y2"),
            ],
        })

    return json.dumps(results, ensure_ascii=False)
