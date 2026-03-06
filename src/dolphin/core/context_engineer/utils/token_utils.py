"""Token utility functions."""

from typing import Union, Dict, List, Optional

from dolphin.core.common.enums import MessageRole, Messages, SingleMessage
from ..core.tokenizer_service import TokenizerService


def estimate_tokens(
    text: Union[str, List[str], Dict[str, str]], avg_chars_per_token: float = 4.0
) -> int:
    """
    Estimate token count based on character length.

    Args:
        text: Input text (string, list, or dict)
        avg_chars_per_token: Average characters per token

    Returns:
        Estimated token count
    """
    if isinstance(text, str):
        return int(len(text) / avg_chars_per_token)
    elif isinstance(text, list):
        return sum(int(len(item) / avg_chars_per_token) for item in text)
    elif isinstance(text, dict):
        total = 0
        for key, value in text.items():
            total += int(len(str(key)) / avg_chars_per_token)
            total += int(len(str(value)) / avg_chars_per_token)
        return total
    else:
        return int(len(str(text)) / avg_chars_per_token)


def count_tokens(
    text: Union[str, List[str], Dict[str, str]],
    tokenizer_service: Optional[TokenizerService] = None,
) -> int:
    """
    Count tokens using tokenizer service.

    Args:
        text: Input text (string, list, or dict)
        tokenizer_service: TokenizerService instance (creates default if None)

    Returns:
        Token count
    """
    if tokenizer_service is None:
        tokenizer_service = TokenizerService()

    return tokenizer_service.count_tokens(text)


def get_text_chunks(
    text: str, max_tokens: int, tokenizer_service: Optional[TokenizerService] = None
) -> List[str]:
    """
    Split text into chunks based on token limit.

    Args:
        text: Input text
        max_tokens: Maximum tokens per chunk
        tokenizer_service: TokenizerService instance

    Returns:
        List of text chunks
    """
    if tokenizer_service is None:
        tokenizer_service = TokenizerService()

    words = text.split()
    chunks = []
    current_chunk = []
    current_tokens = 0

    for word in words:
        word_tokens = tokenizer_service.count_tokens(word)

        if current_tokens + word_tokens > max_tokens and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_tokens = word_tokens
        else:
            current_chunk.append(word)
            current_tokens += word_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def truncate_to_tokens(
    text: Union[str, Messages],
    max_tokens: int,
    tokenizer_service: Optional[TokenizerService] = None,
) -> str:
    """
    Truncate text to fit within token limit.

    Args:
        text: Input text (string or Messages)
        max_tokens: Maximum tokens allowed
        tokenizer_service: TokenizerService instance

    Returns:
        Truncated text
    """
    if tokenizer_service is None:
        tokenizer_service = TokenizerService()

    # If it is a Messages type, extract the content of all messages and concatenate them.
    if isinstance(text, Messages):
        contents = []
        for msg in text.messages:
            if hasattr(msg, "content") and msg.content:
                contents.append(str(msg.content))
        text_content = "\n".join(contents)
    else:
        text_content = str(text)

    if tokenizer_service.count_tokens(text_content) <= max_tokens:
        return text_content

    words = text_content.split()
    result = []
    candidate = ""

    for word in words:
        next_candidate = (candidate + " " + word) if candidate else word
        if tokenizer_service.count_tokens(next_candidate) > max_tokens:
            break
        result.append(word)
        candidate = next_candidate

    return " ".join(result)


