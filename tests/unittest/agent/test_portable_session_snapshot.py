import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dolphin.core.common.constants import KEY_HISTORY, KEY_SESSION_ID
from dolphin.core.common.exceptions import DolphinAgentException
from dolphin.core.context.context import Context
from dolphin.sdk.agent.dolphin_agent import DolphinAgent


def _new_agent(name: str = "portable") -> DolphinAgent:
    with patch(
        "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
        return_value=None,
    ), patch("dolphin.core.executor.dolphin_executor.DolphinExecutor"):
        return DolphinAgent(name=name, content="/prompt/ test -> result")


def _bind_context(agent: DolphinAgent, context: Context) -> None:
    mock_executor = MagicMock()
    mock_executor.context = context
    agent.executor = mock_executor


def _build_agent_with_context() -> tuple[DolphinAgent, Context]:
    agent = _new_agent()
    context = Context()
    context.set_session_id("sess_001")
    context.set_variable("counter", 3)
    context.set_variable("bad_set", {"a", "b"})
    context.set_variable(
        KEY_HISTORY,
        [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_ok",
                        "type": "function",
                        "function": {"name": "_tool_ok", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "result", "tool_call_id": "call_ok"},
            {"role": "assistant", "content": "done"},
        ],
    )
    _bind_context(agent, context)
    return agent, context


def test_export_portable_session_is_json_serializable():
    agent, _ = _build_agent_with_context()

    state = agent.snapshot.export_portable_session()
    json.dumps(state)

    assert state["schema_version"] == "portable_session.v1"
    assert state["session_id"] == "sess_001"
    assert isinstance(state["history_messages"], list)
    assert isinstance(state["variables"], dict)
    assert isinstance(state["variables"]["bad_set"], list)
    assert sorted(state["variables"]["bad_set"]) == ["a", "b"]


def test_export_portable_session_excludes_internal_variables():
    """Verify that internal variables like _progress, usage, props are excluded."""
    agent, context = _build_agent_with_context()
    context.set_variable("_progress", [{"step": 1}])
    context.set_variable("usage", {"tokens": 100})
    context.set_variable("props", {"key": "val"})
    context.set_variable("user_var", "keep_me")

    state = agent.snapshot.export_portable_session()
    assert "user_var" in state["variables"]
    assert "_progress" not in state["variables"]
    assert "usage" not in state["variables"]
    assert "props" not in state["variables"]


def test_export_portable_session_set_order_is_deterministic():
    """Verify that set serialization produces deterministic ordering."""
    agent, _ = _build_agent_with_context()

    state1 = agent.snapshot.export_portable_session()
    state2 = agent.snapshot.export_portable_session()
    assert state1["variables"]["bad_set"] == state2["variables"]["bad_set"]
    assert state1["variables"]["bad_set"] == ["a", "b"]


def test_validate_portable_session_detects_tool_protocol_issues():
    agent, _ = _build_agent_with_context()

    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_x",
        "variables": {},
        "history_messages": [
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_missing",
                        "type": "function",
                        "function": {"name": "_tool", "arguments": "{}"},
                    }
                ],
            },
        ],
    }

    issues = agent.snapshot.validate_portable_session(bad_state)
    codes = {item["code"] for item in issues}
    assert "ORPHAN_TOOL_MESSAGE" in codes
    assert "MISSING_TOOL_RESPONSE" in codes


def test_validate_portable_session_accepts_tool_call_id_field():
    """Validate accepts tool_calls entries using 'tool_call_id' instead of 'id'."""
    agent, _ = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_compat",
        "variables": {},
        "history_messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "tool_call_id": "call_legacy",
                        "type": "function",
                        "function": {"name": "_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "call_legacy"},
        ],
    }

    issues = agent.snapshot.validate_portable_session(state)
    assert issues == []


