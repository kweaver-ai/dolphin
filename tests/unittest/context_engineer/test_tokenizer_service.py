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


class TestSimpleTokenizerConsistency:
    """Bug 2: SimpleTokenizer.count_tokens (word-based) can disagree with
    estimate_tokens (char-based) by orders of magnitude on certain inputs.

    The compressor uses estimate_tokens for fast checks and count_tokens for
    "precise" counting near the budget boundary. A large discrepancy causes
    the compressor to skip compression when it should compress.
    """

    @pytest.mark.parametrize(
        "text,label",
        [
            ("a" * 1000, "repeated single char"),
            ("abcdefghij" * 100, "repeated pattern no spaces"),
            ("x" * 500 + " " + "y" * 500, "two long words"),
            (
                '{"role":"user","content":"' + "z" * 500 + '"}',
                "JSON with long string value",
            ),
            ("这是一段中文测试" * 50, "repeated Chinese text no spaces"),
        ],
    )
    def test_simple_tokenizer_count_vs_estimate_consistency(self, text, label):
        """count_tokens and estimate_tokens must agree within 2x.

        Current bug: count_tokens uses regex \\w+|[^\\w\\s] word splitting,
        so "a" * 1000 → 1 token. estimate_tokens uses len/4.0 → 250 tokens.
        """
        tokenizer = SimpleTokenizer()
        count = tokenizer.count_tokens(text)
        estimate = tokenizer.estimate_tokens(text)

        # Neither should be zero for non-empty text
        assert count > 0, f"count_tokens returned 0 for '{label}'"
        assert estimate > 0, f"estimate_tokens returned 0 for '{label}'"

        ratio = max(count, estimate) / max(min(count, estimate), 1)
        assert ratio <= 2.0, (
            f"SimpleTokenizer count/estimate mismatch for '{label}': "
            f"count={count}, estimate={estimate}, ratio={ratio:.1f}x. "
            f"These methods must be consistent — the compressor relies on both."
        )

    def test_precise_count_does_not_contradict_fast_estimate(self):
        """When _should_use_precise_count triggers, the precise count must
        not wildly disagree with the fast estimate.

        Current bug: near the budget boundary (ratio in [0.85, 1.05]),
        _count_tokens_precise returns ~2K while estimate_tokens returns ~107K
        because SimpleTokenizer.count_tokens word-splits long continuous content.
        """
        from dolphin.core.message.compressor import TruncationStrategy
        from dolphin.core.common.enums import Messages, MessageRole
        from dolphin.core.context.context import Context
        from dolphin.core.config.global_config import GlobalConfig, ContextConstraints

        ctx = Context(config=GlobalConfig(), verbose=False, is_cli=False)
        strategy = TruncationStrategy()

        # Build messages whose fast estimate is near the budget boundary
        # Budget = 100000 - 10000 = 90000. We want estimate ~85K-95K.
        msgs = Messages()
        msgs.add_message(role=MessageRole.SYSTEM, content="System prompt here")
        msgs.add_message(role=MessageRole.USER, content="User query")
        # ~65K chars → ~65K * 1.3 ≈ 84.5K tokens (char-based estimate)
        msgs.add_message(role=MessageRole.ASSISTANT, content="a " * 32500)

        constraints = ContextConstraints(
            max_input_tokens=100000,
            reserve_output_tokens=10000,
            preserve_system=True,
        )
        budget = constraints.max_input_tokens - constraints.reserve_output_tokens

        fast_estimate = strategy.estimate_tokens(msgs)
        # Verify we're in the "precise" boundary zone
        ratio = fast_estimate / budget
        assert 0.80 <= ratio <= 1.10, (
            f"Test setup: fast_estimate={fast_estimate}, budget={budget}, "
            f"ratio={ratio:.2f} — not in boundary zone, adjust test content"
        )

        # Now check precise count
        precise_count = strategy._count_tokens_precise(ctx, msgs)
        assert precise_count is not None, "Precise count returned None"

        mismatch_ratio = max(fast_estimate, precise_count) / max(
            min(fast_estimate, precise_count), 1
        )
        # The fast estimate uses CHINESE_CHAR_TO_TOKEN_RATIO (1.3 tokens/char)
        # while SimpleTokenizer uses avg_chars_per_token=4.0 (0.25 tokens/char).
        # This inherent ~5x gap exists for pure English content.  For Chinese
        # text the gap narrows.  We tolerate up to 6x here; the critical fix
        # is that the old word-splitting bug (250x mismatch) is gone.
        assert mismatch_ratio <= 6.0, (
            f"Precise count ({precise_count}) disagrees with fast estimate "
            f"({fast_estimate}) by {mismatch_ratio:.1f}x. The compressor "
            f"would use the precise count and skip needed compression."
        )


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
