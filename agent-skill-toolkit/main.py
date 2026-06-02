"""
Agent Skill Toolkit — Main Entry Point
========================================
Orchestrates the conversation loop between the user, the DeepSeek LLM,
and the local skill executors.

Usage (via launcher in parent directory):
    python run.py              # interactive REPL
    python run.py "prompt..."  # single-shot
"""

import difflib
import json
import os
import sys
import time
import uuid

import httpx

# Allow direct imports from this directory (which has hyphens, so it
# can't be a normal Python package).
_TOOLKIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLKIT_DIR not in sys.path:
    sys.path.insert(0, _TOOLKIT_DIR)

from openai import OpenAI

import config
import tool_loader
import warning_notice
from executors.keyboard import execute as exec_keyboard
from executors.mouse import execute as exec_mouse
from executors.shell import execute as exec_shell
from executors.screen_capture import execute as exec_screen_capture
from executors.basic import execute as exec_basic
from executors.vlm import execute as exec_vlm

# ── Watchdog state ─────────────────────────────────────────────────────

_STUCK_RECOVERY_MSG = (
    "[Agent Message] Something went wrong resulting in the execution "
    "being stuck and being interrupted. Continue what you were doing."
)

_INTERRUPTED_MSG = (
    "There was an error that caused the execution to be interrupted. "
    "Please continue with your previous task."
)
_last_chunk_time: float = 0.0
_last_tool_time: float = 0.0


def _dispatch(function_name: str, arguments: dict) -> str:
    """Route a function call to the correct executor based on name prefix."""
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


UUID_PREFIX = "[UUID:"
UUID_SUFFIX = "]"


def _make_skill_uuid() -> str:
    """Generate a short, LLM-friendly UUID for a skill execution result."""
    return str(uuid.uuid4())


def _format_result_with_uuid(result: str, skill_uuid: str) -> str:
    """Prepend the UUID marker to a tool result so the LLM and system can identify it."""
    return f"{UUID_PREFIX}{skill_uuid}{UUID_SUFFIX}\n{result}"


def _extract_uuid(content: str | None) -> str | None:
    """Extract the skill UUID from a tool result content string, if present."""
    if not content or not content.startswith(UUID_PREFIX):
        return None
    end = content.find(UUID_SUFFIX, len(UUID_PREFIX))
    if end == -1:
        return None
    return content[len(UUID_PREFIX):end]


def _filter_deleted_messages(
    messages: list[dict],
    deleted_tool_call_ids: set[str],
) -> list[dict]:
    """Return a filtered copy of messages with deleted tool results removed.

    Removes:
    - Tool messages whose UUID maps to a deleted tool_call_id.
    - Corresponding tool_call entries from the preceding assistant message.
    - Assistant messages with no remaining tool_calls and no content.
    """
    # Build a lookup of which UUIDs are deleted → their tool_call_ids
    filtered: list[dict] = []
    for msg in messages:
        if msg["role"] == "tool":
            msg_uuid = _extract_uuid(msg.get("content", ""))
            if msg_uuid and msg["tool_call_id"] in deleted_tool_call_ids:
                continue  # skip deleted tool result
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            remaining_calls = [
                tc for tc in msg["tool_calls"]
                if tc["id"] not in deleted_tool_call_ids
            ]
            if not remaining_calls and msg.get("content") is None:
                continue  # drop assistant message with no remaining calls
            msg = {**msg, "tool_calls": remaining_calls}
        filtered.append(msg)
    return filtered


# ── Streaming response handler ──────────────────────────────────────────