def test_repair_portable_session_uses_minimal_trim_strategy():
    agent, _ = _build_agent_with_context()

    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_fix",
        "variables": {},
        "history_messages": [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "_tool_a", "arguments": "{}"},
                    },
                    {
                        "id": "call_b",
                        "type": "function",
                        "function": {"name": "_tool_b", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            {"role": "tool", "content": "result_b", "tool_call_id": "call_b"},
            {"role": "assistant", "content": "done"},
        ],
    }

    repaired_state, repair_report = agent.snapshot.repair_portable_session(bad_state)
    issues_after = agent.snapshot.validate_portable_session(repaired_state)
    assert issues_after == []
    assert repair_report["applied"] is True

    history = repaired_state["history_messages"]
    assert history[1]["role"] == "assistant"
    assert [tc["id"] for tc in history[1].get("tool_calls", [])] == ["call_b"]
    assert history[2]["role"] == "tool"
    assert history[2]["tool_call_id"] == "call_b"


def test_repair_portable_session_normalizes_tool_call_id_to_id():
    """Repair normalizes tool_call_id field in tool_calls entries to canonical 'id'."""
    agent, _ = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_norm",
        "variables": {},
        "history_messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "tool_call_id": "call_legacy",
                        "type": "function",
                        "function": {"name": "_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "call_legacy"},
        ],
    }

    repaired, report = agent.snapshot.repair_portable_session(state)
    issues = agent.snapshot.validate_portable_session(repaired)
    assert issues == []
    tc = repaired["history_messages"][0]["tool_calls"][0]
    assert tc["id"] == "call_legacy"
    assert "tool_call_id" not in tc


def test_import_portable_session_repair_and_restore_context():
    agent, context = _build_agent_with_context()

    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_restored",
        "variables": {"foo": "bar"},
        "history_messages": [
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            {"role": "user", "content": "new turn"},
            {"role": "assistant", "content": "ok"},
        ],
    }

    report = agent.snapshot.import_portable_session(bad_state, repair=True)
    assert report["applied_repairs"] is True
    assert report["issues_after"] == []

    assert context.get_session_id() == "sess_restored"
    assert context.get_var_value("foo") == "bar"

    history = context.get_history_messages(normalize=True).get_messages_as_dict()
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "new turn"


def test_import_portable_session_repair_false_keeps_issues():
    agent, context = _build_agent_with_context()
    old_session_id = context.get_session_id()

    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_not_applied",
        "variables": {},
        "history_messages": [
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
        ],
    }

    report = agent.snapshot.import_portable_session(bad_state, repair=False)
    assert report["applied_repairs"] is False
    assert report["issues_before"]
    assert context.get_session_id() == old_session_id


def test_import_portable_session_skips_session_id_in_variables():
    """Top-level session_id is authoritative; KEY_SESSION_ID in variables is skipped."""
    agent, context = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_top_level",
        "variables": {KEY_SESSION_ID: "sess_from_variable"},
        "history_messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    }

    agent.snapshot.import_portable_session(state, repair=True)
    assert context.get_session_id() == "sess_top_level"


def test_repair_portable_session_deduplicates_tool_responses():
    agent, _ = _build_agent_with_context()

    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_dup",
        "variables": {},
        "history_messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_dup",
                        "type": "function",
                        "function": {"name": "_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "first", "tool_call_id": "call_dup"},
            {"role": "tool", "content": "second", "tool_call_id": "call_dup"},
        ],
    }

    repaired, report = agent.snapshot.repair_portable_session(bad_state)
    issues = agent.snapshot.validate_portable_session(repaired)
    assert issues == []
    tool_msgs = [m for m in repaired["history_messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "first"
    assert report["applied"] is True


def test_validate_portable_session_invalid_tool_call_entry():
    agent, _ = _build_agent_with_context()
    bad_state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_invalid_tc",
        "variables": {},
        "history_messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "_x"}}],
            }
        ],
    }
    issues = agent.snapshot.validate_portable_session(bad_state)
    codes = {i["code"] for i in issues}
    assert "INVALID_TOOL_CALL_ENTRY" in codes
    assert "EMPTY_TOOL_CALL_IDS" in codes


def test_export_portable_session_requires_initialized_agent():
    with patch(
        "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
        return_value=None,
    ), patch("dolphin.core.executor.dolphin_executor.DolphinExecutor"):
        agent = DolphinAgent(name="portable_not_init", content="/prompt/ x -> y")
    agent.executor = None

    with pytest.raises(DolphinAgentException):
        agent.snapshot.export_portable_session()


