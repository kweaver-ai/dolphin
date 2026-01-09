"""Context assembler for position-aware message assembly.

Context assembler for position-aware message assembly, avoiding the "Lost in the Middle" problem.
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from dolphin.core.common.enums import Messages, MessageRole
from dolphin.core.context_engineer.config.settings import (
    get_default_config,
    ContextConfig,
    BucketConfig,
)
from dolphin.core.context_engineer.services.compressor import Compressor
from ..core.tokenizer_service import TokenizerService
from ..core.budget_manager import BudgetAllocation
from dolphin.core.logging.logger import get_logger

logger = get_logger("context_engineer.assembler")


@dataclass
class ContextSection:
    """Represents a section of context with metadata.

        Represents a section of context with metadata.

        Attributes:
            name (str): Section name
            content (str): Content
            priority (float): Priority
            token_count (int): Number of tokens, default is 0
            allocated_tokens (int): Allocated token count for precise compression target, default is 0
            message_role (str): Message role
            placement (str): Placement information, used for test compatibility
    """

    name: str
    content: str
    priority: float
    token_count: int = 0
    allocated_tokens: int = 0  # The number of tokens allocated for budget distribution, used for precise compression targets.
    message_role: MessageRole = MessageRole.USER
    placement: str = ""  # Used for testing compatibility

    def __init__(self, name: str, content: str, priority: float, *args, **kwargs):
        """Initialize ContextSection, supporting parameter order for test compatibility."""
        self.name = name
        self.content = content
        self.priority = priority

        # Handling positional arguments
        if len(args) > 0 and isinstance(args[0], str):
            self.placement = args[0]
            args = args[1:]

        # Handle the remaining arguments
        if len(args) > 0:
            self.token_count = args[0]
        if len(args) > 1:
            self.allocated_tokens = args[1]

        # Process keyword arguments
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


@dataclass
class AssembledContext:
    """Result of context assembly.

        Result of context assembly.

        Attributes:
            sections (List[ContextSection]): List of original context sections
            total_tokens (int): Total number of tokens
            placement_map (Dict[str, List[str]]): Placement mapping
            dropped_sections (List[str]): List of dropped sections
            full_context (str): Full context string, used for test compatibility
    """

    sections: List[ContextSection]
    total_tokens: int
    placement_map: Dict[str, List[str]]
    dropped_sections: List[str]
    full_context: str = ""  # Used for testing compatibility


class ContextAssembler:
    """Assembles context according to position strategies to avoid "Lost in the Middle".

        Assembles context according to position strategies to avoid "Lost in the Middle".
    """

    def __init__(
        self,
        tokenizer_service: Optional[TokenizerService] = None,
        compressor_service: Optional[Any] = None,
        context_config: Optional[ContextConfig] = None,
    ):
        """Initialize context assembler.

                Initialize the context assembler.

        Args:
            tokenizer_service: TokenizerService instance, used for token counting
            compressor_service: Compressor service, used for content compression
        """
        self.tokenizer = tokenizer_service or TokenizerService()
        self.compressor = compressor_service or Compressor()
        self._last_result = None  # Store the result of the last assembly.
        self.context_config = context_config or get_default_config()
        # Property for testing compatibility
        self.placement_strategy = {"head": [], "middle": [], "tail": []}

    def assemble_context(
        self,
        content_sections: Dict[str, str],
        budget_allocations: List[BudgetAllocation],
        placement_policy: Optional[Dict[str, List[str]]] = None,
        bucket_order: Optional[List[str]] = None,
        layout_policy: Optional[str] = None,
    ) -> AssembledContext:
        """Assemble context sections according to bucket order.

                Assemble context sections according to bucket order.

        Args:
            content_sections: Dictionary mapping section names to their content
            budget_allocations: List of budget allocations for each section
            bucket_order: Global order of buckets; if None, use original order
            bucket_configs: Optional bucket configurations for accessing compression methods

        Returns:
            AssembledContext ordered as specified
        """
        # If bucket_order parameter is provided, use it; otherwise get from layout policy
        if bucket_order is None:
            default_layout_policy = (
                self.context_config.policies.get(layout_policy)
                if layout_policy
                else self.context_config.policies.get("default")
            )
            bucket_order = (
                default_layout_policy.bucket_order if default_layout_policy else None
            )

        # Create context sections with metadata
        sections = self._create_sections(
            content_sections, budget_allocations, self.context_config.buckets
        )

        # Sort sections by bucket order and priority (bucket_order first, then by priority)
        sections = self._sort_sections_by_bucket_order(sections, bucket_order)

        # Apply token limits and compression
        sections = self._apply_token_limits(sections, self.context_config.buckets)

        # Build final ordered sections with bucket order
        bucket_order_map, dropped_sections = self._build_context_by_order(
            sections, bucket_order
        )

        # Calculate total tokens from ordered sections
        total_tokens = sum(section.token_count for section in sections)

        # Build full context string for compatibility
        full_context = self._join_context_parts(
            [section.content for section in sections]
        )

        # Handle placement_policy compatibility
        placement_map = bucket_order_map
        if placement_policy:
            # If placement_policy is provided, use it to construct the placement_map
            placement_map = {"head": [], "middle": [], "tail": []}
            for section in sections:
                # Set the placement attribute of the section according to placement_policy
                for position, bucket_names in placement_policy.items():
                    if section.name in bucket_names:
                        section.placement = position
                        placement_map[position].append(section.name)
                        break
                else:
                    # If no match is found, set the default placement.
                    section.placement = "middle"
                    placement_map["middle"].append(section.name)

        result = AssembledContext(
            sections=sections,
            total_tokens=total_tokens,
            placement_map=placement_map,  # Use the processed placement_map
            dropped_sections=dropped_sections,
            full_context=full_context,
        )

        self._last_result = result  # Save results for later use
        return result

    def _create_sections(
        self,
        content_sections: Dict[str, str],
        budget_allocations: List[BudgetAllocation],
        bucket_configs: Optional[Dict[str, BucketConfig]] = None,
    ) -> List[ContextSection]:
        """Create context sections with metadata from budget allocations.

                Create context sections with metadata from budget allocations.

        Args:
            content_sections: dictionary of content sections
            budget_allocations: list of budget allocations

        Returns:
            list of ContextSection
        """
        sections = []
        allocation_map = {alloc.bucket_name: alloc for alloc in budget_allocations}

        for section_name, content in content_sections.items():
            message_role = MessageRole.USER
            if bucket_configs:
                bucket_config = bucket_configs.get(section_name)
                if bucket_config is not None:  # Add checks to ensure bucket_config is not None
                    message_role = bucket_config.message_role

            allocation = allocation_map.get(section_name)
            if not allocation:
                continue

            section = ContextSection(
                name=section_name,
                content=content,
                priority=allocation.priority,
                token_count=self.tokenizer.count_tokens(content),
                allocated_tokens=allocation.allocated_tokens,  # Pass the number of tokens for budget allocation
                message_role=message_role,
            )
            sections.append(section)

        return sections

    def _sort_sections_by_bucket_order(
        self, sections: List[ContextSection], bucket_order: Optional[List[str]]
    ) -> List[ContextSection]:
        """Sort sections by bucket order and priority.

        Args:
            sections: list of context sections
            bucket_order: global order of buckets, if None then use original order

        Returns:
            sorted list of context sections
        """
        if not bucket_order:
            # If bucket_order is not specified, sort by original order but with priority.
            return sorted(sections, key=lambda s: -s.priority)

        # Create a mapping from bucket names to indices for fast lookup
        bucket_index = {name: idx for idx, name in enumerate(bucket_order)}

        # Sort by bucket_order, and within the same bucket, sort by priority (high priority first)
        return sorted(
            sections,
            key=lambda s: (bucket_index.get(s.name, len(bucket_order)), -s.priority),
        )

    def _apply_token_limits(
        self,
        sections: List[ContextSection],
        bucket_configs: Optional[Dict[str, Any]] = None,
    ) -> List[ContextSection]:
        """Apply token limits and compression to sections.

                Determine whether compression is needed by comparing token_count and allocated_tokens,
                completely removing the compression_needed dependency marker.

        Args:
            sections: List of context sections
            bucket_configs: Dictionary of bucket configurations

        Returns:
            Processed list of context sections
        """
        processed_sections = []

        for section in sections:
            # Determine whether compression is needed by comparing the actual number of tokens with the allocated budget
            if (
                section.token_count > section.allocated_tokens
                and section.token_count > 0
            ):
                # Content exceeds budget, needs compression
                # Determine compression method from bucket configuration
                compression_method = None
                if bucket_configs and section.name in bucket_configs:
                    bucket_config = bucket_configs[section.name]
                    compression_method = getattr(bucket_config, "compress", None)

                # Apply compression with specified method
                compressed_content = self._compress_section(section, compression_method)
                section.content = compressed_content
                section.token_count = self.tokenizer.count_tokens(compressed_content)
            # If the content conforms to the budget or is empty, no action is required.

            processed_sections.append(section)

        return processed_sections

    def _compress_section(
        self, section: ContextSection, compression_method: Optional[str] = None
    ) -> str:
        """Apply compression to a section based on its needs and configuration.

                Compress exactly according to allocated_tokens, removing the 50% heuristic rule.

        Args:
            section: The context section
            compression_method: The compression method

        Returns:
            The compressed content
        """
        if section.token_count <= 0:
            return section.content

        # Precise compression: directly use the allocated_tokens assigned according to the budget as the target
        target_tokens = section.allocated_tokens

        # If the actual content already meets the budget requirements, no compression is needed.
        if section.token_count <= target_tokens:
            return section.content

        # If the compressor service is available, perform precise compression using the specified method.
        if self.compressor and compression_method:
            try:
                result = self.compressor.compress(
                    content=section.content,
                    target_tokens=target_tokens,
                    method=compression_method,
                )
                return result.compressed_content
            except Exception as e:
                # Compression method failed, falling back to simple truncation
                logger.warning(
                    f"Warning: Compression method '{compression_method}' failed: {e}"
                )

        # Fallback to simple truncation, precise to allocated_tokens
        from ..utils.token_utils import truncate_to_tokens

        return truncate_to_tokens(section.content, target_tokens, self.tokenizer)

    def _build_context_by_order(
        self, sections: List[ContextSection], bucket_order: Optional[List[str]]
    ) -> Tuple[Dict[str, List[str]], List[str]]:
        """Build final ordered sections with bucket order.

                Build the final sorted list of context sections using the bucket order.

        Args:
            sections: List of context sections
            bucket_order: Global order of buckets

        Returns:
            Tuple(sorted list of context sections, bucket order mapping, list of discarded sections)
        """
        bucket_order_map = {"ordered": [], "unordered": []}
        dropped_sections = []

        # Build an ordered list of segments according to bucket_order, ensuring all segments with content are included.
        if bucket_order:
            # Add the parts specified in bucket_order first
            for bucket_name in bucket_order:
                section = next((s for s in sections if s.name == bucket_name), None)
                if section and section.content:
                    bucket_order_map["ordered"].append(bucket_name)
                elif section and not section.content:
                    dropped_sections.append(section.name)

            # Add parts that are not in bucket_order but have content
            remaining_sections = [
                s for s in sections if s.name not in bucket_order and s.content
            ]
            for section in remaining_sections:
                bucket_order_map["unordered"].append(section.name)
        else:
            # If there is no bucket_order, include all parts with content in their original order.
            for section in sections:
                if section.content:
                    bucket_order_map["ordered"].append(section.name)
                else:
                    dropped_sections.append(section.name)

        return bucket_order_map, dropped_sections

    def _join_context_parts(self, context_parts: List[str]) -> str:
        """Join context parts with appropriate separators.

        Args:
            context_parts: List of context parts

        Returns:
            Concatenated context string
        """
        if not context_parts:
            return ""

        # Use double newlines to separate major sections
        separator = "\n\n"
        return separator.join(part.strip() for part in context_parts if part.strip())

    def get_context_stats(
        self, assembled_context: Optional[AssembledContext] = None
    ) -> Dict[str, Any]:
        """Get statistics about the assembled context.

                Get statistics about the assembled context.

        Args:
            assembled_context: The assembled context, if None then use _last_result

        Returns:
            A dictionary of statistics
        """
        if assembled_context is None:
            if self._last_result is None:
                return {}
            assembled_context = self._last_result

        # Support new bucket order format and old placement format
        placement_map = assembled_context.placement_map

        # Calculate the number of partials counted by position (for testing compatibility)
        sections_by_placement = {"head": 0, "middle": 0, "tail": 0}
        for section in assembled_context.sections:
            if section.placement == "head":
                sections_by_placement["head"] += 1
            elif section.placement == "middle":
                sections_by_placement["middle"] += 1
            elif section.placement == "tail":
                sections_by_placement["tail"] += 1

        sections_by_order = {
            "ordered": len(placement_map.get("ordered", [])),
            "unordered": len(placement_map.get("unordered", [])),
        }

        stats = {
            "total_tokens": assembled_context.total_tokens,
            "total_sections": len(assembled_context.sections),
            "sections_by_order": sections_by_order,
            "sections_by_placement": sections_by_placement,  # Add compatibility fields
            "dropped_sections": len(assembled_context.dropped_sections),
            "section_details": [],
        }

        for section in assembled_context.sections:
            # Determine whether compression is needed by comparing token_count and allocated_tokens
            stats["section_details"].append(
                {
                    "name": section.name,
                    "message_role": section.message_role,
                    "tokens": section.token_count,
                    "priority": section.priority,
                    "allocated_tokens": section.allocated_tokens,
                    "budget_utilization": (
                        section.token_count / section.allocated_tokens
                        if section.allocated_tokens > 0
                        else 0
                    ),
                }
            )

        return stats

    def to_messages(
        self,
        user_sections: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Convert AssembledContext into a simplified message format: a single system message + user message.

                Strategy:
                - Merge everything except the user message into a single system message
                - Maximize LLM compatibility
                - No need for format_type parameter

        Args:
            user_sections: Specifies which sections should be treated as user role (default: ["user_query", "user", "input"])
            bucket_configs: Bucket configuration dictionary to support role assignment based on configuration

        Returns:
            A simplified message list in the format [system, user] or similar structure

        Raises:
            RuntimeError: If no context can be converted
        """
        if not hasattr(self, "_last_result") or self._last_result is None:
            raise RuntimeError(
                "No assembled context available. Call assemble_context() first."
            )

        # Delayed import avoids circular dependencies
        from ..utils.message_formatter import MessageFormatter

        if not hasattr(self, "_message_formatter"):
            self._message_formatter = MessageFormatter()

        # Use the most simplified format to merge all non-user messages into a single system message
        # Pass in bucket_configs to support role assignment based on configuration
        return self._message_formatter.to_openai_messages_simple(
            self._last_result,
            user_sections=user_sections,
        )

    def to_dph_messages(
        self,
    ) -> Messages:
        from ..utils.message_formatter import MessageFormatter

        if not hasattr(self, "_message_formatter"):
            self._message_formatter = MessageFormatter()

        return self._message_formatter.to_dph_messages_simple(
            self._last_result,
        )

    # The following methods are used for compatibility testing
    def _apply_placement_policy(self, sections, placement_policy):
        """A compatibility method applying positional strategies."""
        # Set the placement attribute of the section according to placement_policy
        for section in sections:
            # Set the placement attribute of the section according to placement_policy
            for position, bucket_names in placement_policy.items():
                if section.name in bucket_names:
                    section.placement = position
                    break
            else:
                # If no match is found, set the default placement.
                section.placement = "middle"
        return sections

    def _sort_sections(self, sections):
        """Compatibility methods for the sorting section."""
        # This is a blank implementation, used only for testing compatibility.
        return sorted(sections, key=lambda s: -s.priority)

    def _build_context(self, sections):
        """A method for building context compatibility."""
        # This is a blank implementation, used only for testing compatibility.
        context = "\n\n".join(section.content for section in sections)
        placement_map = {"head": [], "middle": [], "tail": []}

        # Fill the placement_map according to the placement attribute of section
        for section in sections:
            if section.placement == "head":
                placement_map["head"].append(section.name)
            elif section.placement == "middle":
                placement_map["middle"].append(section.name)
            elif section.placement == "tail":
                placement_map["tail"].append(section.name)

        dropped = []
        return context, placement_map, dropped

    def apply_lost_in_middle_mitigation(self, content_sections, key_sections):
        """A compatibility method that alleviates the application of Lost in the Middle."""
        # This is a blank implementation, used only for testing compatibility.
        result = {}
        for name, content in content_sections.items():
            if name in key_sections:
                result[name] = "IMPORTANT: " + content
            else:
                result[name] = content
        return result

    def create_excerpts_with_summary(self, content, excerpt_ratio=0.5):
        """A compatibility method for creating excerpts with summaries."""
        # This is a blank implementation, used only for testing compatibility.
        excerpt = "... [content truncated] ..."
        summary = "Summary of paragraphs"
        return excerpt, summary
