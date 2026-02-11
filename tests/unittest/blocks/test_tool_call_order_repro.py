"""Reproduction tests for tool-call ordering issues in persisted history."""

from __future__ import annotations

from unittest.mock import MagicMock

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.constants import KEY_HISTORY
from dolphin.core.common.enums import Messages
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.config.settings import BuildInBucket


def _build_tool_call(call_id: str, name: str, arguments: str = "{}") -> list[dict]:
    return [
        {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }
    ]


def _find_tool_sequence_issues(messages: list[dict]) -> list[str]:
    """Validate assistant(tool_calls) -> tool messages adjacency."""
    issues: list[str] = []
    idx = 0

    while idx < len(messages):
        msg = messages[idx]
        tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else None
        if msg.get("role") == "assistant" and isinstance(tool_calls, list) and tool_calls:
            expected_ids = [
                tc.get("id")
                for tc in tool_calls
                if isinstance(tc, dict) and tc.get("id")
            ]
            matched_ids: list[str] = []
            ptr = idx + 1

            while ptr < len(messages) and len(matched_ids) < len(expected_ids):
                next_msg = messages[ptr]
                if next_msg.get("role") != "tool":
                    issues.append(
                        f"assistant tool_calls at index {idx} followed by non-tool role={next_msg.get('role')} at index {ptr}"
                    )
                    break
                tool_call_id = next_msg.get("tool_call_id")
                if tool_call_id in expected_ids and tool_call_id not in matched_ids:
                    matched_ids.append(tool_call_id)
                ptr += 1

            if set(matched_ids) != set(expected_ids):
                issues.append(
                    f"assistant tool_calls at index {idx} missing adjacent tool responses: expected={expected_ids}, matched={matched_ids}"
                )

        idx += 1

    return issues


def _persist_history_for_scratchpad(
    scratchpad: Messages,
    user_query: str = "user-query",
    final_answer: str = "final-answer",
) -> list[dict]:
    context = Context()
    context.add_bucket(BuildInBucket.SCRATCHPAD.value, scratchpad)

    block = BasicCodeBlock(context=context)
    block.content = user_query
    block.recorder = MagicMock()
    block.recorder.get_answer.return_value = final_answer

    block._update_history_and_cleanup()
    history = context.get_var_value(KEY_HISTORY)
    assert isinstance(history, list)
    return history


def test_delayed_tool_responses_are_reordered_to_adjacent_pairs_in_history():
    """Delayed/reordered tool responses should be persisted adjacent to their calls."""
    scratchpad = Messages()

    # Simulate two assistant tool-call messages emitted before the first tool response.
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_00_nAmx", "_load_resource_skill", '{"skill_name":"s1"}'),
    )
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_00_qzN7", "_bash", '{"cmd":"echo hi"}'),
    )

    # Tool responses arrive in delayed/reordered manner.
    scratchpad.add_tool_response_message(
        content="bash-output",
        tool_call_id="call_00_qzN7",
    )
    scratchpad.add_tool_response_message(
        content="skill-output",
        tool_call_id="call_00_nAmx",
    )

    history = _persist_history_for_scratchpad(scratchpad)

    # Persisted history should satisfy assistant(tool_calls) -> tool adjacency.
    roles = [msg.get("role") for msg in history]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert history[2].get("tool_call_id") == "call_00_nAmx"
    assert history[4].get("tool_call_id") == "call_00_qzN7"

    # No protocol issue should remain after persistence reordering.
    issues = _find_tool_sequence_issues(history)
    assert issues == []


def test_tool_call_responses_should_be_adjacent():
    """Each assistant tool_call should be immediately followed by its tool response."""
    scratchpad = Messages()

    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_00_nAmx", "_load_resource_skill", '{"skill_name":"s1"}'),
    )
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_00_qzN7", "_bash", '{"cmd":"echo hi"}'),
    )
    scratchpad.add_tool_response_message(content="bash-output", tool_call_id="call_00_qzN7")
    scratchpad.add_tool_response_message(content="skill-output", tool_call_id="call_00_nAmx")

    history = _persist_history_for_scratchpad(scratchpad)
    issues = _find_tool_sequence_issues(history)

    assert issues == []


def test_unresponded_tool_calls_are_filtered_without_breaking_adjacency():
    """Unresponded tool calls should be dropped from persisted assistant.tool_calls."""
    scratchpad = Messages()
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=[
            _build_tool_call("call_a", "_tool_a")[0],
            _build_tool_call("call_b", "_tool_b")[0],
        ],
    )
    scratchpad.add_tool_response_message(content="result-b", tool_call_id="call_b")

    history = _persist_history_for_scratchpad(scratchpad)
    issues = _find_tool_sequence_issues(history)

    assert issues == []
    assert history[1]["role"] == "assistant"
    assert [tc["id"] for tc in history[1]["tool_calls"]] == ["call_b"]
    assert history[2]["role"] == "tool"
    assert history[2]["tool_call_id"] == "call_b"
    assert all("call_a" != item.get("tool_call_id") for item in history if isinstance(item, dict))


def test_duplicate_tool_responses_for_same_id_keep_first_response_only():
    """When duplicate tool responses exist for one id, only the first is persisted."""
    scratchpad = Messages()
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_dup", "_tool_dup"),
    )
    scratchpad.add_tool_response_message(content="first-response", tool_call_id="call_dup")
    scratchpad.add_tool_response_message(content="second-response", tool_call_id="call_dup")

    history = _persist_history_for_scratchpad(scratchpad)
    tool_msgs = [msg for msg in history if msg.get("role") == "tool"]
    issues = _find_tool_sequence_issues(history)

    assert issues == []
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_dup"
    assert tool_msgs[0]["content"] == "first-response"


def test_orphan_tool_responses_are_ignored_when_declared_id_exists():
    """Tool responses with undeclared ids should not be persisted."""
    scratchpad = Messages()
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_ok", "_tool_ok"),
    )
    scratchpad.add_tool_response_message(content="orphan", tool_call_id="call_orphan")
    scratchpad.add_tool_response_message(content="ok-result", tool_call_id="call_ok")

    history = _persist_history_for_scratchpad(scratchpad)
    tool_msgs = [msg for msg in history if msg.get("role") == "tool"]
    issues = _find_tool_sequence_issues(history)

    assert issues == []
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_ok"
    assert tool_msgs[0]["content"] == "ok-result"


def test_reordered_tool_responses_keep_original_timestamps():
    """Persisted reordered tool responses should retain original tool timestamps."""
    scratchpad = Messages()
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_1", "_tool_1"),
    )
    scratchpad.add_tool_call_message(
        content="",
        tool_calls=_build_tool_call("call_2", "_tool_2"),
    )
    scratchpad.add_tool_response_message(content="result-2", tool_call_id="call_2")
    scratchpad.add_tool_response_message(content="result-1", tool_call_id="call_1")

    all_msgs = scratchpad.get_messages()
    all_msgs[2].timestamp = "2026-02-01T10:00:00"
    all_msgs[3].timestamp = "2026-02-01T09:00:00"

    history = _persist_history_for_scratchpad(scratchpad)
    tool_msgs = [msg for msg in history if msg.get("role") == "tool"]

    assert [msg["tool_call_id"] for msg in tool_msgs] == ["call_1", "call_2"]
    assert [msg["timestamp"] for msg in tool_msgs] == [
        "2026-02-01T09:00:00",
        "2026-02-01T10:00:00",
    ]