def test_repair_report_separates_degraded_fields_from_actions():
    """Verify RepairReport has separate degraded_fields and actions lists."""
    agent, _ = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_degrade",
        "variables": {"key": {"nested": "value"}},
        "history_messages": [],
    }

    _, report = agent.snapshot.repair_portable_session(state)
    assert "degraded_fields" in report
    assert "actions" in report
    assert isinstance(report["degraded_fields"], list)
    assert isinstance(report["actions"], list)


# --- Message role/content validation tests ---


def test_validate_detects_missing_role():
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"content": "no role field"},
        ],
    }
    issues = agent.snapshot.validate_portable_session(state)
    codes = {i["code"] for i in issues}
    assert "MISSING_OR_INVALID_ROLE" in codes


def test_validate_detects_invalid_role_type():
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"role": 123, "content": "bad role type"},
        ],
    }
    issues = agent.snapshot.validate_portable_session(state)
    codes = {i["code"] for i in issues}
    assert "MISSING_OR_INVALID_ROLE" in codes


def test_validate_detects_missing_content():
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"role": "user"},
        ],
    }
    issues = agent.snapshot.validate_portable_session(state)
    codes = {i["code"] for i in issues}
    assert "MISSING_CONTENT" in codes


def test_validate_allows_assistant_with_tool_calls_but_no_content():
    """Assistant messages with tool_calls don't require content."""
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "c1"},
        ],
    }
    issues = agent.snapshot.validate_portable_session(state)
    codes = {i["code"] for i in issues}
    assert "MISSING_CONTENT" not in codes


def test_repair_drops_message_with_invalid_role():
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"content": "no role"},
            {"role": "user", "content": "good"},
        ],
    }
    repaired, report = agent.snapshot.repair_portable_session(state)
    assert report["applied"] is True
    assert len(repaired["history_messages"]) == 1
    assert repaired["history_messages"][0]["content"] == "good"
    issues = agent.snapshot.validate_portable_session(repaired)
    assert issues == []


def test_repair_adds_default_content_for_missing_content():
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"role": "user"},
            {"role": "assistant", "content": "reply"},
        ],
    }
    repaired, report = agent.snapshot.repair_portable_session(state)
    assert report["applied"] is True
    assert repaired["history_messages"][0]["content"] == ""
    issues = agent.snapshot.validate_portable_session(repaired)
    assert issues == []


def test_import_does_not_crash_on_missing_role_or_content():
    """Import with repair=True should handle damaged messages without KeyError."""
    agent, context = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_damaged",
        "variables": {},
        "history_messages": [
            {"content": "no role"},
            {"role": "user"},
            {"role": "user", "content": "valid"},
            {"role": "assistant", "content": "ok"},
        ],
    }
    report = agent.snapshot.import_portable_session(state, repair=True)
    assert report["applied_repairs"] is True
    assert report["issues_after"] == []
    history = context.get_history_messages(normalize=True).get_messages_as_dict()
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[0]["content"] == ""


# --- File persistence roundtrip tests ---


def test_portable_session_roundtrip_via_file(tmp_path: Path):
    source = _new_agent("portable_source")
    source_ctx = Context()
    source_ctx.set_session_id("sess_roundtrip")
    source_ctx.set_variable("plain_value", {"a": 1, "b": ["x", "y"]})
    source_ctx.set_variable("non_json_set", {"v1", "v2"})
    source_ctx.set_variable(
        KEY_HISTORY,
        [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "_tool_1", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
            {"role": "assistant", "content": "done"},
        ],
    )
    _bind_context(source, source_ctx)

    state = source.snapshot.export_portable_session()
    snapshot_file = tmp_path / "portable_session.json"
    snapshot_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    restored = _new_agent("portable_restored")
    restored_ctx = Context()
    _bind_context(restored, restored_ctx)

    loaded_state = json.loads(snapshot_file.read_text(encoding="utf-8"))
    report = restored.snapshot.import_portable_session(loaded_state, repair=True)

    assert report["issues_after"] == []
    assert restored_ctx.get_session_id() == "sess_roundtrip"
    assert restored_ctx.get_var_value("plain_value") == {"a": 1, "b": ["x", "y"]}
    assert sorted(restored_ctx.get_var_value("non_json_set")) == ["v1", "v2"]
    restored_history = restored_ctx.get_history_messages(normalize=True).get_messages_as_dict()
    assert [m["role"] for m in restored_history] == ["user", "assistant", "tool", "assistant"]


