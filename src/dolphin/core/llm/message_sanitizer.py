from __future__ import annotations

import re as _re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from dolphin.core.common.constants import PIN_MARKER

# Default prefix for downgraded tool messages
DOWNGRADED_TOOL_PREFIX = "[Tool Output]: "

# Regex patterns that identify reasoning models requiring
# reasoning_content in assistant tool-call messages.
# Each pattern is matched against the full (lowered) model name with re.search.

_REASONING_MODEL_PATTERNS = [
    _re.compile(r"^kimi-for-coding\b"),
]


def needs_reasoning_content(model_name: str) -> bool:
    """Check whether *model_name* belongs to a reasoning-model family that
    requires ``reasoning_content`` on assistant tool-call messages."""
    name = model_name.lower()
    return any(p.search(name) for p in _REASONING_MODEL_PATTERNS)


def sanitize_openai_messages(
    messages: List[Dict[str, Any]],
    *,
    downgrade_role: str = "user",
    pinned_downgrade_role: str = "assistant",
    downgraded_prefix: str = DOWNGRADED_TOOL_PREFIX,
    ensure_reasoning_content: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Best-effort sanitizer for OpenAI-compatible tool message constraints.

    OpenAI-compatible APIs require:
    - role="tool" messages must be responses to a preceding assistant message with tool_calls
    - tool messages must carry tool_call_id and it must match a previously declared tool_calls[].id

    In real systems, context restore/compression/persistence may produce orphan tool messages, e.g.:
    - tool appears before any assistant(tool_calls) (system -> tool -> user)
    - tool_call_id missing or mismatched

    This function downgrades orphan tool messages into normal text messages to avoid hard API failures.

    When ``ensure_reasoning_content`` is True, all assistant messages with
    tool_calls will be ensured to carry a ``reasoning_content`` field (defaulting
    to ``" "``), because some providers (e.g. Kimi) reject tool-call messages
    without it when thinking mode is active.  A single space is used because
    the Kimi API treats empty strings as "missing".

    Returns:
    - sanitized_messages: list[dict] safe to send to OpenAI-compatible APIs
    - downgraded_count: number of tool messages downgraded
    """
    if not messages:
        return messages, 0

    declared_tool_call_ids: set[str] = set()
    seen_any_tool_calls = False
    downgraded = 0
    sanitized: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")

        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                seen_any_tool_calls = True
                for tc in tool_calls:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared_tool_call_ids.add(tc["id"])
                if ensure_reasoning_content and "reasoning_content" not in msg:
                    msg = {**msg, "reasoning_content": " "}
            sanitized.append(msg)
            continue

        if role != "tool":
            sanitized.append(msg)
            continue

        # NOTE: Some workflows inject pinned tool outputs (e.g. skill docs) even when
        # the model didn't initiate a tool call. OpenAI-compatible providers (incl. DashScope)
        # may reject *any* role="tool" message unless it is part of a valid tool_calls sequence.
        # Pinned outputs are best represented as normal assistant text to avoid hard API failures.
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        tool_call_id = msg.get("tool_call_id")
        is_orphan = False
        if not seen_any_tool_calls:
            is_orphan = True
        elif not tool_call_id or not isinstance(tool_call_id, str):
            is_orphan = True
        elif tool_call_id not in declared_tool_call_ids:
            is_orphan = True

        # If a pinned tool message is a valid response to a preceding tool_calls entry,
        # keep it as role="tool" so OpenAI-compatible providers won't reject the sequence.
        if content.startswith(PIN_MARKER):
            if is_orphan:
                downgraded += 1
                sanitized.append({"role": pinned_downgrade_role, "content": content})
            else:
                sanitized.append(msg)
            continue

        if not is_orphan:
            sanitized.append(msg)
            continue

        downgraded += 1
        downgraded_msg = {"role": downgrade_role, "content": f"{downgraded_prefix}{content}"}
        sanitized.append(downgraded_msg)

    # Second pass: strip orphan assistant tool_calls (declared but no matching
    # tool response).  This prevents hard 400 errors from providers like DashScope
    # that reject assistant messages with tool_calls lacking tool responses.
    #
    # We match in *message order* so that when the same tool_call_id appears in
    # multiple rounds, a tool response is paired with the closest preceding
    # (most recent) unmatched declaration rather than the earliest one.
    #
    # Algorithm:
    #   1. Forward scan: record assistant tool_call declarations in a per-id
    #      stack (list of msg indices).  When a tool response is encountered,
    #      pop the most-recent unmatched declaration for that id.
    #   2. Rebuild: keep only the matched declarations in each assistant message.

    # pending[tc_id] = [msg_idx, ...] — indices of assistant messages that
    # declared this tc_id but haven't been matched yet (oldest first).
    pending: Dict[str, List[int]] = defaultdict(list)
    # matched_budget[msg_idx][tc_id] = how many declarations at msg_idx matched
    matched_budget: Dict[int, Counter[str]] = defaultdict(Counter)

    for idx, msg in enumerate(sanitized):
        role = msg.get("role")
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        if isinstance(tc_id, str):
                            pending[tc_id].append(idx)
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if isinstance(tid, str) and pending.get(tid):
                # Match to the most recent unmatched declaration (closest preceding)
                matched_idx = pending[tid].pop()
                matched_budget[matched_idx][tid] += 1

    result: List[Dict[str, Any]] = []
    for idx, msg in enumerate(sanitized):
        if msg.get("role") == "assistant":
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                budget = matched_budget.get(idx, Counter())
                kept = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    tc_id = tc.get("id")
                    if isinstance(tc_id, str) and budget.get(tc_id, 0) > 0:
                        budget[tc_id] -= 1
                        kept.append(tc)
                dropped = len(tool_calls) - len(kept)
                if dropped > 0:
                    downgraded += dropped
                    if kept:
                        msg = {**msg, "tool_calls": kept}
                    else:
                        msg = {
                            k: v for k, v in msg.items() if k != "tool_calls"
                        }
                        if not msg.get("content"):
                            msg["content"] = ""
        result.append(msg)

    return result, downgraded


def sanitize_and_log(
    messages: List[Dict[str, Any]],
    warning_fn: Optional[Callable[[str], None]] = None,
    **sanitize_kwargs,
) -> List[Dict[str, Any]]:
    """Sanitize messages and optionally log warnings about downgraded tool messages.

    Args:
        messages: List of message dictionaries to sanitize
        warning_fn: Optional callable to log warnings (e.g., logger.warning or context.warn)
        **sanitize_kwargs: Additional arguments to pass to sanitize_openai_messages

    Returns:
        Sanitized message list safe for OpenAI-compatible APIs
    """
    sanitized_messages, downgraded_count = sanitize_openai_messages(
        messages, **sanitize_kwargs
    )
    if downgraded_count and warning_fn:
        warning_fn(
            f"Detected {downgraded_count} orphan tool message(s); "
            "downgraded for OpenAI compatibility"
        )
    return sanitized_messages
