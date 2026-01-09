"""Token utility functions."""

from typing import Union, Dict, List, Optional

from dolphin.core.common.enums import Messages
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
    current_tokens = 0

    for word in words:
        word_tokens = tokenizer_service.count_tokens(word)

        if current_tokens + word_tokens > max_tokens:
            break
        result.append(word)
        current_tokens += word_tokens

    return " ".join(result)
