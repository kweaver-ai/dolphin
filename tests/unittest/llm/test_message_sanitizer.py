#!/usr/bin/env python3
"""
Unit tests for OpenAI-compatible message sanitization.

Focus: tool_calls / tool_call_id sequencing and PIN_MARKER handling.
"""

import unittest

from dolphin.core.common.constants import PIN_MARKER
from dolphin.core.llm.message_sanitizer import sanitize_openai_messages, sanitize_and_log


class TestMessageSanitizer(unittest.TestCase):
    def test_pinned_tool_message_with_matching_tool_call_id_is_not_downgraded(self):
        """Pinned tool output that matches a preceding tool_calls id must remain role='tool'."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "_load_resource_skill", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": f"{PIN_MARKER}doc..."},
            {"role": "assistant", "content": "ok"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 0)
        self.assertEqual(sanitized[3]["role"], "tool")
        self.assertEqual(sanitized[3]["tool_call_id"], "call_1")
        self.assertTrue(sanitized[3]["content"].startswith(PIN_MARKER))

    def test_pinned_tool_message_without_tool_calls_is_downgraded(self):
        """Pinned tool output without any preceding tool_calls should be downgraded."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": f"{PIN_MARKER}doc..."},
            {"role": "user", "content": "hi"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 1)
        self.assertEqual(sanitized[1]["role"], "assistant")  # pinned_downgrade_role default
        self.assertNotEqual(sanitized[1].get("role"), "tool")

    def test_pinned_tool_message_with_mismatched_tool_call_id_is_downgraded(self):
        """Pinned tool output whose tool_call_id is not declared should be downgraded."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_expected",
                        "type": "function",
                        "function": {"name": "_bash", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_other",
                "content": f"{PIN_MARKER}doc...",
            },
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        # downgraded >= 1: tool response downgraded + assistant tool_calls stripped
        self.assertGreaterEqual(downgraded, 1)
        self.assertEqual(sanitized[-1]["role"], "assistant")

    def test_sanitize_and_log_emits_warning_when_downgraded(self):
        """sanitize_and_log should call warning_fn when it downgrades messages."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": f"{PIN_MARKER}doc..."},
        ]

        warnings = []

        def _warn(msg: str):
            warnings.append(msg)

        sanitized = sanitize_and_log(messages, _warn)
        self.assertEqual(len(warnings), 1)
        self.assertIn("downgraded for OpenAI compatibility", warnings[0])
        self.assertEqual(sanitized[1]["role"], "assistant")