def truncate_messages_to_tokens(
    messages: Messages,
    max_tokens: int,
    tokenizer_service: Optional[TokenizerService] = None,
) -> Messages:
    """
    Truncate a Messages object to fit within token limit by dropping oldest messages first.

    Preserves message structure (roles, boundaries). Keeps the most recent messages.

    Args:
        messages: Input Messages object
        max_tokens: Maximum tokens allowed
        tokenizer_service: TokenizerService instance

    Returns:
        Truncated Messages object (same type, structure preserved)
    """
    if tokenizer_service is None:
        tokenizer_service = TokenizerService()

    groups = _group_messages_for_truncation(list(messages.messages))
    while groups:
        msgs = _flatten_message_groups(groups)
        total = sum(_count_tokens_for_message(msg, tokenizer_service) for msg in msgs)
        if total <= max_tokens:
            break
        if len(groups) == 1 and len(groups[0]) == 1:
            groups[0][0] = _truncate_single_message(
                groups[0][0],
                max_tokens,
                tokenizer_service,
            )
            break
        if len(groups) == 1:
            # The last remaining group is a multi-message tool call chain.
            # Splitting it would leave orphan tool responses, making the
            # conversation invalid for the LLM.  Accept the overage rather
            # than producing a broken message sequence.
            break
        groups.pop(0)

    result = Messages()
    result.max_tokens = messages.max_tokens
    result.messages = _flatten_message_groups(groups)
    return result


def _count_tokens_for_message(
    msg: SingleMessage,
    tokenizer_service: TokenizerService,
) -> int:
    """Count tokens for a single message, handling both str and multi-block content."""
    if isinstance(msg.content, list):
        return sum(
            tokenizer_service.count_tokens(block.get("text", ""))
            for block in msg.content
            if block.get("type") == "text"
        )
    return tokenizer_service.count_tokens(str(msg.content) if msg.content else "")


def _group_messages_for_truncation(
    messages: List[SingleMessage],
) -> List[List[SingleMessage]]:
    """Group messages so tool call chains are dropped atomically."""
    groups: List[List[SingleMessage]] = []
    current_group: List[SingleMessage] = []
    expecting_tools = False
    expected_tool_ids = set()

    for msg in messages:
        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            if current_group:
                groups.append(current_group)

            current_group = [msg]
            expecting_tools = True
            expected_tool_ids = {
                tc.get("id")
                for tc in msg.tool_calls
                if isinstance(tc, dict) and tc.get("id")
            }
            continue

        if msg.role == MessageRole.TOOL and expecting_tools:
            if msg.tool_call_id not in expected_tool_ids:
                # Unrecognized tool_call_id — flush the incomplete group and
                # treat this response as a standalone message so the group
                # does not stay open indefinitely.
                if current_group:
                    groups.append(current_group)
                    current_group = []
                expecting_tools = False
                expected_tool_ids = set()
                groups.append([msg])
                continue

            current_group.append(msg)
            expected_tool_ids.discard(msg.tool_call_id)

            if not expected_tool_ids:
                groups.append(current_group)
                current_group = []
                expecting_tools = False
            continue

        if current_group:
            groups.append(current_group)
            current_group = []
            expecting_tools = False
            expected_tool_ids = set()

        groups.append([msg])

    if current_group:
        groups.append(current_group)

    return groups


def _flatten_message_groups(groups: List[List[SingleMessage]]) -> List[SingleMessage]:
    """Flatten grouped messages back into a plain message list."""
    return [msg for group in groups for msg in group]


def _truncate_single_message(
    message: SingleMessage,
    max_tokens: int,
    tokenizer_service: TokenizerService,
) -> SingleMessage:
    """Truncate message content in-place fallback while preserving metadata."""
    truncated = message.copy()

    if isinstance(truncated.content, str):
        truncated.content = truncate_to_tokens(
            truncated.content,
            max_tokens,
            tokenizer_service,
        )
        return truncated

    remaining_tokens = max_tokens
    truncated_blocks = []
    for block in truncated.content:
        if remaining_tokens <= 0:
            break

        if block.get("type") != "text":
            block_tokens = tokenizer_service.count_tokens(str(block))
            truncated_blocks.append(block)
            remaining_tokens -= block_tokens
            continue

        text = block.get("text", "")
        if not text:
            truncated_blocks.append(block)
            continue

        truncated_text = truncate_to_tokens(text, remaining_tokens, tokenizer_service)
        truncated_blocks.append({**block, "text": truncated_text})
        remaining_tokens -= tokenizer_service.count_tokens(truncated_text)
        if remaining_tokens <= 0:
            break

    truncated.content = truncated_blocks
    return truncated
