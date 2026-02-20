#!/usr/bin/env python3
"""
Unit tests for HistoryProjector – full-storage + budget projection.

Covers:
1. Empty history
2. Old-format (user/assistant text only) – passthrough
3. History with tool chains – recent turns kept, old turns trimmed
4. tool_calls + tool response pairs never split
5. Pinned messages preserved regardless of turn age
6. _update_history_and_cleanup stores tool chains
7. get_history_messages(projected=True) end-to-end
8. Backward compatibility with old sessions (no tool_calls in history)
"""

import unittest
from datetime import datetime
from unittest.mock import Mock, MagicMock, PropertyMock

from dolphin.core.common.constants import KEY_HISTORY
from dolphin.core.common.enums import Messages, MessageRole, SingleMessage
from dolphin.core.context.context import Context
from dolphin.core.context.history_projector import (
    HistoryProjector,
    ProjectionConfig,
    _parse_turns,
    _is_pinned,
)


# ─── helpers ───────────────────────────────────────────────────────────────

def _msg(role: str, content: str, **kwargs) -> dict:
    """Shorthand for a plain-dict message."""
    d = {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
    d.update(kwargs)
    return d


def _user(content: str) -> dict:
    return _msg("user", content)


def _assistant(content: str) -> dict:
    return _msg("assistant", content)


def _assistant_tc(content: str, tool_calls: list) -> dict:
    return _msg("assistant", content, tool_calls=tool_calls)


def _tool(content: str, tool_call_id: str) -> dict:
    return _msg("tool", content, tool_call_id=tool_call_id)


def _pinned(content: str) -> dict:
    return _msg("assistant", content, metadata={"pinned": True, "source": "tool"})


def _messages_from_dicts(dicts: list) -> Messages:
    m = Messages()
    m.extend_plain_messages(dicts)
    return m


SAMPLE_TC = [{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]


# ─── Test: Empty history ──────────────────────────────────────────────────

class TestEmptyHistory(unittest.TestCase):
    def test_empty_messages_returns_empty(self):
        proj = HistoryProjector()
        result = proj.project(Messages())
        self.assertEqual(len(result.get_messages()), 0)


# ─── Test: Old format passthrough ─────────────────────────────────────────

class TestOldFormatPassthrough(unittest.TestCase):
    def test_user_assistant_only_passthrough(self):
        """History with only user/assistant text should pass through unchanged."""
        history = _messages_from_dicts([
            _user("Q1"), _assistant("A1"),
            _user("Q2"), _assistant("A2"),
            _user("Q3"), _assistant("A3"),
        ])
        proj = HistoryProjector(ProjectionConfig(recent_turns=2))
        result = proj.project(history)

        msgs = result.get_messages()
        # Turn 1 (old) should still have user+assistant (no tool chain to trim)
        # Turn 2,3 (recent) kept fully
        self.assertEqual(len(msgs), 6)
        self.assertEqual(msgs[0].content, "Q1")
        self.assertEqual(msgs[1].content, "A1")


# ─── Test: Tool chain trimming ────────────────────────────────────────────

class TestToolChainTrimming(unittest.TestCase):
    def _build_history(self):
        """Build 3-turn history: each turn has user + tool_call + tool_resp + assistant."""
        turns = []
        for i in range(1, 4):
            tc = [{"id": f"call_{i}", "type": "function",
                   "function": {"name": f"tool_{i}", "arguments": "{}"}}]
            turns.extend([
                _user(f"Q{i}"),
                _assistant_tc(f"thinking_{i}", tc),
                _tool(f"result_{i}", f"call_{i}"),
                _assistant(f"A{i}"),
            ])
        return _messages_from_dicts(turns)

    def test_recent_turns_keep_tool_chain(self):
        """With recent_turns=2, turns 2+3 should keep their tool chains."""
        history = self._build_history()
        proj = HistoryProjector(ProjectionConfig(recent_turns=2))
        result = proj.project(history)

        msgs = result.get_messages()
        # Turn 1 (old): user + assistant_final = 2 messages (tool chain trimmed)
        # Turn 2 (recent): user + tc + tool + assistant = 4 messages
        # Turn 3 (recent): user + tc + tool + assistant = 4 messages
        self.assertEqual(len(msgs), 10)

        # Verify turn 1 is trimmed
        self.assertEqual(msgs[0].role, MessageRole.USER)
        self.assertEqual(msgs[0].content, "Q1")
        self.assertEqual(msgs[1].role, MessageRole.ASSISTANT)
        self.assertEqual(msgs[1].content, "A1")

        # Verify turn 2 is full
        self.assertEqual(msgs[2].content, "Q2")
        self.assertTrue(msgs[3].has_tool_calls())
        self.assertEqual(msgs[4].role, MessageRole.TOOL)
        self.assertEqual(msgs[5].content, "A2")

    def test_all_recent_no_trimming(self):
        """If recent_turns >= total turns, nothing is trimmed."""
        history = self._build_history()
        proj = HistoryProjector(ProjectionConfig(recent_turns=5))
        result = proj.project(history)
        self.assertEqual(len(result.get_messages()), 12)

    def test_old_turn_tool_chain_dropped(self):
        """Old turns should not contain tool_calls or tool messages."""
        history = self._build_history()
        proj = HistoryProjector(ProjectionConfig(recent_turns=1))
        result = proj.project(history)

        msgs = result.get_messages()
        # Turns 1,2 are old → 2 msgs each = 4
        # Turn 3 is recent → 4 msgs
        self.assertEqual(len(msgs), 8)

        # Old turns: no TOOL role and no tool_calls
        old_msgs = msgs[:4]  # first 2 turns trimmed
        for m in old_msgs:
            self.assertNotEqual(m.role, MessageRole.TOOL)
            self.assertFalse(m.has_tool_calls())


# ─── Test: tool_calls + tool pairs never split ────────────────────────────

class TestToolPairIntegrity(unittest.TestCase):
    def test_recent_turn_keeps_pairs(self):
        """In a recent turn, assistant(tool_calls) is always followed by tool(response)."""
        tc = [{"id": "call_x", "type": "function",
               "function": {"name": "search", "arguments": "{}"}}]
        history = _messages_from_dicts([
            _user("Q"),
            _assistant_tc("", tc),
            _tool("found it", "call_x"),
            _assistant("Answer"),
        ])
        proj = HistoryProjector(ProjectionConfig(recent_turns=1))
        result = proj.project(history)
        msgs = result.get_messages()

        # Should keep all 4 messages
        self.assertEqual(len(msgs), 4)
        # The assistant-with-tool-calls must be immediately before the tool response
        self.assertTrue(msgs[1].has_tool_calls())
        self.assertEqual(msgs[2].role, MessageRole.TOOL)
        self.assertEqual(msgs[2].tool_call_id, "call_x")


# ─── Test: Pinned messages always preserved ───────────────────────────────

class TestPinnedPreservation(unittest.TestCase):
    def test_pinned_in_old_turn_preserved(self):
        """Pinned messages survive trimming even in old turns."""
        history = _messages_from_dicts([
            # Turn 1 (will be old)
            _user("Q1"),
            _assistant_tc("", SAMPLE_TC),
            _tool("res", "call_1"),
            _pinned("important data"),
            _assistant("A1"),
            # Turn 2 (recent)
            _user("Q2"),
            _assistant("A2"),
        ])
        proj = HistoryProjector(ProjectionConfig(recent_turns=1))
        result = proj.project(history)
        msgs = result.get_messages()

        # Old turn: user + pinned + assistant_final = 3
        # Recent turn: user + assistant = 2
        self.assertEqual(len(msgs), 5)

        contents = [m.content for m in msgs]
        self.assertIn("important data", contents)
        self.assertNotIn("res", contents)  # tool response trimmed

    def test_pinned_in_recent_turn_preserved(self):
        """Pinned messages in recent turns are preserved (they'd be kept anyway)."""
        history = _messages_from_dicts([
            _user("Q1"),
            _pinned("pinned data"),
            _assistant("A1"),
        ])
        proj = HistoryProjector(ProjectionConfig(recent_turns=1))
        result = proj.project(history)
        msgs = result.get_messages()
        contents = [m.content for m in msgs]
        self.assertIn("pinned data", contents)


# ─── Test: _is_pinned helper ─────────────────────────────────────────────

class TestIsPinned(unittest.TestCase):
    def test_pinned_true(self):
        msg = SingleMessage(
            role=MessageRole.ASSISTANT,
            content="data",
            metadata={"pinned": True},
        )
        self.assertTrue(_is_pinned(msg))

    def test_not_pinned(self):
        msg = SingleMessage(
            role=MessageRole.ASSISTANT,
            content="data",
            metadata={},
        )
        self.assertFalse(_is_pinned(msg))

    def test_no_metadata(self):
        msg = SingleMessage(role=MessageRole.ASSISTANT, content="data")
        self.assertFalse(_is_pinned(msg))


# ─── Test: _parse_turns ──────────────────────────────────────────────────

class TestParseTurns(unittest.TestCase):
    def test_single_turn(self):
        history = _messages_from_dicts([
            _user("Q"), _assistant("A"),
        ])
        turns = _parse_turns(history)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].user.content, "Q")
        self.assertEqual(turns[0].assistant_final.content, "A")

    def test_multiple_turns(self):
        history = _messages_from_dicts([
            _user("Q1"), _assistant("A1"),
            _user("Q2"), _assistant("A2"),
        ])
        turns = _parse_turns(history)
        self.assertEqual(len(turns), 2)

    def test_turn_with_tool_chain(self):
        tc = [{"id": "c1", "type": "function",
               "function": {"name": "t", "arguments": "{}"}}]
        history = _messages_from_dicts([
            _user("Q"),
            _assistant_tc("thinking", tc),
            _tool("result", "c1"),
            _assistant("A"),
        ])
        turns = _parse_turns(history)
        self.assertEqual(len(turns), 1)
        self.assertEqual(len(turns[0].tool_chain), 2)
        self.assertEqual(turns[0].assistant_final.content, "A")

    def test_empty_history(self):
        turns = _parse_turns(Messages())
        self.assertEqual(len(turns), 0)


