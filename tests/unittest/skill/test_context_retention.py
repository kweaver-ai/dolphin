"""Tests for Skill Context Retention strategies."""

import pytest
from dolphin.core.skill.context_retention import (
    ContextRetentionMode,
    SkillContextRetention,
    SummaryContextStrategy,
    FullContextStrategy,
    PinContextStrategy,
    ReferenceContextStrategy,
    get_context_retention_strategy,
    context_retention,
)


class TestContextRetentionMode:
    """Tests for ContextRetentionMode enum."""

    def test_enum_values(self):
        """Test that all expected modes exist."""
        assert ContextRetentionMode.SUMMARY.value == "summary"
        assert ContextRetentionMode.FULL.value == "full"
        assert ContextRetentionMode.PIN.value == "pin"
        assert ContextRetentionMode.REFERENCE.value == "reference"

    def test_enum_from_string(self):
        """Test creating enum from string."""
        assert ContextRetentionMode("summary") == ContextRetentionMode.SUMMARY
        assert ContextRetentionMode("full") == ContextRetentionMode.FULL
        assert ContextRetentionMode("pin") == ContextRetentionMode.PIN
        assert ContextRetentionMode("reference") == ContextRetentionMode.REFERENCE


class TestSkillContextRetention:
    """Tests for SkillContextRetention dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SkillContextRetention()
        assert config.mode == ContextRetentionMode.FULL
        assert config.max_length == 2000
        assert config.summary_prompt is None
        assert config.ttl_turns == -1
        assert config.reference_hint is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SkillContextRetention(
            mode=ContextRetentionMode.SUMMARY,
            max_length=500,
            summary_prompt="Summarize this",
            ttl_turns=5,
            reference_hint="Custom hint",
        )
        assert config.mode == ContextRetentionMode.SUMMARY
        assert config.max_length == 500
        assert config.summary_prompt == "Summarize this"
        assert config.ttl_turns == 5
        assert config.reference_hint == "Custom hint"


class TestSummaryContextStrategy:
    """Tests for SummaryContextStrategy."""

    def setup_method(self):
        self.strategy = SummaryContextStrategy()
        self.config = SkillContextRetention(
            mode=ContextRetentionMode.SUMMARY,
            max_length=100,
        )

    def test_short_content_unchanged(self):
        """Content shorter than max_length should be unchanged."""
        result = "Short content"
        processed = self.strategy.process(result, self.config)
        assert processed == result

    def test_long_content_truncated(self):
        """Content longer than max_length should be truncated."""
        result = "A" * 200  # 200 chars
        processed = self.strategy.process(result, self.config)
        assert len(processed) < 200
        assert "omitted" in processed

    def test_reference_hint_included(self):
        """Reference ID should be included in hint when provided."""
        result = "A" * 200
        processed = self.strategy.process(result, self.config, reference_id="ref_123")
        assert "ref_123" in processed
        assert "_get_cached_result_detail" in processed

    def test_head_tail_preserved(self):
        """Head and tail of content should be preserved."""
        result = "HEAD" + "X" * 100 + "TAIL"
        processed = self.strategy.process(result, self.config)
        assert "HEAD" in processed
        assert "TAIL" in processed


class TestFullContextStrategy:
    """Tests for FullContextStrategy."""

    def setup_method(self):
        self.strategy = FullContextStrategy()
        self.config = SkillContextRetention(mode=ContextRetentionMode.FULL)

    def test_content_unchanged(self):
        """Content should be returned unchanged."""
        result = "A" * 10000  # Very long content
        processed = self.strategy.process(result, self.config)
        assert processed == result


class TestPinContextStrategy:
    """Tests for PinContextStrategy."""

    def setup_method(self):
        self.strategy = PinContextStrategy()
        self.config = SkillContextRetention(mode=ContextRetentionMode.PIN)

    def test_pin_marker_added(self):
        """PIN_MARKER should be added to content."""
        result = "Important content"
        processed = self.strategy.process(result, self.config)
        from dolphin.core.common.constants import PIN_MARKER
        assert processed.startswith(PIN_MARKER)
        assert "Important content" in processed

    def test_pin_marker_not_duplicated(self):
        """PIN_MARKER should not be duplicated if already present."""
        from dolphin.core.common.constants import PIN_MARKER
        result = f"{PIN_MARKER}Already pinned"
        processed = self.strategy.process(result, self.config)
        # Should not have double PIN_MARKER
        assert processed.count(PIN_MARKER) == 1


class TestReferenceContextStrategy:
    """Tests for ReferenceContextStrategy."""

    def setup_method(self):
        self.strategy = ReferenceContextStrategy()
        self.config = SkillContextRetention(
            mode=ContextRetentionMode.REFERENCE,
            reference_hint="Custom hint",
        )

    def test_reference_info_returned(self):
        """Reference info with fetch instructions should be returned."""
        result = "A" * 5000
        processed = self.strategy.process(result, self.config, reference_id="ref_xyz")
        assert "Custom hint" in processed
        assert "5000" in processed  # Original length
        assert "ref_xyz" in processed
        assert "_get_cached_result_detail" in processed

    def test_fallback_to_summary_without_reference(self):
        """Should fallback to summary strategy when no reference_id."""
        result = "A" * 200
        config = SkillContextRetention(
            mode=ContextRetentionMode.REFERENCE,
            max_length=100,
        )
        processed = self.strategy.process(result, config, reference_id=None)
        # Should have summary behavior (truncation)
        assert "omitted" in processed


class TestGetContextRetentionStrategy:
    """Tests for get_context_retention_strategy function."""

    def test_returns_correct_strategy(self):
        """Should return the correct strategy for each mode."""
        assert isinstance(
            get_context_retention_strategy(ContextRetentionMode.SUMMARY),
            SummaryContextStrategy,
        )
        assert isinstance(
            get_context_retention_strategy(ContextRetentionMode.FULL),
            FullContextStrategy,
        )
        assert isinstance(
            get_context_retention_strategy(ContextRetentionMode.PIN),
            PinContextStrategy,
        )
        assert isinstance(
            get_context_retention_strategy(ContextRetentionMode.REFERENCE),
            ReferenceContextStrategy,
        )

    def test_default_to_full_for_unknown(self):
        """Should default to FullContextStrategy for unknown modes."""
        # This tests the fallback behavior
        strategy = get_context_retention_strategy(None)  # type: ignore
        assert isinstance(strategy, FullContextStrategy)


class TestContextRetentionDecorator:
    """Tests for context_retention decorator."""

    def test_decorator_attaches_config(self):
        """Decorator should attach _context_retention config to function."""

        @context_retention(mode="summary", max_length=500)
        def my_skill():
            pass

        config = getattr(my_skill, "_context_retention", None)
        assert config is not None
        assert config.mode == ContextRetentionMode.SUMMARY
        assert config.max_length == 500

    def test_decorator_with_all_params(self):
        """Decorator should handle all parameters."""

        @context_retention(
            mode="reference",
            max_length=1000,
            summary_prompt="Custom prompt",
            ttl_turns=10,
            reference_hint="Custom hint",
        )
        def my_skill():
            pass

        config = getattr(my_skill, "_context_retention", None)
        assert config.mode == ContextRetentionMode.REFERENCE
        assert config.max_length == 1000
        assert config.summary_prompt == "Custom prompt"
        assert config.ttl_turns == 10
        assert config.reference_hint == "Custom hint"

    def test_decorator_invalid_mode_defaults_to_full(self):
        """Invalid mode should default to FULL."""

        @context_retention(mode="invalid_mode")
        def my_skill():
            pass

        config = getattr(my_skill, "_context_retention", None)
        assert config.mode == ContextRetentionMode.FULL

    def test_undecorated_function_has_no_config(self):
        """Undecorated function should not have _context_retention."""

        def plain_skill():
            pass

        config = getattr(plain_skill, "_context_retention", None)
        assert config is None
