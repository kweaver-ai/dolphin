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
        self.assertEqual(downgraded, 1)
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