def _stream_response(client: OpenAI, messages: list[dict], active_tools: list[dict]):
    """Stream a chat completion and return (content, tool_calls, reasoning)."""
    response = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        tools=active_tools,
        stream=True,
        reasoning_effort=config.REASONING_EFFORT,
        extra_body={"thinking": {"type": "enabled"}},
    )

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_call_chunks: dict[int, dict] = {}  # index -> {id, name, arguments}
    is_reasoning_phase = True
    phase_violation_warned = False  # track whether we already warned about phase violation

    for chunk in response:
        global _last_chunk_time
        _last_chunk_time = time.time()
        delta = chunk.choices[0].delta

        # ── Reasoning / thinking ──────────────────────────────────
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if is_reasoning_phase:
                print("\n[thinking] ", end="", flush=True)
                is_reasoning_phase = False
            print(delta.reasoning_content, end="", flush=True)
            reasoning_parts.append(delta.reasoning_content)

        # ── Tool calls (streamed as deltas) ───────────────────────
        if delta.tool_calls:
            # Guard: tool calls arriving after content has started is a phase violation
            if content_parts and not phase_violation_warned:
                phase_violation_warned = True
                print(
                    f"\n\033[33m[WARN] Tool calls received after final content "
                    f"already started — phase boundary violated!\033[0m",
                    flush=True,
                )
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

        # ── Content ───────────────────────────────────────────────
        if delta.content:
            # Guard: content arriving while tool calls are still being built
            # signals the model is mixing phases
            if tool_call_chunks and not content_parts and not phase_violation_warned:
                phase_violation_warned = True
                print(
                    "\n\033[33m[WARN] Final content started while tool calls "
                    "are still pending — phase boundary violated!\033[0m",
                    flush=True,
                )
            if not content_parts:
                # First content chunk — close thinking section if open
                if not is_reasoning_phase:
                    print("\n")
                print()  # newline before response
            print(delta.content, end="", flush=True)
            content_parts.append(delta.content)

    # Final newline
    if content_parts or (not reasoning_parts and not tool_call_chunks):
        pass  # streaming already handled spacing
    if reasoning_parts and not content_parts and not tool_call_chunks:
        print()

    # Reconstruct tool_calls from accumulated chunks
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

    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    return content, tool_calls, reasoning


# ── Step-by-step helpers ────────────────────────────────────────────────

# Internal safety limit: max tool-call rounds within a single step.
# One logical operation should never need more than this.
_MAX_INTERNAL_ROUNDS = 50

# Signal that the overall task is complete.
_TASK_COMPLETE_MARKER = "TASK_COMPLETE"

# Prompt injected after each step to trigger the next one.
_CONTINUE_PROMPT = (
    "Continue with the next logical operation for the original task. "
    "If all steps are complete, reply with 'TASK_COMPLETE' "
    "followed by a summary of what was accomplished."
)


def _strip_to_step_summaries(
    messages: list[dict],
    original_request: str,
) -> list[dict]:
    """Strip all intermediate messages, keeping only step summaries.

    Retains:
    - System prompt (first message)
    - Original user request
    - Every assistant message that has *content* but no *tool_calls*
      (these are step summaries)
    """
    clean: list[dict] = [messages[0]]  # system prompt
    clean.append({"role": "user", "content": original_request})

    for msg in messages[2:]:  # skip system + original user
        if msg["role"] == "assistant" and msg.get("content") and not msg.get("tool_calls"):
            clean.append(dict(msg))  # shallow copy — only content is kept

    return clean


