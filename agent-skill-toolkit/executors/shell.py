"""Shell action executor using subprocess."""

import subprocess
import re
import sys
import os

# Patterns that indicate high-risk commands
SUSPICIOUS_PATTERNS = [
    re.compile(r"curl\s+.*\|\s*(ba)?sh", re.I),
    re.compile(r"wget\s+.*\|\s*(ba)?sh", re.I),
    re.compile(r"irm\s+.*\|\s*iex", re.I),           # PowerShell Invoke-Expression
    re.compile(r"Invoke-Expression", re.I),
    re.compile(r"eval\s+", re.I),
    re.compile(r"base64\s+-d", re.I),
    re.compile(r"reg\s+(add|delete)", re.I),
]

DANGEROUS_COMMANDS = [
    "rm -rf /", "rd /s /q C:", "format C:", "del /f /s /q C:",
]

# Lazy-import security_check to avoid circular imports at module level
_security_check = None


def _get_security_check():
    global _security_check
    if _security_check is None:
        _TOOLKIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _TOOLKIT_DIR not in sys.path:
            sys.path.insert(0, _TOOLKIT_DIR)
        import security_check
        _security_check = security_check
    return _security_check


def execute(function_name: str, arguments: dict) -> str:
    if function_name == "ShellAction_RunShell":
        return _run_shell(arguments)
    if function_name == "ShellAction_RunShellAsync":
        return _run_shell_async(arguments)
    return f"Error: unknown shell function '{function_name}'"


def _run_shell(args: dict) -> str:
    code = args.get("ShellCode", "")
    explanation = args.get("Explanation", "")

    if not code.strip():
        return "Error: ShellCode must not be empty"

    # Safety checks
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(code):
            return (
                f"SAFETY BLOCK: The command matches suspicious pattern "
                f"'{pattern.pattern}'. This looks like a potential malware "
                f"delivery attempt. REFUSING to execute."
            )

    for dangerous in DANGEROUS_COMMANDS:
        if dangerous.lower() in code.lower():
            return (
                f"SAFETY BLOCK: The command contains '{dangerous}' "
                f"which is a destructive operation. REFUSING to execute."
            )

    # LLM-based security check
    sc = _get_security_check()
    result = sc.check_shell_command(code, explanation)
    if not result.approved:
        return f"SAFETY BLOCK: {result.message}"

    try:
        result = subprocess.run(
            code,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=None,
        )
        output = result.stdout.strip()
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr.strip()

        if len(output) > 1500:
            summary = output[:700] + f"\n... (truncated, {len(output)} chars total) ...\n" + output[-700:]
            return summary

        return output if output else f"(exit code {result.returncode}, no output)"

    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120 seconds"
    except Exception as e:
        return f"Error: {e}"


def _run_shell_async(args: dict) -> str:
    code = args.get("ShellCode", "")
    explanation = args.get("Explanation", "")

    if not code.strip():
        return "Error: ShellCode must not be empty"

    # Safety checks (same as synchronous version)
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(code):
            return (
                f"SAFETY BLOCK: The command matches suspicious pattern "
                f"'{pattern.pattern}'. REFUSING to execute."
            )

    for dangerous in DANGEROUS_COMMANDS:
        if dangerous.lower() in code.lower():
            return (
                f"SAFETY BLOCK: The command contains '{dangerous}' "
                f"which is a destructive operation. REFUSING to execute."
            )

    # LLM-based security check
    sc = _get_security_check()
    check_result = sc.check_shell_command(code, explanation)
    if not check_result.approved:
        return f"SAFETY BLOCK: {check_result.message}"

    try:
        subprocess.Popen(
            code,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=None,
        )
        return f"Launched async: {code}"
    except Exception as e:
        return f"Error launching process: {e}"
