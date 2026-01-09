"""Tokenizer service for unified tokenization and length estimation.

Unified tokenizer service for tokenization and length estimation.
"""

import re
from typing import Dict, Union, List
from abc import ABC, abstractmethod


class BaseTokenizer(ABC):
    """Abstract base class for tokenizers.

        Abstract base class for tokenizers, defining the interface that tokenizers should implement.
    """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens in the given text.

                Count the number of tokens in the given text.

        Args:
            text (str): The text to count tokens for

        Returns:
            int: The number of tokens in the text
        """
        pass

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (faster but less accurate).

                Estimate the number of tokens (faster but less accurate).

        Args:
            text (str): The text to estimate the token count for

        Returns:
            int: The estimated token count
        """
        pass


class SimpleTokenizer(BaseTokenizer):
    """Simple tokenizer using regex-based word splitting.

        Simple tokenizer using regex-based word splitting.
    """

    def __init__(self, avg_chars_per_token: float = 4.0):
        """Initialize a simple tokenizer.

        Args:
            avg_chars_per_token (float): Average number of characters per token, default is 4.0
        """
        self.avg_chars_per_token = avg_chars_per_token
        self.word_pattern = re.compile(r"\w+|[^\w\s]")

    def count_tokens(self, text: str) -> int:
        """Count tokens using word-based splitting.

                Count tokens using word-based splitting.

        Args:
            text (str): The text to count tokens for

        Returns:
            int: The number of tokens in the text
        """
        if not text:
            return 0
        words = self.word_pattern.findall(text)
        return len(words)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count based on character length.

                Estimate the number of tokens based on character length.

        Args:
            text (str): The text to estimate token count for

        Returns:
            int: Estimated token count
        """
        if not text:
            return 0
        return int(len(text) / self.avg_chars_per_token)


class TiktokenTokenizer(BaseTokenizer):
    """Tokenizer using tiktoken (if available).

        Tokenizer using tiktoken (if available).
    """

    def __init__(self, encoding_name: str = "cl100k_base"):
        """Initialize the tiktoken tokenizer.

        Args:
            encoding_name (str): Encoding name, default is "cl100k_base"
        """
        try:
            import tiktoken

            # Try to get the encoding, which may trigger a network request to download the encoding file
            try:
                self.encoding = tiktoken.get_encoding(encoding_name)
                self.available = True
            except (OSError, ConnectionError, TimeoutError, Exception):
                # Catch network connection errors and other exceptions, mark as unavailable
                self.available = False
                self.fallback = SimpleTokenizer()
        except ImportError:
            self.available = False
            self.fallback = SimpleTokenizer()

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken encoding.

                Count the number of tokens using tiktoken encoding.

        Args:
            text (str): The text to count tokens for

        Returns:
            int: The number of tokens in the text
        """
        if not self.available:
            return self.fallback.count_tokens(text)
        return len(self.encoding.encode(text))

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (same as count for tiktoken).

                Estimate the number of tokens (same as count_tokens for tiktoken).

        Args:
            text (str): The text to estimate the token count for

        Returns:
            int: Estimated number of tokens
        """
        return self.count_tokens(text)


class TokenizerService:
    """Unified tokenizer service supporting multiple backends.

        Unified tokenizer service supporting multiple backends.
    """

    def __init__(self, backend: str = "auto", **kwargs):
        """Initialize tokenizer service.

                Initialize the tokenizer service.

        Args:
            backend: Tokenizer backend ('simple', 'tiktoken', 'auto')
            **kwargs: Additional arguments specific to the backend
        """
        if backend == "auto":
            # Default to SimpleTokenizer to avoid attempting tiktoken when network is unavailable
            self.tokenizer = SimpleTokenizer(**kwargs)
        elif backend == "tiktoken":
            self.tokenizer = TiktokenTokenizer(**kwargs)
        elif backend == "simple":
            self.tokenizer = SimpleTokenizer(**kwargs)
        else:
            raise ValueError(f"Unknown tokenizer backend: {backend}")

    def count_tokens(self, text: Union[str, List[str], Dict[str, str]]) -> int:
        """Count tokens in text.

                Calculate the number of tokens in text.

        Args:
            text: string, list of strings, or dictionary of strings

        Returns:
            Total number of tokens
        """
        if isinstance(text, str):
            return self.tokenizer.count_tokens(text)
        elif isinstance(text, list):
            return sum(self.tokenizer.count_tokens(item) for item in text)
        elif isinstance(text, dict):
            total = 0
            for key, value in text.items():
                total += self.tokenizer.count_tokens(str(key))
                total += self.tokenizer.count_tokens(str(value))
            return total
        else:
            return self.tokenizer.count_tokens(str(text))

    def estimate_tokens(self, text: Union[str, List[str], Dict[str, str]]) -> int:
        """Estimate tokens in text (faster but less accurate).

                Estimate the number of tokens in text (faster but less accurate).

        Args:
            text: string, list of strings, or dictionary of strings

        Returns:
            Estimated number of tokens
        """
        if isinstance(text, str):
            return self.tokenizer.estimate_tokens(text)
        elif isinstance(text, list):
            return sum(self.tokenizer.estimate_tokens(item) for item in text)
        elif isinstance(text, dict):
            total = 0
            for key, value in text.items():
                total += self.tokenizer.estimate_tokens(str(key))
                total += self.tokenizer.estimate_tokens(str(value))
            return total
        else:
            return self.tokenizer.estimate_tokens(str(text))

    def count_tokens_with_breakdown(self, text: Dict[str, str]) -> Dict[str, int]:
        """Count tokens for each section in a dictionary.

                Count the number of tokens for each part in a dictionary.

        Args:
            text: Dictionary of text parts

        Returns:
            Dictionary of token counts for each part
        """
        breakdown = {}
        total = 0

        for key, value in text.items():
            count = self.count_tokens(value)
            breakdown[key] = count
            total += count

        breakdown["total"] = total
        return breakdown

    def get_tokenizer_info(self) -> Dict[str, Union[str, bool]]:
        """Get information about the current tokenizer.

                Get information about the current tokenizer.

        Returns:
            A dictionary containing tokenizer information
        """
        info = {"backend": type(self.tokenizer).__name__, "available": True}

        # Check if it is a TiktokenTokenizer and has an available attribute
        if isinstance(self.tokenizer, TiktokenTokenizer):
            info["available"] = self.tokenizer.available
            if self.tokenizer.available and hasattr(self.tokenizer, "encoding"):
                info["encoding_name"] = self.tokenizer.encoding.name

        return info
