"""Unit tests for token utility helpers."""

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.context_engineer.config.settings import ContextConfig, get_default_config
from dolphin.core.context_engineer.core.tokenizer_service import TokenizerService
from dolphin.core.context_engineer.utils.token_utils import truncate_messages_to_tokens


def test_truncate_messages_preserves_last_message_with_content_truncation():
    """The newest message should be truncated instead of being dropped."""
    tokenizer_service = TokenizerService()
    overlong_content = "detail " * 200
    max_tokens = max(tokenizer_service.count_tokens("detail"), 1)

    messages = Messages()
    messages.add_message("old context", role=MessageRole.USER)
    messages.add_message(overlong_content, role=MessageRole.ASSISTANT)

    truncated = truncate_messages_to_tokens(
        messages,
        max_tokens=max_tokens,
        tokenizer_service=tokenizer_service,
    )

    assert len(truncated.messages) == 1
    assert truncated.messages[0].role == MessageRole.ASSISTANT
    assert truncated.messages[0].content
    assert tokenizer_service.count_tokens(truncated.messages[0].content) <= max_tokens


def test_context_config_uses_qwen_plus_as_default_model():
    """The default model name should match the shipped default configuration."""
    config = ContextConfig.from_dict({})

    assert config.model.name == "qwen-plus"
    assert config.model.context_limit == 16384


def test_get_default_config_uses_qwen_plus():
    """Built-in default config should use qwen-plus."""
    config = get_default_config()

    assert config.model.name == "qwen-plus"


def test_truncate_messages_drops_tool_call_chain_atomically():
    """Tool call chains should be removed as a whole to keep message order valid."""
    tokenizer_service = TokenizerService()
    max_tokens = tokenizer_service.count_tokens("final answer")

    messages = Messages()
    messages.add_message("old context", role=MessageRole.USER)
    messages.add_tool_call_message(
        content="calling tool",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "search"}}],
    )
    messages.add_tool_response_message(
        content="tool result",
        tool_call_id="call_1",
    )
    messages.add_message("final answer", role=MessageRole.ASSISTANT)

    truncated = truncate_messages_to_tokens(
        messages,
        max_tokens=max_tokens,
        tokenizer_service=tokenizer_service,
    )

    assert len(truncated.messages) == 1
    assert truncated.messages[0].role == MessageRole.ASSISTANT
    assert truncated.messages[0].content == "final answer"


def test_truncate_messages_never_keeps_orphan_tool_response():
    """A tool response must not survive when its assistant tool call is dropped."""
    tokenizer_service = TokenizerService()
    max_tokens = tokenizer_service.count_tokens("tool result final answer")

    messages = Messages()
    messages.add_message("old context", role=MessageRole.USER)
    messages.add_tool_call_message(
        content="calling tool",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "search"}}],
    )
    messages.add_tool_response_message(
        content="tool result",
        tool_call_id="call_1",
    )
    messages.add_message("final answer", role=MessageRole.ASSISTANT)

    truncated = truncate_messages_to_tokens(
        messages,
        max_tokens=max_tokens,
        tokenizer_service=tokenizer_service,
    )

    assert all(msg.role != MessageRole.TOOL for msg in truncated.messages)
    assert all(not msg.tool_calls for msg in truncated.messages)


def test_truncate_messages_keeps_last_tool_call_group():
    """The last tool call group should not be dropped when it is the only survivor."""
    tokenizer_service = TokenizerService()
    max_tokens = max(tokenizer_service.count_tokens("result"), 1)

    messages = Messages()
    messages.add_tool_call_message(
        content="calling tool with a lot of context " * 50,
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "search"}}],
    )
    messages.add_tool_response_message(
        content="result " * 50,
        tool_call_id="call_1",
    )

    truncated = truncate_messages_to_tokens(
        messages,
        max_tokens=max_tokens,
        tokenizer_service=tokenizer_service,
    )

    assert len(truncated.messages) == 2
    assert truncated.messages[0].role == MessageRole.ASSISTANT
    assert truncated.messages[0].tool_calls
    assert truncated.messages[1].role == MessageRole.TOOL
    assert truncated.messages[1].tool_call_id == "call_1"
    assert truncated.messages[0].content == "calling tool with a lot of context " * 50
    assert truncated.messages[1].content == "result " * 50
