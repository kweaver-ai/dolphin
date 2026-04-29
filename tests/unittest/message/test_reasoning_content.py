"""Tests for issue #63: reasoning_content must be persisted on assistant
tool-call messages so reasoning models (DeepSeek V4, etc.) accept the next
turn's payload.
"""

import unittest

from dolphin.core.common.enums import MessageRole, Messages, SingleMessage
from dolphin.core.llm.message_sanitizer import sanitize_openai_messages


class TestSingleMessageReasoningContent(unittest.TestCase):
    def test_to_dict_omits_reasoning_when_absent(self):
        msg = SingleMessage(role=MessageRole.ASSISTANT, content="hi")
        self.assertNotIn("reasoning_content", msg.to_dict())

    def test_to_dict_omits_reasoning_when_empty_string(self):
        msg = SingleMessage(
            role=MessageRole.ASSISTANT, content="hi", reasoning_content=""
        )
        self.assertNotIn("reasoning_content", msg.to_dict())

    def test_to_dict_includes_reasoning_when_present(self):
        msg = SingleMessage(
            role=MessageRole.ASSISTANT,
            content="hi",
            reasoning_content="思考过程",
        )
        self.assertEqual(msg.to_dict()["reasoning_content"], "思考过程")

    def test_copy_preserves_reasoning_content(self):
        msg = SingleMessage(
            role=MessageRole.ASSISTANT,
            content="hi",
            reasoning_content="思考过程",
        )
        copied = msg.copy()
        self.assertEqual(copied.reasoning_content, "思考过程")
        self.assertEqual(copied.to_dict()["reasoning_content"], "思考过程")


class TestMessagesAddToolCallReasoning(unittest.TestCase):
    def test_add_tool_call_message_persists_reasoning_content(self):
        msgs = Messages()
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "sql", "arguments": "{}"},
            }
        ]
        msgs.add_tool_call_message(
            content="",
            tool_calls=tool_calls,
            reasoning_content="reasoning trace",
        )

        dumped = msgs.get_messages_as_dict()
        self.assertEqual(len(dumped), 1)
        msg = dumped[0]
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["tool_calls"], tool_calls)
        self.assertEqual(msg["reasoning_content"], "reasoning trace")

    def test_add_tool_call_message_without_reasoning_omits_field(self):
        msgs = Messages()
        msgs.add_tool_call_message(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "sql", "arguments": "{}"},
                }
            ],
        )
        msg = msgs.get_messages_as_dict()[0]
        self.assertNotIn("reasoning_content", msg)


def test_extend_plain_messages_preserves_reasoning_content():
    messages = Messages()
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "sql", "arguments": "{}"},
        }
    ]
    plain_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": tool_calls,
            "reasoning_content": "reasoning trace",
        }
    ]

    messages.extend_plain_messages(plain_messages)

    restored = messages.get_messages_as_dict()[0]
    assert restored["tool_calls"] == tool_calls
    assert restored["reasoning_content"] == "reasoning trace"


class TestSanitizerPreservesReasoningContent(unittest.TestCase):
    """Regression guard: sanitizer must not drop or overwrite a real
    reasoning_content that the streaming layer captured.
    """

    def test_real_reasoning_content_survives_sanitize(self):
        messages = [
            {"role": "user", "content": "list users"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "sql", "arguments": "{}"},
                    }
                ],
                "reasoning_content": "I should call SQL to list users.",
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "[u1, u2]"},
        ]

        sanitized, downgraded = sanitize_openai_messages(messages)
        self.assertEqual(downgraded, 0)
        # Locate the assistant tool-call message
        asst = next(m for m in sanitized if m.get("role") == "assistant")
        self.assertEqual(
            asst["reasoning_content"], "I should call SQL to list users."
        )

    def test_real_reasoning_content_not_clobbered_by_whitelist_path(self):
        """When ensure_reasoning_content=True (whitelist matched a model), an
        existing real reasoning_content must NOT be replaced with the ' '
        placeholder.
        """
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "sql", "arguments": "{}"},
                    }
                ],
                "reasoning_content": "real trace",
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
        sanitized, _ = sanitize_openai_messages(
            messages, ensure_reasoning_content=True
        )
        asst = next(m for m in sanitized if m.get("role") == "assistant")
        self.assertEqual(asst["reasoning_content"], "real trace")


if __name__ == "__main__":
    unittest.main()