# ─── Test: _update_history_and_cleanup stores tool chains ─────────────────

class TestUpdateHistoryStoresToolChains(unittest.TestCase):
    def test_tool_chain_persisted_to_history(self):
        """_update_history_and_cleanup should extract tool chains from scratchpad."""
        from dolphin.core.code_block.basic_code_block import BasicCodeBlock
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        ctx = Context()
        ctx.set_variable(KEY_HISTORY, [])

        # Build scratchpad with tool chain messages
        scratchpad_msgs = Messages()
        tc = [{"id": "call_abc", "type": "function",
               "function": {"name": "web_search", "arguments": '{"q": "test"}'}}]
        scratchpad_msgs.add_tool_call_message(content="let me search", tool_calls=tc)
        scratchpad_msgs.add_tool_response_message(content="search results here", tool_call_id="call_abc")

        # Set up scratchpad bucket in context_manager
        ctx.context_manager.add_bucket(
            BuildInBucket.SCRATCHPAD.value, scratchpad_msgs
        )

        # Create a mock block with recorder
        block = BasicCodeBlock.__new__(BasicCodeBlock)
        block.context = ctx
        block.content = "User question"
        block.recorder = Mock()
        block.recorder.get_answer.return_value = "Final answer"

        block._save_trajectory = Mock()

        block._update_history_and_cleanup()

        history = ctx.get_var_value(KEY_HISTORY)
        self.assertIsInstance(history, list)

        # Should contain: user + assistant(tool_calls) + tool(response) + assistant_final
        roles = [item["role"] for item in history]
        self.assertIn("tool", roles)

        # Find the tool_calls message
        tc_msgs = [item for item in history if item.get("tool_calls")]
        self.assertEqual(len(tc_msgs), 1)
        self.assertEqual(tc_msgs[0]["tool_calls"][0]["id"], "call_abc")

        # Find the tool response
        tool_msgs = [item for item in history if item["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_abc")

    def test_pinned_tool_response_survives_projection_for_old_turn(self):
        """Pinned content from tool responses should survive projection trimming."""
        from dolphin.core.code_block.basic_code_block import BasicCodeBlock
        from dolphin.core.context_engineer.config.settings import BuildInBucket
        from dolphin.core.common.constants import PIN_MARKER

        ctx = Context()
        ctx.set_variable(KEY_HISTORY, [])

        block = BasicCodeBlock.__new__(BasicCodeBlock)
        block.context = ctx
        block.recorder = Mock()
        block._save_trajectory = Mock()

        # Build 4 turns so turn-1 becomes an old turn when projected (recent_turns=3).
        for i in range(1, 5):
            scratchpad_msgs = Messages()
            tc = [{
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"tool_{i}", "arguments": "{}"},
            }]
            scratchpad_msgs.add_tool_call_message(content="", tool_calls=tc)
            tool_content = f"{PIN_MARKER} keep_me" if i == 1 else f"result_{i}"
            scratchpad_msgs.add_tool_response_message(
                content=tool_content, tool_call_id=f"call_{i}"
            )
            if ctx.context_manager.has_bucket(BuildInBucket.SCRATCHPAD.value):
                ctx.context_manager.replace_bucket_content(
                    BuildInBucket.SCRATCHPAD.value, scratchpad_msgs
                )
            else:
                ctx.context_manager.add_bucket(
                    BuildInBucket.SCRATCHPAD.value, scratchpad_msgs
                )

            block.content = f"Q{i}"
            block.recorder.get_answer.return_value = f"A{i}"
            block._update_history_and_cleanup()

        projected = ctx.get_history_messages(projected=True)
        contents = [m.content for m in projected.get_messages()]
        self.assertIn("keep_me", contents)

    def test_no_tool_chain_duplication_when_scratchpad_missing(self):
        """Fallback extraction from merged messages should not re-append old tool chains."""
        from dolphin.core.code_block.basic_code_block import BasicCodeBlock

        ctx = Context()
        existing_history = [
            {
                "role": "user",
                "content": "Q0",
                "timestamp": datetime.now().isoformat(),
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c0",
                        "type": "function",
                        "function": {"name": "tool_0", "arguments": "{}"},
                    }
                ],
                "timestamp": datetime.now().isoformat(),
            },
            {
                "role": "tool",
                "content": "res0",
                "tool_call_id": "c0",
                "timestamp": datetime.now().isoformat(),
            },
            {
                "role": "assistant",
                "content": "A0",
                "timestamp": datetime.now().isoformat(),
            },
        ]
        ctx.set_variable(KEY_HISTORY, existing_history)
        ctx.set_history_bucket(ctx.get_history_messages())

        block = BasicCodeBlock.__new__(BasicCodeBlock)
        block.context = ctx
        block.content = "Q1"
        block.recorder = Mock()
        block.recorder.get_answer.return_value = "A1"
        block._save_trajectory = Mock()
        block._update_history_and_cleanup()

        history = ctx.get_history_messages(normalize=False)
        c0_call_count = sum(
            1
            for item in history
            if isinstance(item, dict)
            and item.get("tool_calls")
            and item["tool_calls"][0].get("id") == "c0"
        )
        self.assertEqual(c0_call_count, 1)

    def test_pinned_content_should_not_be_duplicated_semantically(self):
        """Pinned tool output should not appear twice with equivalent semantics."""
        from dolphin.core.code_block.basic_code_block import BasicCodeBlock
        from dolphin.core.context_engineer.config.settings import BuildInBucket
        from dolphin.core.common.constants import PIN_MARKER

        ctx = Context()
        ctx.set_variable(KEY_HISTORY, [])

        scratchpad = Messages()
        scratchpad.add_tool_call_message(
            content="",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "tool_1", "arguments": "{}"},
            }],
        )
        scratchpad.add_tool_response_message(
            content=f"{PIN_MARKER} important_result",
            tool_call_id="call_1",
        )
        ctx.context_manager.add_bucket(BuildInBucket.SCRATCHPAD.value, scratchpad)

        block = BasicCodeBlock.__new__(BasicCodeBlock)
        block.context = ctx
        block.content = "Q"
        block.recorder = Mock()
        block.recorder.get_answer.return_value = "A_final"
        block._save_trajectory = Mock()
        block._update_history_and_cleanup()

        history = ctx.get_history_messages(normalize=False)
        semantic_hits = [
            msg for msg in history
            if isinstance(msg, dict) and "important_result" in (msg.get("content") or "")
        ]
        self.assertEqual(len(semantic_hits), 1)

    def test_pinned_content_should_keep_original_temporal_position(self):
        """Pinned content should stay near its original tool response position."""
        from dolphin.core.code_block.basic_code_block import BasicCodeBlock
        from dolphin.core.context_engineer.config.settings import BuildInBucket
        from dolphin.core.common.constants import PIN_MARKER

        ctx = Context()
        ctx.set_variable(KEY_HISTORY, [])

        scratchpad = Messages()
        scratchpad.add_tool_call_message(
            content="",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "tool_1", "arguments": "{}"},
            }],
        )
        scratchpad.add_tool_response_message(
            content=f"{PIN_MARKER} pin_a",
            tool_call_id="call_1",
        )
        scratchpad.add_tool_call_message(
            content="",
            tool_calls=[{
                "id": "call_2",
                "type": "function",
                "function": {"name": "tool_2", "arguments": "{}"},
            }],
        )
        scratchpad.add_tool_response_message(
            content="normal_b",
            tool_call_id="call_2",
        )
        ctx.context_manager.add_bucket(BuildInBucket.SCRATCHPAD.value, scratchpad)

        block = BasicCodeBlock.__new__(BasicCodeBlock)
        block.context = ctx
        block.content = "Q"
        block.recorder = Mock()
        block.recorder.get_answer.return_value = "A_final"
        block._save_trajectory = Mock()
        block._update_history_and_cleanup()

        history = ctx.get_history_messages(normalize=False)
        pin_tool_index = next(
            i for i, msg in enumerate(history)
            if isinstance(msg, dict) and msg.get("role") == "tool" and "pin_a" in (msg.get("content") or "")
        )
        normal_tool_index = next(
            i for i, msg in enumerate(history)
            if isinstance(msg, dict)
            and msg.get("role") == "tool"
            and msg.get("content") == "normal_b"
        )
        pinned_assistant = [
            msg for msg in history
            if isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and (msg.get("metadata") or {}).get("pinned") is True
            and msg.get("content") == "pin_a"
        ]
        self.assertEqual(len(pinned_assistant), 0)
        self.assertLess(pin_tool_index, normal_tool_index)


