"""Tests for ContextAssembler v2 - Comprehensive unit tests."""

from unittest.mock import Mock, patch
import pytest


from dolphin.core.context_engineer.core.context_assembler import (
    ContextAssembler,
    ContextSection,
    AssembledContext,
)
from dolphin.core.context_engineer.core.budget_manager import BudgetAllocation
from dolphin.core.context_engineer.core.tokenizer_service import (
    TokenizerService,
)
from dolphin.core.context_engineer.config.settings import (
    ContextConfig,
)
from dolphin.core.common.enums import MessageRole


class TestContextSection:
    """Test cases for ContextSection dataclass."""

    def test_basic_creation(self):
        """Test basic ContextSection creation."""
        section = ContextSection(
            name="test_section",
            content="Test content",
            priority=1.5,
        )

        assert section.name == "test_section"
        assert section.content == "Test content"
        assert section.priority == 1.5
        assert section.token_count == 0
        assert section.allocated_tokens == 0
        assert section.message_role == MessageRole.USER
        assert section.placement == ""

    def test_creation_with_placement(self):
        """Test ContextSection creation with placement parameter."""
        section = ContextSection(
            "test_section",
            "Test content",
            1.5,
            "head",
        )

        assert section.placement == "head"

    def test_creation_with_all_parameters(self):
        """Test ContextSection creation with all possible parameters."""
        section = ContextSection(
            "test_section",
            "Test content",
            1.5,
            "head",
            100,  # token_count
            50,  # allocated_tokens
        )

        assert section.name == "test_section"
        assert section.content == "Test content"
        assert section.priority == 1.5
        assert section.placement == "head"
        assert section.token_count == 100
        assert section.allocated_tokens == 50

    def test_creation_with_kwargs(self):
        """Test ContextSection creation with keyword arguments."""
        section = ContextSection(
            "test_section",
            "Test content",
            1.5,
            message_role=MessageRole.SYSTEM,
            token_count=25,
        )

        assert section.name == "test_section"
        assert section.content == "Test content"
        assert section.priority == 1.5
        assert section.message_role == MessageRole.SYSTEM
        assert section.token_count == 25


class TestAssembledContext:
    """Test cases for AssembledContext dataclass."""

    def test_basic_creation(self):
        """Test basic AssembledContext creation."""
        sections = [
            ContextSection("section1", "Content 1", 1.0),
            ContextSection("section2", "Content 2", 1.5),
        ]
        placement_map = {"ordered": ["section1", "section2"]}
        dropped_sections = []

        context = AssembledContext(
            sections=sections,
            total_tokens=50,
            placement_map=placement_map,
            dropped_sections=dropped_sections,
        )

        assert context.sections == sections
        assert context.total_tokens == 50
        assert context.placement_map == placement_map
        assert context.dropped_sections == dropped_sections
        assert context.full_context == ""