def _run_one_step(
    client: OpenAI,
    messages: list[dict],
    active_tools: list[dict],
    loaded_categories: set[str],
    result_registry: dict[str, dict],
    deleted_tool_call_ids: set[str],
) -> tuple[str | None, str]:
    """Execute ONE step: internal tool-call loop until the LLM produces content.

    Returns (content, reasoning).  content may be None if the step failed.
    The caller is responsible for appending the final assistant message to
    *messages* when the step succeeds.
    """
    global _last_chunk_time, _last_tool_time
    _last_chunk_time = time.time()
    _last_tool_time = time.time()
    work_done = False
    step_round = 0
    empty_retries = 0

    while step_round < _MAX_INTERNAL_ROUNDS:
        step_round += 1
        clean_messages = _filter_deleted_messages(messages, deleted_tool_call_ids)

        try:
            content, tool_calls, reasoning = _stream_response(
                client, clean_messages, active_tools,
            )
        except (httpx.ReadTimeout, httpx.ReadError):
            now = time.time()
            if now - _last_chunk_time > 10 and now - _last_tool_time > 30:
                print(
                    f"\n\033[33m{_STUCK_RECOVERY_MSG}\033[0m",
                    flush=True,
                )
                messages.append({"role": "user", "content": _STUCK_RECOVERY_MSG})
                _last_chunk_time = time.time()
                _last_tool_time = time.time()
                continue
            raise

        # ── Tool calls ───────────────────────────────────────────────
        if tool_calls:
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

                args_preview = json.dumps(fn_args, ensure_ascii=False)
                if len(args_preview) > 120:
                    args_preview = args_preview[:117] + "…"
                print(f"\n[tool] {fn_name}({args_preview})")

                if fn_name == "LoadSkillCategory":
                    result = _handle_load_category(fn_args, loaded_categories, active_tools)
                elif fn_name == "ListSkillResults":
                    result = _handle_list_results(result_registry, deleted_tool_call_ids)
                elif fn_name == "DeleteSkillResult":
                    result = _handle_delete_results(
                        fn_args, result_registry, deleted_tool_call_ids,
                    )
                else:
                    result = _dispatch(fn_name, fn_args)
                    work_done = True

                _last_tool_time = time.time()

                if fn_name not in ("LoadSkillCategory", "ListSkillResults", "DeleteSkillResult"):
                    skill_uuid = _make_skill_uuid()
                    result_registry[skill_uuid] = {
                        "tool_call_id": tc["id"],
                        "function": fn_name,
                        "timestamp": time.time(),
                    }
                    result = _format_result_with_uuid(result, skill_uuid)

                is_error = result.startswith("Error:") or result.startswith("SAFETY BLOCK")
                length = len(result)
                if is_error:
                    print(f"  \033[31m✗ Error\033[0m ({length} chars)")
                else:
                    print(f"  \033[32m✓ OK\033[0m ({length} chars)")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # When content arrived together with tool_calls, the model
            # intended to stop after these tools — but only treat it as
            # a step summary when domain tools were actually called.
            # If only meta-tools (LoadSkillCategory, etc.)
            # ran, the content is likely planning/intent rather than a
            # summary of accomplished work, so continue the loop.
            if content:
                if work_done:
                    print()
                    messages.append({"role": "assistant", "content": content})
                    return content, reasoning
                else:
                    # Only meta-tools called — append content as context
                    # and let the next round call domain tools.
                    messages.append({"role": "assistant", "content": content})

            continue

        # ── Final text response (no tool calls) ──────────────────────
        if content:
            # Accept the step summary even when no domain tools were called
            # (the model may have concluded the task is already done).
            print()
            messages.append({"role": "assistant", "content": content})
            return content, reasoning

        # Empty response — retry once, then abort to avoid infinite loop
        empty_retries += 1
        if empty_retries > 1:
            print(
                f"\n\033[31mStep failed after {empty_retries} empty responses "
                f"— aborting step.\033[0m",
                flush=True,
            )
            return None, ""
        print(f"\n\033[33m{_INTERRUPTED_MSG}\033[0m", flush=True)
        messages.append({"role": "user", "content": _INTERRUPTED_MSG})

    print(f"\n[step exceeded {_MAX_INTERNAL_ROUNDS} internal rounds — aborting step]")
    return None, ""


# ── Conversation loop ──────────────────────────────────────────────────