def test_portable_session_roundtrip_with_repair_via_file(tmp_path: Path):
    source = _new_agent("portable_source_bad")
    source_ctx = Context()
    source_ctx.set_session_id("sess_bad")
    source_ctx.set_variable("keep_me", 42)
    source_ctx.set_variable(
        KEY_HISTORY,
        [
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "_tool_x", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "final"},
        ],
    )
    _bind_context(source, source_ctx)

    state = source.snapshot.export_portable_session()
    snapshot_file = tmp_path / "portable_session_bad.json"
    snapshot_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    restored = _new_agent("portable_restored_bad")
    restored_ctx = Context()
    _bind_context(restored, restored_ctx)

    loaded_state = json.loads(snapshot_file.read_text(encoding="utf-8"))
    report = restored.snapshot.import_portable_session(loaded_state, repair=True)

    assert report["applied_repairs"] is True
    assert report["issues_after"] == []
    assert restored_ctx.get_session_id() == "sess_bad"
    assert restored_ctx.get_var_value("keep_me") == 42
    restored_history = restored_ctx.get_history_messages(normalize=True).get_messages_as_dict()
    assert [m["role"] for m in restored_history] == ["user", "assistant", "assistant"]
    assert all(m["role"] != "tool" for m in restored_history)


def test_import_repair_assistant_with_only_unpaired_tool_calls():
    """Repair should not leave assistant message without both content and tool_calls.

    When an assistant message has only unpaired tool_calls (no content), the repair
    flow removes tool_calls and must backfill content="" so post-repair validation
    does not report MISSING_CONTENT.
    """
    agent, context = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_unpaired",
        "variables": {},
        "history_messages": [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_no_response",
                        "type": "function",
                        "function": {"name": "_tool_x", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "done"},
        ],
    }

    report = agent.snapshot.import_portable_session(state, repair=True)
    assert report["issues_after"] == [], (
        "import should succeed after repair backfills content on stripped assistant"
    )
    assert report["applied_repairs"] is True

    history = context.get_history_messages(normalize=True).get_messages_as_dict()
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant", "assistant"]
    assert history[1].get("content") == ""


def test_import_clears_old_variables_not_in_snapshot():
    """Importing a snapshot should remove pre-existing variables absent from the snapshot."""
    agent, context = _build_agent_with_context()
    context.set_variable("old_var", "should_be_removed")
    context.set_variable("counter", 999)

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_clean",
        "variables": {"counter": 1, "new_var": "hello"},
        "history_messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"},
        ],
    }

    agent.snapshot.import_portable_session(state, repair=True)
    assert context.get_var_value("counter") == 1
    assert context.get_var_value("new_var") == "hello"
    user_vars = context.get_user_variables(include_system_context_vars=True)
    assert "old_var" not in user_vars
    assert "bad_set" not in user_vars


def test_repair_applied_true_when_only_value_degradation():
    """report.applied must be True when _json_safe_value degrades values."""
    from decimal import Decimal

    agent, _ = _build_agent_with_context()

    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_degrade_only",
        "variables": {"price": Decimal("9.99")},
        "history_messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"},
        ],
    }

    _, report = agent.snapshot.repair_portable_session(state)
    assert report["applied"] is True
    assert len(report["degraded_fields"]) > 0


def test_repair_fixes_content_none_to_empty_string():
    """repair should treat content=None the same as missing content and backfill ''."""
    agent, _ = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "s",
        "variables": {},
        "history_messages": [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "reply"},
        ],
    }
    repaired, report = agent.snapshot.repair_portable_session(state)
    assert report["applied"] is True
    assert repaired["history_messages"][0]["content"] == ""
    issues = agent.snapshot.validate_portable_session(repaired)
    assert issues == []


def test_import_handles_content_none_without_crash():
    """import with repair=True must not crash on content=None messages."""
    agent, context = _build_agent_with_context()
    state = {
        "schema_version": "portable_session.v1",
        "session_id": "sess_none_content",
        "variables": {},
        "history_messages": [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "ok"},
        ],
    }
    report = agent.snapshot.import_portable_session(state, repair=True)
    assert report["issues_after"] == []
    history = context.get_history_messages(normalize=True).get_messages_as_dict()
    assert history[0]["content"] == ""