class TestContextAssembler:
    """Test cases for ContextAssembler class."""

    def test_initialization_default(self):
        """Test ContextAssembler initialization with default parameters."""
        assembler = ContextAssembler()

        assert assembler.tokenizer is not None
        assert assembler.compressor is not None
        assert assembler.context_config is not None
        assert assembler._last_result is None
        assert assembler.placement_strategy == {"head": [], "middle": [], "tail": []}

    def test_initialization_with_custom_services(self):
        """Test ContextAssembler initialization with custom services."""
        mock_tokenizer = Mock(spec=TokenizerService)
        mock_compressor = Mock()
        mock_config = Mock(spec=ContextConfig)

        assembler = ContextAssembler(
            tokenizer_service=mock_tokenizer,
            compressor_service=mock_compressor,
            context_config=mock_config,
        )

        assert assembler.tokenizer == mock_tokenizer
        assert assembler.compressor == mock_compressor
        assert assembler.context_config == mock_config

    def test_assemble_context_basic(self):
        """Test basic context assembly."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "You are a helpful assistant.",
            "task": "Help the user with their question.",
            "history": "Previous conversation about weather.",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
            BudgetAllocation("history", 30, 1.0),
        ]

        result = assembler.assemble_context(content_sections, budget_allocations)

        assert isinstance(result, AssembledContext)
        assert len(result.sections) == 3
        assert result.total_tokens > 0
        assert "ordered" in result.placement_map
        assert len(result.dropped_sections) == 0

    def test_assemble_context_with_bucket_order(self):
        """Test context assembly with custom bucket order."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "System prompt",
            "task": "Task description",
            "history": "Conversation history",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
            BudgetAllocation("history", 30, 1.0),
        ]

        bucket_order = ["history", "system", "task"]

        result = assembler.assemble_context(
            content_sections, budget_allocations, bucket_order=bucket_order
        )

        assert isinstance(result, AssembledContext)
        assert len(result.sections) == 3
        # Check that bucket order is preserved in placement_map
        assert "ordered" in result.placement_map
        assert len(result.placement_map["ordered"]) == 3

    def test_assemble_context_with_layout_policy(self):
        """Test context assembly with layout policy."""
        mock_config = Mock(spec=ContextConfig)
        mock_policy = Mock()
        mock_policy.bucket_order = ["system", "task", "history"]
        mock_config.policies = {"test_policy": mock_policy}
        mock_config.buckets = {}

        assembler = ContextAssembler(context_config=mock_config)

        content_sections = {
            "system": "System prompt",
            "task": "Task description",
            "history": "Conversation history",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
            BudgetAllocation("history", 30, 1.0),
        ]

        result = assembler.assemble_context(
            content_sections, budget_allocations, layout_policy="test_policy"
        )

        assert isinstance(result, AssembledContext)
        assert len(result.sections) == 3

    def test_create_sections(self):
        """Test creating context sections from content and budget allocations."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "System prompt",
            "task": "Task description",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
        ]

        sections = assembler._create_sections(content_sections, budget_allocations, {})

        assert len(sections) == 2
        assert sections[0].name == "system"
        assert sections[0].content == "System prompt"
        assert sections[0].priority == 2.0
        assert sections[0].allocated_tokens == 50
        assert sections[0].token_count > 0  # Should be calculated

    def test_create_sections_with_bucket_configs(self):
        """Test creating sections with bucket configurations."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "System prompt",
            "task": "Task description",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
        ]

        # Mock bucket configs
        mock_bucket_config = Mock()
        mock_bucket_config.message_role = MessageRole.SYSTEM

        bucket_configs = {"system": mock_bucket_config}

        sections = assembler._create_sections(
            content_sections, budget_allocations, bucket_configs
        )

        assert len(sections) == 2
        system_section = next(s for s in sections if s.name == "system")
        assert system_section.message_role == MessageRole.SYSTEM
        task_section = next(s for s in sections if s.name == "task")
        assert task_section.message_role == MessageRole.USER  # Default

    def test_create_sections_missing_allocation(self):
        """Test creating sections when some sections don't have budget allocations."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "System prompt",
            "task": "Task description",
            "extra": "Extra content without allocation",
        }

        budget_allocations = [
            BudgetAllocation("system", 50, 2.0),
            BudgetAllocation("task", 40, 1.5),
        ]

        sections = assembler._create_sections(content_sections, budget_allocations, {})

        # Should only create sections for which we have allocations
        assert len(sections) == 2
        section_names = [s.name for s in sections]
        assert "system" in section_names
        assert "task" in section_names
        assert "extra" not in section_names

    def test_sort_sections_by_bucket_order(self):
        """Test sorting sections by bucket order."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("history", "History content", 1.0),
            ContextSection("system", "System prompt", 2.0),
            ContextSection("task", "Task description", 1.5),
        ]

        bucket_order = ["system", "task", "history"]

        sorted_sections = assembler._sort_sections_by_bucket_order(
            sections, bucket_order
        )

        # Should follow bucket_order
        assert sorted_sections[0].name == "system"
        assert sorted_sections[1].name == "task"
        assert sorted_sections[2].name == "history"

    def test_sort_sections_by_priority_without_bucket_order(self):
        """Test sorting sections by priority when no bucket order is provided."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("history", "History content", 1.0),
            ContextSection("system", "System prompt", 2.0),
            ContextSection("task", "Task description", 1.5),
        ]

        sorted_sections = assembler._sort_sections_by_bucket_order(sections, None)

        # Should be sorted by priority (descending)
        assert sorted_sections[0].name == "system"  # priority 2.0
        assert sorted_sections[1].name == "task"  # priority 1.5
        assert sorted_sections[2].name == "history"  # priority 1.0

    def test_sort_sections_mixed_order(self):
        """Test sorting sections with mixed bucket order and priority."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("section_a", "Content A", 1.5),
            ContextSection("section_b", "Content B", 2.0),
            ContextSection("section_c", "Content C", 1.0),
        ]

        bucket_order = ["section_c", "section_a"]

        sorted_sections = assembler._sort_sections_by_bucket_order(
            sections, bucket_order
        )

        # Should follow bucket_order, with higher priority first within same bucket
        assert sorted_sections[0].name == "section_c"  # First in bucket_order
        assert sorted_sections[1].name == "section_a"  # Second in bucket_order
        assert sorted_sections[2].name == "section_b"  # Not in bucket_order, comes last

    def test_apply_token_limits_no_compression_needed(self):
        """Test applying token limits when no compression is needed."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "short_section",
                "Short content",
                1.0,
                token_count=10,
                allocated_tokens=50,
            ),
            ContextSection(
                "normal_section",
                "Normal content",
                1.0,
                token_count=30,
                allocated_tokens=50,
            ),
        ]

        processed_sections = assembler._apply_token_limits(sections, {})

        assert len(processed_sections) == 2
        # Content should remain unchanged since token_count <= allocated_tokens
        assert processed_sections[0].content == "Short content"
        assert processed_sections[1].content == "Normal content"

    def test_apply_token_limits_with_compression(self):
        """Test applying token limits with compression."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "long_section",
                "This is a very long section that needs compression " * 20,
                1.0,
                token_count=100,
                allocated_tokens=30,
            ),
        ]

        with patch.object(assembler, "_compress_section") as mock_compress:
            mock_compress.return_value = "Compressed content"

            processed_sections = assembler._apply_token_limits(sections, {})

            assert len(processed_sections) == 1
            # Should have called compression
            mock_compress.assert_called_once()
            assert processed_sections[0].content == "Compressed content"

    def test_compress_section_no_compression_needed(self):
        """Test compression when no compression is needed."""
        assembler = ContextAssembler()

        section = ContextSection(
            "test_section",
            "Test content",
            1.0,
            token_count=20,
            allocated_tokens=50,
        )

        result = assembler._compress_section(section)

        # Should return original content
        assert result == "Test content"

    def test_compress_section_with_compressor(self):
        """Test compression using compressor service."""
        assembler = ContextAssembler()
        mock_compressor = Mock()
        mock_compressor.compress.return_value = Mock(
            compressed_content="Compressed by service"
        )
        assembler.compressor = mock_compressor

        section = ContextSection(
            "test_section",
            "Original content " * 50,
            1.0,
            token_count=100,
            allocated_tokens=30,
        )

        result = assembler._compress_section(section, "smart_compress")

        # Should use compressor service
        mock_compressor.compress.assert_called_once_with(
            content=section.content,
            target_tokens=section.allocated_tokens,
            method="smart_compress",
        )
        assert result == "Compressed by service"

    def test_compress_section_fallback_to_truncate(self):
        """Test compression fallback to truncation when compressor fails."""
        assembler = ContextAssembler()
        mock_compressor = Mock()
        mock_compressor.compress.side_effect = Exception("Compression failed")
        assembler.compressor = mock_compressor

        section = ContextSection(
            "test_section",
            "Original content " * 50,
            1.0,
            token_count=100,
            allocated_tokens=30,
        )

        with patch(
            "dolphin.core.context_engineer.utils.token_utils.truncate_to_tokens"
        ) as mock_truncate:
            mock_truncate.return_value = "Truncated content"

            result = assembler._compress_section(section, "smart_compress")

            # Should fall back to truncation
            mock_truncate.assert_called_once_with(
                section.content, 30, assembler.tokenizer
            )
            assert result == "Truncated content"

    def test_build_context_by_order_with_bucket_order(self):
        """Test building context by order with bucket order."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("system", "System prompt", 2.0),
            ContextSection("task", "Task description", 1.5),
            ContextSection("history", "History content", 1.0),
        ]

        bucket_order = ["system", "task"]

        bucket_order_map, dropped_sections = assembler._build_context_by_order(
            sections, bucket_order
        )

        assert bucket_order_map["ordered"] == ["system", "task"]
        assert bucket_order_map["unordered"] == ["history"]
        assert len(dropped_sections) == 0

    def test_build_context_by_order_empty_sections(self):
        """Test building context by order with empty sections."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("system", "System prompt", 2.0),
            ContextSection("empty_section", "", 1.0),
            ContextSection("task", "Task description", 1.5),
        ]

        bucket_order = ["system", "empty_section", "task"]

        bucket_order_map, dropped_sections = assembler._build_context_by_order(
            sections, bucket_order
        )

        assert bucket_order_map["ordered"] == ["system", "task"]
        assert len(dropped_sections) == 1
        assert "empty_section" in dropped_sections

    def test_build_context_by_order_no_bucket_order(self):
        """Test building context by order without bucket order."""
        assembler = ContextAssembler()

        sections = [
            ContextSection("system", "System prompt", 2.0),
            ContextSection("empty_section", "", 1.0),
            ContextSection("task", "Task description", 1.5),
        ]

        bucket_order_map, dropped_sections = assembler._build_context_by_order(
            sections, None
        )

        assert len(bucket_order_map["ordered"]) == 2  # Only non-empty sections
        assert "system" in bucket_order_map["ordered"]
        assert "task" in bucket_order_map["ordered"]
        assert len(dropped_sections) == 1
        assert "empty_section" in dropped_sections

    def test_join_context_parts(self):
        """Test joining context parts."""
        assembler = ContextAssembler()

        context_parts = [
            "First part",
            "Second part",
            "Third part",
        ]

        result = assembler._join_context_parts(context_parts)

        expected = "First part\n\nSecond part\n\nThird part"
        assert result == expected

    def test_join_context_parts_empty(self):
        """Test joining empty context parts."""
        assembler = ContextAssembler()

        result = assembler._join_context_parts([])
        assert result == ""

    def test_join_context_parts_with_whitespace(self):
        """Test joining context parts with extra whitespace."""
        assembler = ContextAssembler()

        context_parts = [
            "  First part  ",
            "",
            "Second part",
            "   ",
            "Third part  ",
        ]

        result = assembler._join_context_parts(context_parts)

        expected = "First part\n\nSecond part\n\nThird part"
        assert result == expected

    def test_get_context_stats_with_assembled_context(self):
        """Test getting context stats with assembled context."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "system", "System", 2.0, token_count=10, allocated_tokens=20
            ),
            ContextSection("task", "Task", 1.5, token_count=15, allocated_tokens=20),
        ]

        assembled_context = AssembledContext(
            sections=sections,
            total_tokens=25,
            placement_map={"ordered": ["system", "task"]},
            dropped_sections=[],
        )

        stats = assembler.get_context_stats(assembled_context)

        assert stats["total_tokens"] == 25
        assert stats["total_sections"] == 2
        assert stats["sections_by_order"]["ordered"] == 2
        assert stats["sections_by_order"]["unordered"] == 0
        assert len(stats["section_details"]) == 2

        # Check section details
        system_details = next(
            d for d in stats["section_details"] if d["name"] == "system"
        )
        assert system_details["tokens"] == 10
        assert system_details["allocated_tokens"] == 20
        assert system_details["budget_utilization"] == 0.5

    def test_get_context_stats_without_assembled_context(self):
        """Test getting context stats without assembled context (uses _last_result)."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "system", "System", 2.0, token_count=10, allocated_tokens=20
            ),
        ]

        assembled_context = AssembledContext(
            sections=sections,
            total_tokens=10,
            placement_map={"ordered": ["system"]},
            dropped_sections=[],
        )
        assembler._last_result = assembled_context

        stats = assembler.get_context_stats()

        assert stats["total_tokens"] == 10
        assert stats["total_sections"] == 1

    def test_get_context_stats_no_context_available(self):
        """Test getting context stats when no context is available."""
        assembler = ContextAssembler()

        stats = assembler.get_context_stats()
        assert stats == {}

    def test_to_messages_success(self):
        """Test converting assembled context to messages."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "system", "System prompt", 2.0, message_role=MessageRole.SYSTEM
            ),
            ContextSection(
                "task", "Task description", 1.5, message_role=MessageRole.USER
            ),
        ]

        assembled_context = AssembledContext(
            sections=sections,
            total_tokens=25,
            placement_map={"ordered": ["system", "task"]},
            dropped_sections=[],
        )
        assembler._last_result = assembled_context

        with patch(
            "dolphin.core.context_engineer.utils.message_formatter.MessageFormatter"
        ) as mock_formatter:
            mock_formatter_instance = Mock()
            mock_formatter_instance.to_openai_messages_simple.return_value = [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Task description"},
            ]
            mock_formatter.return_value = mock_formatter_instance

            messages = assembler.to_messages()

            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"

    def test_to_messages_no_context_available(self):
        """Test converting to messages when no context is available."""
        assembler = ContextAssembler()

        with pytest.raises(RuntimeError, match="No assembled context available"):
            assembler.to_messages()

    def test_to_dph_messages_success(self):
        """Test converting assembled context to DPH messages."""
        assembler = ContextAssembler()

        sections = [
            ContextSection(
                "system", "System prompt", 2.0, message_role=MessageRole.SYSTEM
            ),
            ContextSection(
                "task", "Task description", 1.5, message_role=MessageRole.USER
            ),
        ]

        assembled_context = AssembledContext(
            sections=sections,
            total_tokens=25,
            placement_map={"ordered": ["system", "task"]},
            dropped_sections=[],
        )
        assembler._last_result = assembled_context

        with patch(
            "dolphin.core.context_engineer.utils.message_formatter.MessageFormatter"
        ) as mock_formatter:
            mock_formatter_instance = Mock()
            mock_messages = Mock()
            mock_formatter_instance.to_dph_messages_simple.return_value = mock_messages
            mock_formatter.return_value = mock_formatter_instance

            result = assembler.to_dph_messages()

            assert result == mock_messages

    def test_compatibility_methods(self):
        """Test compatibility methods for backward compatibility."""
        assembler = ContextAssembler()

        # Test _apply_placement_policy
        sections = [
            ContextSection("system", "System", 2.0),
            ContextSection("task", "Task", 1.5),
        ]

        placement_policy = {"head": ["system"], "middle": ["task"]}
        result = assembler._apply_placement_policy(sections, placement_policy)

        assert result[0].placement == "head"
        assert result[1].placement == "middle"

        # Test _sort_sections
        sorted_sections = assembler._sort_sections(sections)
        assert sorted_sections[0].name == "system"  # Higher priority first

        # Test _build_context
        context, placement_map, dropped = assembler._build_context(sections)
        assert isinstance(context, str)
        # Should have 1 section in "middle" (task) and 1 in "head" (system)
        assert len(placement_map["middle"]) == 1
        assert len(placement_map["head"]) == 1
        assert len(dropped) == 0

        # Test apply_lost_in_middle_mitigation
        content_sections = {"system": "System", "task": "Task"}
        key_sections = ["system"]
        result = assembler.apply_lost_in_middle_mitigation(
            content_sections, key_sections
        )
        assert result["system"].startswith("IMPORTANT:")

        # Test create_excerpts_with_summary
        content = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        excerpt, summary = assembler.create_excerpts_with_summary(content)
        assert isinstance(excerpt, str)
        assert isinstance(summary, str)

    def test_edge_cases(self):
        """Test edge cases and error conditions."""
        assembler = ContextAssembler()

        # Test with empty content sections
        content_sections = {}
        budget_allocations = []

        result = assembler.assemble_context(content_sections, budget_allocations)

        assert isinstance(result, AssembledContext)
        assert len(result.sections) == 0
        assert result.total_tokens == 0

        # Test with None content
        sections = [ContextSection("test", None, 1.0)]
        processed = assembler._apply_token_limits(sections, {})
        assert len(processed) == 1

        # Test with zero allocated tokens
        section = ContextSection(
            name="test",
            content="Content",
            priority=1.0,
            token_count=50,
            allocated_tokens=0,
        )
        result = assembler._compress_section(section)
        assert (
            result == ""
        )  # Should return empty string when allocated_tokens is 0 (truncated to 0 tokens)

    def test_integration_with_real_tokenizer(self):
        """Test integration with real tokenizer service."""
        assembler = ContextAssembler()

        content_sections = {
            "system": "You are a helpful assistant.",
            "task": "Help me understand Python programming.",
            "history": "User: How do I learn Python?\nAssistant: Start with basics.",
        }

        budget_allocations = [
            BudgetAllocation("system", 100, 2.0),
            BudgetAllocation("task", 150, 1.5),
            BudgetAllocation("history", 200, 1.0),
        ]

        result = assembler.assemble_context(content_sections, budget_allocations)

        assert isinstance(result, AssembledContext)
        assert len(result.sections) == 3
        assert result.total_tokens > 0

        # Verify token counts are calculated correctly
        for section in result.sections:
            expected_tokens = assembler.tokenizer.count_tokens(section.content)
            assert section.token_count == expected_tokens