def _run_loop(client: OpenAI, user_prompt: str | None = None) -> None:
    """Main conversation loop using step-by-step execution.

    Each step completes exactly ONE operation.  Between steps the
    intermediate messages (thinking, tool calls, tool results) are
    stripped so the next step only sees the original task + past step
    summaries.
    """

    entry = tool_loader.load_entry_point()
    system_prompt = entry["system_prompt"]

    # Start with meta-tools + basic utilities (clipboard, etc.)
    # Basic tools are always available
    _default_tools: list[dict] = list(entry["tools"])
    try:
        _default_tools.extend(tool_loader.load_category_tools("basic"))
    except Exception:
        pass

    if user_prompt:
        # ── Single-shot / automated multi-step ───────────────────────
        _run_multi_step(client, system_prompt, _default_tools, user_prompt)
    else:
        # ── Interactive REPL ─────────────────────────────────────────
        print("Agent Skill Toolkit — type /help for commands, /quit to exit")
        print(f"Model: {config.DEEPSEEK_MODEL}")
        print(f"Architecture: Step-by-step (max {config.MAX_STEPS} steps)")
        print("Loaded: LoadSkillCategory (meta-tool)")
        print()

        active_tools: list[dict] = list(_default_tools)
        loaded_categories: set[str] = set()
        result_registry: dict[str, dict] = {}
        deleted_tool_call_ids: set[str] = set()
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]

        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line.lower() in ("/quit", "/q", "/exit"):
                break
            if line.lower() == "/help":
                _print_help(loaded_categories)
                continue
            if line.lower() == "/tools":
                _print_tools(active_tools)
                continue
            if line.lower() == "/results":
                print()
                print(_handle_list_results(result_registry, deleted_tool_call_ids))
                print()
                continue
            if line.lower() == "/reset":
                active_tools = list(_default_tools)
                loaded_categories.clear()
                result_registry.clear()
                deleted_tool_call_ids.clear()
                messages = [{"role": "system", "content": system_prompt}]
                print("[reset] Tools, conversation, and skill result registry cleared.")
                continue

            messages.append({"role": "user", "content": line})
            original_request = line

            try:
                _run_multi_step(
                    client, system_prompt, _default_tools,
                    original_request, messages=messages,
                )
            except Exception as e:
                print(f"\n\033[31mError: {e}\033[0m", flush=True)
                print(f"\033[33m{_INTERRUPTED_MSG}\033[0m", flush=True)
                messages.append({"role": "user", "content": _INTERRUPTED_MSG})


def _run_multi_step(
    client: OpenAI,
    system_prompt: str,
    default_tools: list[dict],
    original_request: str,
    messages: list[dict] | None = None,
) -> None:
    """Execute a user request across one or more steps.

    Each step completes one logical operation.  Intermediate messages
    (thinking, tool calls, tool results) are stripped after each step so
    that the next step only sees the original request + step summaries.
    """

    # Build fresh message list or reuse the caller's (REPL mode)
    if messages is None:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": original_request},
        ]

    previous_summaries: list[str] = []

    for step_num in range(1, config.MAX_STEPS + 1):
        # ── Per-step fresh state (tools are NOT persisted across steps) ──
        active_tools: list[dict] = list(default_tools)
        loaded_categories: set[str] = set()
        result_registry: dict[str, dict] = {}
        deleted_tool_call_ids: set[str] = set()

        try:
            content, _reasoning = _run_one_step(
                client, messages, active_tools, loaded_categories,
                result_registry, deleted_tool_call_ids,
            )
        except Exception as e:
            print(f"\n\033[31mError at step {step_num}: {e}\033[0m", flush=True)
            break

        if not content:
            print(f"\n\033[33mStep {step_num} returned no content — retrying.\033[0m", flush=True)
            messages.append({"role": "user", "content": _INTERRUPTED_MSG})
            continue

        # The step summary was already appended to *messages* by _run_one_step.
        print(f"\n\033[1m[Step {step_num}]\033[0m {content}")

        # ── Check for task completion ──────────────────────────────────
        if content.strip().startswith(_TASK_COMPLETE_MARKER):
            print()
            return

        # ── Stuck detection: near-duplicate consecutive step summaries ─
        summary_stripped = content.strip()
        previous_summaries.append(summary_stripped)
        if len(previous_summaries) >= 3:
            s0, s1, s2 = previous_summaries[-3:]
            r01 = difflib.SequenceMatcher(None, s0, s1).ratio()
            r12 = difflib.SequenceMatcher(None, s1, s2).ratio()
            r02 = difflib.SequenceMatcher(None, s0, s2).ratio()
            if r01 > 0.8 and r12 > 0.8 and r02 > 0.8:
                print(
                    f"\n\033[31mNear-duplicate step summaries detected "
                    f"(sim {r01:.2f}/{r12:.2f}/{r02:.2f}) — "
                    f"agent is stuck. Aborting.\033[0m",
                    flush=True,
                )
                break

        # ── Strip to step summaries for the next step ──────────────────
        # Build a clean message list: system + original request + summaries
        clean = _strip_to_step_summaries(messages, original_request)
        # Overwrite *messages* so the next step sees a clean view.
        messages.clear()
        messages.extend(clean)

        # ── Inject continuation prompt ─────────────────────────────────
        messages.append({"role": "user", "content": _CONTINUE_PROMPT})

    else:
        print(f"\n[stopped after {config.MAX_STEPS} steps]")