class TestOrphanAssistantToolCalls(unittest.TestCase):
    """Tests for orphan assistant tool_calls (tool_calls without matching tool responses)."""

    def test_orphan_assistant_tool_calls_no_response(self):
        """assistant has tool_calls but no tool response follows.

        Sanitizer must strip orphan tool_calls to prevent DashScope 400 errors.
        """
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_orphan",
                        "type": "function",
                        "function": {"name": "_search", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertGreater(downgraded, 0)
        # tool_calls should be stripped from the assistant message
        self.assertNotIn("tool_calls", sanitized[1])

    def test_orphan_assistant_tool_calls_partial_response(self):
        """2 tool_calls declared but only 1 tool response: orphan call_b must be stripped."""
        messages = [
            {"role": "user", "content": "hi"},
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
            {"role": "tool", "tool_call_id": "call_a", "content": "result_a"},
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertGreater(downgraded, 0)
        # Only call_a (which has a response) should remain
        tool_call_ids = [tc["id"] for tc in sanitized[1]["tool_calls"]]
        self.assertIn("call_a", tool_call_ids)
        self.assertNotIn("call_b", tool_call_ids)

    def test_valid_tool_chain_not_downgraded(self):
        """Complete tool chain (assistant→tool_calls→tool response) must not be altered."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "_search", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "found it"},
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 0)
        self.assertEqual(len(sanitized), 4)
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[2]["tool_call_id"], "call_1")

    def test_multiple_assistant_tool_calls_rounds(self):
        """Multiple rounds of tool_calls each paired correctly."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_r1", "type": "function", "function": {"name": "_t1", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_r1", "content": "r1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_r2", "type": "function", "function": {"name": "_t2", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_r2", "content": "r2"},
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 0)
        self.assertEqual(len(sanitized), 6)
        # Both tool responses remain as role=tool
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[4]["role"], "tool")

    def test_duplicate_tool_call_id_across_rounds_only_first_matched(self):
        """Same tool_call_id reused in two rounds; only the first has a response.

        The second round's tool_calls must be stripped even though the id matches
        a response from the first round.  Per-occurrence matching is required.
        """
        messages = [
            {"role": "user", "content": "hi"},
            # Round 1: call_dup has response
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_dup", "type": "function",
                     "function": {"name": "_t1", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_dup", "content": "result_1"},
            # Round 2: same id, but NO response
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_dup", "type": "function",
                     "function": {"name": "_t2", "arguments": "{}"}},
                ],
            },
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertGreater(downgraded, 0)
        # Round 1 assistant still has its tool_calls (matched)
        self.assertIn("tool_calls", sanitized[1])
        # Round 2 assistant must have tool_calls stripped (no response)
        round2 = sanitized[3]
        self.assertFalse(
            round2.get("tool_calls"),
            "Round 2 with duplicate id but no response must be stripped",
        )

    def test_same_id_in_single_assistant_two_calls_one_response(self):
        """Same tool_call_id declared twice in one assistant, only one response exists.

        Only one of the two declarations should survive.
        """
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_same", "type": "function",
                     "function": {"name": "_a", "arguments": "{}"}},
                    {"id": "call_same", "type": "function",
                     "function": {"name": "_b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_same", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertGreater(downgraded, 0)
        kept_tcs = sanitized[1].get("tool_calls", [])
        # Only one declaration should be kept (matching the single response)
        self.assertEqual(len(kept_tcs), 1)


    def test_cross_round_same_id_response_belongs_to_later_round(self):
        """Same tool_call_id in two rounds, response only after round 2.

        Round 1 has no response -> strip its tool_calls.
        Round 2 has a response  -> keep its tool_calls.

        The previous global-count approach incorrectly assigned the budget to
        round 1 (first-come), leaving the sequence as:
            assistant(tool_calls) -> assistant -> tool
        which violates the OpenAI tool-call ordering constraint.
        """
        messages = [
            {"role": "user", "content": "hi"},
            # Round 1: declares dup, NO response follows before round 2
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_dup", "type": "function",
                     "function": {"name": "_t1", "arguments": "{}"}},
                ],
            },
            # Round 2: declares same dup
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_dup", "type": "function",
                     "function": {"name": "_t2", "arguments": "{}"}},
                ],
            },
            # Response belongs to round 2 (immediately follows it)
            {"role": "tool", "tool_call_id": "call_dup", "content": "result_2"},
            {"role": "assistant", "content": "done"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertGreater(downgraded, 0)

        # Round 1 (index 1): tool_calls must be STRIPPED (no response)
        round1 = sanitized[1]
        self.assertFalse(
            round1.get("tool_calls"),
            "Round 1 with no response must have tool_calls stripped",
        )

        # Round 2 (index 2): tool_calls must be KEPT (response follows)
        round2 = sanitized[2]
        self.assertTrue(
            round2.get("tool_calls"),
            "Round 2 whose response follows must keep tool_calls",
        )
        self.assertEqual(round2["tool_calls"][0]["id"], "call_dup")


class TestOrphanToolResponses(unittest.TestCase):
    """Tests for orphan tool responses (role=tool without matching assistant tool_calls)."""

    def test_orphan_tool_response_no_preceding_tool_calls(self):
        """Non-pinned orphan tool response (no preceding tool_calls) is downgraded."""
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "call_ghost", "content": "result"},
            {"role": "assistant", "content": "ok"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 1)
        self.assertEqual(sanitized[1]["role"], "user")
        self.assertIn("result", sanitized[1]["content"])

    def test_orphan_tool_response_mismatched_id(self):
        """Tool response with tool_call_id not matching any declared tool_calls is downgraded."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_real", "type": "function", "function": {"name": "_t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_real", "content": "ok"},
            {"role": "tool", "tool_call_id": "call_fake", "content": "orphan"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 1)
        # call_real kept as tool, call_fake downgraded
        tool_msgs = [m for m in sanitized if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_real")

    def test_orphan_tool_response_missing_id_field(self):
        """Tool response without tool_call_id field is downgraded."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_x", "type": "function", "function": {"name": "_t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "content": "no id field"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        # downgraded >= 1: tool response downgraded + assistant tool_calls stripped
        self.assertGreaterEqual(downgraded, 1)
        self.assertNotEqual(sanitized[-1]["role"], "tool")


class TestSanitizerEdgeCases(unittest.TestCase):
    """Edge cases and additional parameter tests."""

    def test_empty_messages(self):
        """Empty message list returns empty list with 0 downgrades."""
        sanitized, downgraded = sanitize_openai_messages([])
        self.assertEqual(sanitized, [])
        self.assertEqual(downgraded, 0)

    def test_ensure_reasoning_content_adds_field(self):
        """ensure_reasoning_content=True adds reasoning_content to assistant tool_calls messages."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "_t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]

        sanitized, _ = sanitize_openai_messages(messages, ensure_reasoning_content=True)
        assistant_with_tc = sanitized[1]
        self.assertIn("reasoning_content", assistant_with_tc)
        self.assertEqual(assistant_with_tc["reasoning_content"], " ")

    def test_ensure_reasoning_content_preserves_existing(self):
        """ensure_reasoning_content=True does not overwrite existing reasoning_content."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "my reasoning",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "_t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]

        sanitized, _ = sanitize_openai_messages(messages, ensure_reasoning_content=True)
        self.assertEqual(sanitized[1]["reasoning_content"], "my reasoning")

    def test_messages_without_tool_calls_pass_through(self):
        """Pure text messages (no tool_calls, no tool responses) are unaffected."""
        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "bye"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 0)
        self.assertEqual(sanitized, messages)

