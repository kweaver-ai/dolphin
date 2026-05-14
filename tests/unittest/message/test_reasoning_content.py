"""Tests for issue #63: reasoning_content must be persisted on assistant
tool-call messages so reasoning models (DeepSeek V4, etc.) accept the next
turn's payload.

Follow-up fix: empty-string reasoning_content must also be emitted.
DeepSeek thinking mode can return reasoning_content: "" (empty string) when
the model decided not to think explicitly but still activated thinking mode.
The field must be echoed back on subsequent turns even when empty, otherwise
DeepSeek returns: "The `reasoning_content` in the thinking mode must be
passed back to the API."

Design contract:
  - None  → LLM never emitted reasoning_content (non-thinking model), omit from dict
  - ""    → LLM emitted reasoning_content: "" (thinking mode, empty thinking),
            INCLUDE in dict so it can be echoed back
  - str   → non-empty thinking trace, include as usual
"""

import asyncio
import unittest

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.enums import MessageRole, Messages, SingleMessage
from dolphin.core.llm.message_sanitizer import sanitize_openai_messages


class _FakeContext:
    def has_skillkit_hook(self):
        return False

    def set_skillkit_hook(self, skillkit_hook):
        self.skillkit_hook = skillkit_hook

    def set_last_model_name(self, model):
        self.last_model_name = model

    def check_user_interrupt(self):
        return None

    def is_cli_mode(self):
        return False

    def is_verbose(self):
        return False


class _FakeLLMClient:
    async def mf_chat_stream(self, **kwargs):
        tool_calls_data = {
            0: {
                "id": "call_late_reasoning",
                "name": "_date",
                "arguments": [],
            }
        }
        yield {
            "content": "",
            "reasoning_content": None,
            "tool_calls_data": tool_calls_data,
            "func_name": "_date",
        }

        tool_calls_data = {
            0: {
                "id": "call_late_reasoning",
                "name": "_date",
                "arguments": ["{}"],
            }
        }
        yield {
            "content": "",
            "reasoning_content": None,
            "tool_calls_data": tool_calls_data,
            "func_name": "_date",
            "func_args": ["{}"],
        }

        # Some RLM streams can emit reasoning after arguments have become
        # parseable but before finish_reason=tool_calls.  The early-stop path
        # must keep consuming until this chunk is seen.
        yield {
            "content": "",
            "reasoning_content": "",
            "tool_calls_data": tool_calls_data,
            "func_name": "_date",
            "func_args": ["{}"],
        }

        yield {
            "content": "",
            "reasoning_content": "",
            "tool_calls_data": tool_calls_data,
            "func_name": "_date",
            "func_args": ["{}"],
            "finish_reason": "tool_calls",
        }


class TestToolCallEarlyStopReasoning(unittest.TestCase):
    def test_early_stop_waits_for_tool_call_finish_reason(self):
        async def collect_items():
            block = BasicCodeBlock(_FakeContext())
            block.llm_client = _FakeLLMClient()
            return [
                item
                async for item in block.llm_chat_stream(
                    llm_params={"model": "deepseek-v4-pro", "messages": Messages()},
                    recorder=None,
                    content="请调用 _date",
                    early_stop_on_tool_call=True,
                )
            ]

        items = asyncio.run(collect_items())

        # Regression guard: old behavior stopped at the second chunk as soon
        # as arguments parsed, before the later reasoning_content chunk.
        self.assertEqual(len(items), 4)
        self.assertTrue(items[-1].has_complete_tool_call())
        self.assertEqual(items[-1].finish_reason, "tool_calls")
        self.assertEqual(items[-1].think, "")


class TestSingleMessageReasoningContent(unittest.TestCase):
    def test_to_dict_omits_reasoning_when_absent(self):
        msg = SingleMessage(role=MessageRole.ASSISTANT, content="hi")
        self.assertNotIn("reasoning_content", msg.to_dict())

    def test_to_dict_includes_reasoning_when_empty_string(self):
        """Empty string means thinking mode was active but produced no output.
        The field MUST be included in to_dict() so it can be echoed back to
        the API (DeepSeek requirement), even though the value is empty.
        Previously this was omitted via `reasoning_content or None`, which was
        incorrect for thinking-mode models.
        """
        msg = SingleMessage(
            role=MessageRole.ASSISTANT, content="hi", reasoning_content=""
        )
        self.assertIn("reasoning_content", msg.to_dict())
        self.assertEqual(msg.to_dict()["reasoning_content"], "")

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


class TestEmptyReasoningContentRoundtrip(unittest.TestCase):
    """End-to-end guard: empty reasoning_content must survive the full
    store-and-restore cycle so that subsequent API calls include the field.
    """

    def _tool_calls(self):
        return [{"id": "call_1", "type": "function",
                 "function": {"name": "builtin_skill_load", "arguments": "{}"}}]

    def test_empty_reasoning_content_survives_add_and_serialize(self):
        """add_tool_call_message with reasoning_content="" must emit the field."""
        msgs = Messages()
        msgs.add_tool_call_message(
            content="", tool_calls=self._tool_calls(), reasoning_content=""
        )
        dumped = msgs.get_messages_as_dict()
        self.assertIn("reasoning_content", dumped[0])
        self.assertEqual(dumped[0]["reasoning_content"], "")

    def test_empty_reasoning_content_survives_extend_plain_messages(self):
        """extend_plain_messages with reasoning_content: '' must preserve it."""
        plain = [{"role": "assistant", "content": "",
                  "tool_calls": self._tool_calls(), "reasoning_content": ""}]
        msgs = Messages()
        msgs.extend_plain_messages(plain)
        restored = msgs.get_messages_as_dict()[0]
        self.assertIn("reasoning_content", restored)
        self.assertEqual(restored["reasoning_content"], "")

    def test_copy_preserves_empty_reasoning_content(self):
        msg = SingleMessage(role=MessageRole.ASSISTANT, content="",
                            reasoning_content="")
        copied = msg.copy()
        self.assertEqual(copied.reasoning_content, "")
        self.assertIn("reasoning_content", copied.to_dict())
        self.assertEqual(copied.to_dict()["reasoning_content"], "")

    def test_none_reasoning_content_is_still_omitted(self):
        """None (non-thinking model) must remain absent from the dict."""
        msg = SingleMessage(role=MessageRole.ASSISTANT, content="hi")
        self.assertIsNone(msg.reasoning_content)
        self.assertNotIn("reasoning_content", msg.to_dict())


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