# ─── Test: get_history_messages(projected=True) end-to-end ────────────────

class TestGetHistoryProjected(unittest.TestCase):
    def test_projected_trims_old_turns(self):
        """get_history_messages(projected=True) should trim old tool chains."""
        ctx = Context()

        # Build a 3-turn history with tool chains
        history_list = []
        for i in range(1, 4):
            tc = [{"id": f"call_{i}", "type": "function",
                   "function": {"name": f"t{i}", "arguments": "{}"}}]
            history_list.extend([
                _user(f"Q{i}"),
                _assistant_tc(f"think_{i}", tc),
                _tool(f"res_{i}", f"call_{i}"),
                _assistant(f"A{i}"),
            ])
        ctx.set_variable(KEY_HISTORY, history_list)

        # Without projection: all 12 messages
        full = ctx.get_history_messages(projected=False, normalize=True)
        self.assertEqual(len(full.get_messages()), 12)

        # With projection (default recent_turns=3): all kept
        projected = ctx.get_history_messages(projected=True)
        self.assertEqual(len(projected.get_messages()), 12)

    def test_projected_with_more_turns(self):
        """With 5 turns and recent_turns=3, first 2 turns are trimmed."""
        ctx = Context()
        history_list = []
        for i in range(1, 6):
            tc = [{"id": f"call_{i}", "type": "function",
                   "function": {"name": f"t{i}", "arguments": "{}"}}]
            history_list.extend([
                _user(f"Q{i}"),
                _assistant_tc(f"think_{i}", tc),
                _tool(f"res_{i}", f"call_{i}"),
                _assistant(f"A{i}"),
            ])
        ctx.set_variable(KEY_HISTORY, history_list)

        projected = ctx.get_history_messages(projected=True)
        msgs = projected.get_messages()
        # Old turns (1,2): 2 msgs each = 4
        # Recent turns (3,4,5): 4 msgs each = 12
        self.assertEqual(len(msgs), 16)

    def test_projected_false_returns_full(self):
        """projected=False should not trim anything."""
        ctx = Context()
        history_list = [_user("Q1"), _assistant("A1")]
        ctx.set_variable(KEY_HISTORY, history_list)

        result = ctx.get_history_messages(projected=False)
        self.assertEqual(len(result.get_messages()), 2)