def _handle_load_category(
    args: dict,
    loaded_categories: set[str],
    active_tools: list[dict],
) -> str:
    """Execute LoadSkillCategory: load tool definitions into the active set."""
    category = args.get("category", "")
    try:
        tools = tool_loader.load_category_tools(category)
    except ValueError as e:
        return str(e)

    if category in loaded_categories:
        tool_names = [t["function"]["name"] for t in tools]
        return (
            f"Category '{category}' is already loaded. "
            f"Available: {', '.join(tool_names)}"
        )

    loaded_categories.add(category)
    active_tools.extend(tools)
    desc = tool_loader.get_category_description(category)
    tool_names = [t["function"]["name"] for t in tools]
    return (
        f"Loaded category '{category}': {desc}\n"
        f"Available functions: {', '.join(tool_names)}"
    )


def _handle_list_results(
    result_registry: dict[str, dict],
    deleted_tool_call_ids: set[str],
) -> str:
    """List all non-deleted skill execution results with their UUIDs."""
    entries: list[str] = []
    for skill_uuid, info in result_registry.items():
        if info["tool_call_id"] in deleted_tool_call_ids:
            continue
        ts = info["timestamp"]
        time_str = time.strftime("%H:%M:%S", time.localtime(ts))
        entries.append(f"  {skill_uuid} | {info['function']} | {time_str}")
    if not entries:
        return "No skill execution results in context."
    return "UUID | Function | Time\n" + "\n".join(entries)


def _handle_delete_results(
    args: dict,
    result_registry: dict[str, dict],
    deleted_tool_call_ids: set[str],
) -> str:
    """Delete skill execution results by UUID."""
    uuids: list[str] = args.get("uuids", [])
    if not uuids:
        return "Error: uuids must be a non-empty list"

    deleted: list[str] = []
    missing: list[str] = []
    already_deleted: list[str] = []

    for skill_uuid in uuids:
        info = result_registry.get(skill_uuid)
        if info is None:
            missing.append(skill_uuid)
        elif info["tool_call_id"] in deleted_tool_call_ids:
            already_deleted.append(skill_uuid)
        else:
            deleted_tool_call_ids.add(info["tool_call_id"])
            deleted.append(skill_uuid)

    parts: list[str] = []
    if deleted:
        parts.append(f"Deleted {len(deleted)} result(s): {', '.join(deleted)}")
    if missing:
        parts.append(f"UUID(s) not found: {', '.join(missing)}")
    if already_deleted:
        parts.append(f"Already deleted: {', '.join(already_deleted)}")
    return "\n".join(parts) if parts else "No results matched the given UUIDs."


def _print_help(loaded_categories: set[str]) -> None:
    print()
    print("Commands:")
    print("  /help     Show this message")
    print("  /tools    List currently loaded tools")
    print("  /results  List skill execution results in context (UUIDs)")
    print("  /reset    Clear conversation and reload entry tools")
    print("  /quit     Exit")
    print()
    print("Context management (always available):")
    print("  ListSkillResults          List all skill execution results with UUIDs")
    print("  DeleteSkillResult(uuids)  Delete results by UUID to free context")
    print()
    entry = tool_loader.load_entry_point()
    cats = entry.get("available_categories", {})
    print("Available categories (loaded on demand):")
    for name, info in cats.items():
        marker = " [loaded]" if name in loaded_categories else ""
        print(f"  {name} ({info['tool_count']} tools){marker}: {info['description']}")
    print()


def _print_tools(active_tools: list[dict]) -> None:
    print()
    if not active_tools:
        print("  (no tools loaded)")
        print()
        return
    for tool in active_tools:
        fn = tool["function"]
        params = list(fn.get("parameters", {}).get("properties", {}).keys())
        print(f"  {fn['name']}({', '.join(params) if params else '—'})")
    print()


def main() -> None:
    if not warning_notice.show_cli_warning():
        return

    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=httpx.Timeout(connect=10.0, read=12.0, write=10.0, pool=10.0),
    )

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        _run_loop(client, prompt)
    else:
        _run_loop(client)


if __name__ == "__main__":
    main()
