"""Tests for TokenizerService."""

import pytest
from dolphin.core.context_engineer.core.tokenizer_service import (
    TokenizerService,
    SimpleTokenizer,
    TiktokenTokenizer,
)


class TestTokenizerService:
    """Test cases for TokenizerService."""

    def test_simple_tokenizer_basic(self):
        """Test basic functionality of SimpleTokenizer."""
        tokenizer = SimpleTokenizer()

        # Test empty string
        assert tokenizer.count_tokens("") == 0
        assert tokenizer.estimate_tokens("") == 0

        # Test simple text
        text = "Hello world this is a test"
        count = tokenizer.count_tokens(text)
        estimate = tokenizer.estimate_tokens(text)

        assert count > 0
        assert estimate > 0
        assert abs(count - estimate) < 10  # Should be reasonably close

    def test_tokenizer_service_string_input(self):
        """Test TokenizerService with string input."""
        service = TokenizerService(backend="simple")

        text = "The quick brown fox jumps over the lazy dog"
        count = service.count_tokens(text)
        estimate = service.estimate_tokens(text)

        assert count > 0
        assert estimate > 0

    def test_tokenizer_service_list_input(self):
        """Test TokenizerService with list input."""
        service = TokenizerService(backend="simple")

        texts = ["Hello world", "This is a test", "Another sentence"]
        count = service.count_tokens(texts)

        assert count > 0
        assert count == sum(service.count_tokens(text) for text in texts)

    def test_tokenizer_service_dict_input(self):
        """Test TokenizerService with dictionary input."""
        service = TokenizerService(backend="simple")

        content = {
            "title": "Test Document",
            "body": "This is the main content of the document.",
            "footer": "Copyright 2024",
        }
        count = service.count_tokens(content)

        assert count > 0
        # Should count both keys and values
        assert count == (
            service.count_tokens("title")
            + service.count_tokens("Test Document")
            + service.count_tokens("body")
            + service.count_tokens("This is the main content of the document.")
            + service.count_tokens("footer")
            + service.count_tokens("Copyright 2024")
        )

    def test_count_tokens_with_breakdown(self):
        """Test token counting with breakdown by section."""
        service = TokenizerService(backend="simple")

        content = {
            "system": "You are a helpful assistant.",
            "user": "What is the weather like?",
            "context": "Previous conversation about weather patterns.",
        }

        breakdown = service.count_tokens_with_breakdown(content)

        assert "total" in breakdown
        assert breakdown["total"] > 0
        assert len(breakdown) == len(content) + 1  # +1 for total

        for section in content:
            assert section in breakdown
            assert breakdown[section] > 0

    def test_tokenizer_info(self):
        """Test getting tokenizer information."""
        service = TokenizerService(backend="simple")
        info = service.get_tokenizer_info()

        assert "backend" in info
        assert info["backend"] == "SimpleTokenizer"
        assert "available" in info
        assert info["available"] is True

    def test_auto_backend_selection(self):
        """Test automatic backend selection."""
        service = TokenizerService(backend="auto")
        info = service.get_tokenizer_info()

        assert "backend" in info
        assert info["available"] is True

    def test_invalid_backend(self):
        """Test handling of invalid backend."""
        with pytest.raises(ValueError):
            TokenizerService(backend="invalid_backend")


class TestTiktokenTokenizer:
    """Test cases for TiktokenTokenizer."""

    def test_tiktoken_tokenizer_availability(self):
        """Test TiktokenTokenizer availability check."""
        tokenizer = TiktokenTokenizer()

        # Should handle import gracefully
        assert hasattr(tokenizer, "available")

        if tokenizer.available:
            # Test basic functionality if available
            text = "Hello world"
            count = tokenizer.count_tokens(text)
            assert count > 0

            estimate = tokenizer.estimate_tokens(text)
            assert estimate == count  # For tiktoken, estimate should equal count
        else:
            # Should have fallback
            assert hasattr(tokenizer, "fallback")
            assert tokenizer.fallback is not None
