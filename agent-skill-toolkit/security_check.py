"""
Autonomous LLM-based security check for shell commands.

Before each shell command executes, this module sends a context-free query
to a fresh DeepSeek client asking whether the command is dangerous.
Dangerous commands trigger a native OS popup requiring human approval.
"""

from __future__ import annotations

import json
import sys
import ctypes
from typing import Any

import httpx
from openai import OpenAI

import config

# ── Security audit prompt ─────────────────────────────────────────────────

SECURITY_SYSTEM_PROMPT = """\
You are an expert security auditor for computer shell commands.
Your job is to analyze commands and determine if they could cause
SERIOUS, IRREVERSIBLE damage to the computer system.

"Serious, irreversible damage" means:
- Deleting or corrupting the operating system files (e.g., rm -rf /, del C:\\Windows)
- Formatting drives (e.g., format C:, mkfs)
- Wiping the entire filesystem or home directory
- Bricking the machine (firmware attacks, disk encryption sabotage)
- Mass data destruction beyond a scoped project/work directory
- Modifying system boot configuration in destructive ways

NOT considered serious/irreversible:
- Commands scoped to a specific project directory (even if they delete files)
- Normal package management (pip install, npm, apt-get)
- Git operations (even force push)
- Process management (kill, taskkill)
- File moves/renames within a workspace
- Standard build/dev commands (make, cargo, docker, etc.)

Reply with a JSON object — no other text:
{
  "is_dangerous": true or false,
  "overall_risk": "one-sentence summary of the danger, or 'safe' if none",
  "parts": [
    {"part": "the specific dangerous segment", "why": "why it's dangerous"}
  ]
}
"""


def _build_user_query(shell_code: str, explanation: str) -> str:
    return f"""Analyze this shell command for safety:

Command:
```
{shell_code}
```

User's stated intent:
{explanation if explanation.strip() else "(no explanation provided)"}

Output ONLY the JSON object."""


# ── DeepSeek API call ─────────────────────────────────────────────────────

def _call_deepseek_security_check(shell_code: str, explanation: str) -> dict[str, Any]:
    """Send a context-free query to DeepSeek. Returns parsed JSON dict."""
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0),
    )

    messages = [
        {"role": "system", "content": SECURITY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_query(shell_code, explanation)},
    ]

    response = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1024,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise ValueError("DeepSeek returned empty response for security check")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        import re
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            result = json.loads(match.group(0))
        else:
            raise ValueError(f"Failed to parse security check response: {raw[:200]}")

    return result


# ── Native popup (thread-safe via Win32 MessageBox) ───────────────────────

def _show_windows_popup(title: str, message: str) -> bool:
    """Show a native Windows MessageBox with Yes/No. Thread-safe.
    Returns True if user clicked Yes (approve), False otherwise."""
    MB_YESNO = 0x00000004
    MB_ICONWARNING = 0x00000030
    MB_DEFBUTTON2 = 0x00000100  # default to No
    IDYES = 6

    try:
        result = ctypes.windll.user32.MessageBoxW(
            0, message, title, MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2
        )
        return result == IDYES
    except Exception:
        return False


def _show_cli_prompt(shell_code: str, overall_risk: str, parts: list[dict]) -> bool:
    """Fallback CLI prompt for non-Windows or when MessageBox fails."""
    print()
    print("=" * 60)
    print("SECURITY WARNING — This command may be dangerous!")
    print("=" * 60)
    print(f"\nCommand: {shell_code}")
    print(f"\nRisk: {overall_risk}")
    if parts:
        print("\nAnalysis:")
        for p in parts:
            print(f"  • {p.get('part', '?')}: {p.get('why', 'no details')}")
    print()
    while True:
        try:
            choice = input("Execute anyway? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no", ""):
            return False
        print("  Please enter 'y' or 'n'")


# ── Public API ────────────────────────────────────────────────────────────

class SecurityCheckResult:
    def __init__(self, approved: bool, message: str) -> None:
        self.approved = approved
        self.message = message


def check_shell_command(shell_code: str, explanation: str = "") -> SecurityCheckResult:
    """Run the LLM security check and, if dangerous, request human approval.

    Returns a SecurityCheckResult:
    - approved=True, message=""  → safe to execute
    - approved=True, message="Approved by user" → dangerous but user allowed it
    - approved=False, message="Rejected, ..." → dangerous and user denied
    """

    # ── 1. Call DeepSeek for security analysis ─────────────────────────
    print("Pending Security Check via LLM...", end="", flush=True)
    try:
        result = _call_deepseek_security_check(shell_code, explanation)
    except Exception as e:
        print(f" failed ({e})", flush=True)
        # If the security check itself fails, allow execution (static
        # pattern checks in shell.py still run as a safety net).
        return SecurityCheckResult(True, "")
    print(" done.", flush=True)

    is_dangerous = result.get("is_dangerous", False)
    overall_risk = result.get("overall_risk", "")
    parts = result.get("parts", [])

    if not is_dangerous:
        return SecurityCheckResult(True, "")

    # ── 2. Command is dangerous — request human approval ───────────────
    parts_text = ""
    for p in parts:
        parts_text += f"\n  • {p.get('part', '?')}: {p.get('why', 'no details')}"

    popup_message = (
        f"The following command may be DANGEROUS:\n\n"
        f"{shell_code}\n\n"
        f"Risk: {overall_risk}\n"
        f"Analysis:{parts_text}\n\n"
        f"Do you want to execute it anyway?"
    )

    if sys.platform == "win32":
        approved = _show_windows_popup(
            "Security Warning — Desktop Agent", popup_message
        )
    else:
        approved = _show_cli_prompt(shell_code, overall_risk, parts)

    if approved:
        return SecurityCheckResult(True, "Approved by user")
    else:
        # Build the rejection reason
        reasons = "; ".join(p.get("why", "") for p in parts if p.get("why"))
        if not reasons:
            reasons = overall_risk
        return SecurityCheckResult(False, f"Rejected, {reasons}")