# ─── Test: Backward compatibility with old sessions ───────────────────────

class TestBackwardCompatibility(unittest.TestCase):
    def test_old_session_no_tool_calls(self):
        """Old sessions have only user/assistant in history – projection is a no-op."""
        ctx = Context()
        history_list = [
            _user("old Q1"), _assistant("old A1"),
            _user("old Q2"), _assistant("old A2"),
        ]
        ctx.set_variable(KEY_HISTORY, history_list)

        projected = ctx.get_history_messages(projected=True)
        msgs = projected.get_messages()
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[0].content, "old Q1")
        self.assertEqual(msgs[3].content, "old A2")

    def test_messages_object_history(self):
        """History stored as Messages object should also work with projection."""
        ctx = Context()
        history = Messages()
        history.add_message(role=MessageRole.USER, content="Q1")
        history.add_message(role=MessageRole.ASSISTANT, content="A1")
        ctx.set_variable(KEY_HISTORY, history)

        projected = ctx.get_history_messages(projected=True)
        self.assertEqual(len(projected.get_messages()), 2)

    def test_none_history(self):
        """None history should return empty Messages."""
        ctx = Context()
        result = ctx.get_history_messages(projected=True)
        self.assertEqual(len(result.get_messages()), 0)


# ─── Test: ProjectionConfig ──────────────────────────────────────────────

class TestProjectionConfig(unittest.TestCase):
    def test_default_recent_turns(self):
        config = ProjectionConfig()
        self.assertEqual(config.recent_turns, 3)

    def test_custom_recent_turns(self):
        config = ProjectionConfig(recent_turns=5)
        self.assertEqual(config.recent_turns, 5)


if __name__ == "__main__":
    unittest.main()
