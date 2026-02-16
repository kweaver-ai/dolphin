from __future__ import annotations

import re as _re
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

    return sanitized, downgraded


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
