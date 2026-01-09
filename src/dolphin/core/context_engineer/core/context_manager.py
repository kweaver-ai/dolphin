"""Incremental context manager for dynamic context assembly and compression.

Incremental context manager supporting dynamic updates, incremental assembly, and controllable compression.
"""

from typing import Dict, List, Optional, Set, Any, Union
from dataclasses import dataclass, field
from dolphin.core.common.enums import Messages, MessageRole
from dolphin.core.context_engineer.config.settings import (
    get_default_config,
    ContextConfig,
)
from dolphin.core.context_engineer.core.context_assembler import (
    AssembledContext,
)
from dolphin.core.context_engineer.services.compressor import Compressor
from dolphin.core.context_engineer.utils.token_utils import truncate_to_tokens
from dolphin.core.context_engineer.utils.message_formatter import (
    MessageFormatter,
)

from dolphin.core.context_engineer.core.tokenizer_service import (
    TokenizerService,
)
from dolphin.core.common.exceptions import ContextEngineerException
from dolphin.core.logging.logger import get_logger

logger = get_logger("context_engineer.context_manager")


DEFAULT_ALLOCATED_TOKENS = 1024


@dataclass
class ContextBucket:
    """Represents a context bucket with dynamic content, used for managing different types and priorities of context content.

        A context bucket is the fundamental unit for context management. Each bucket contains specific content, priority, and related metadata,
        used for sorting and selecting during the construction of the final context.

        Attributes:
            name (str): The bucket name, used to uniquely identify a context bucket
            content (Union[str, Messages]): The content of the bucket, which can be a plain text string or a Messages object
            priority (float): The priority of the bucket, with higher values indicating greater importance, used for sorting and selection
            token_count (int): The number of tokens in the content, used to calculate context size
            allocated_tokens (int): The token budget allocated to this bucket, used to control content size
            message_role (MessageRole): The message role, defining the role of the content in the conversation (e.g., user, system, etc.)
            is_dirty (bool): Dirty flag, indicating whether the content has been modified and needs to have its token count recalculated
            is_compressed (bool): Compression flag, indicating whether the content has already been compressed
    """

    name: str
    content: Union[str, Messages]
    priority: float
    token_count: int = 0
    allocated_tokens: int = 0
    message_role: MessageRole = MessageRole.USER
    is_dirty: bool = True
    is_compressed: bool = False

    def _is_messages_type(self) -> bool:
        """Check if content is of Messages type"""
        return isinstance(self.content, Messages)

    def _get_content_text(self) -> str:
        """Get the text representation of content"""
        if self._is_messages_type() and isinstance(self.content, Messages):
            # If it is a Messages type, extract the content of all messages and concatenate them.
            contents = []
            for msg in self.content.messages:
                if hasattr(msg, "content") and msg.content:
                    contents.append(str(msg.content))
            return "\n".join(contents)
        else:
            # If it is a string type, return directly.
            return str(self.content)

    def _merge_messages(
        self, new_content: Union[str, Messages]
    ) -> Union[str, Messages]:
        """Merge Messages content"""
        if not self._is_messages_type() or not isinstance(new_content, Messages):
            return new_content

        # Merge Messages
        merged_messages = Messages()
        if isinstance(self.content, Messages):
            merged_messages.extend_messages(self.content)
        if isinstance(new_content, Messages):
            merged_messages.extend_messages(new_content)

        return merged_messages


@dataclass
class ContextState:
    """Current state of the context assembly.

        Context assembly's current state.

        Attributes:
            buckets (Dict[str, ContextBucket]): Dictionary of buckets
            total_tokens (int): Total number of tokens
            layout_policy (str): Layout policy
            bucket_order (List[str]): Order of buckets
            dirty_buckets (Set[str]): Set of buckets that need to be updated
    """

    buckets: Dict[str, ContextBucket] = field(default_factory=dict)
    total_tokens: int = 0
    layout_policy: str = "default"
    bucket_order: List[str] = field(default_factory=list)
    dirty_buckets: Set[str] = field(default_factory=set)


class SimpleContextSection:
    def __init__(self, name, content, message_role):
        self.name = name
        self.content = content
        self.message_role = message_role


class SimpleAssembledContext(AssembledContext):
    def __init__(self, sections, assembled_context, bucket_order):
        self.sections = sections
        self.total_tokens = assembled_context["total_tokens"]
        self.placement_map = {
            "ordered": (
                bucket_order
                if bucket_order
                else list(assembled_context["sections"].keys())
            )
        }


class ContextManager:
    """Manages context assembly with incremental updates and controlled compression.

        Manages context assembly with incremental updates and controlled compression.
    """

    def __init__(
        self,
        tokenizer_service: Optional[TokenizerService] = None,
        compressor_service: Optional[Any] = None,
        context_config: Optional[ContextConfig] = None,
    ):
        """Initialize incremental context manager.

                Initialize incremental context manager.

        Args:
            tokenizer_service: TokenizerService instance
            compressor_service: Compressor service
            context_config: Context configuration
        """
        self.tokenizer = tokenizer_service or TokenizerService()
        self.compressor = compressor_service or Compressor()
        self.context_config = context_config or get_default_config()
        self.state = ContextState()
        self._message_formatter = MessageFormatter()

        # Initialize with default policy if available
        if "default" in self.context_config.policies:
            self.set_layout_policy("default")

    def add_bucket(
        self,
        bucket_name: str,
        content: Union[str, Messages],
        priority: float = 1.0,
        allocated_tokens: Optional[int] = None,
        message_role: Optional[MessageRole] = None,
    ) -> None:
        """Add or update a context bucket.

                Add or update a context bucket.

        Args:
            bucket_name: Bucket name
            content: Content, supports string or Messages type
            priority: Priority
            allocated_tokens: Allocated token count
            message_role: Message role
        """
        # Get bucket configuration
        bucket_config = self.context_config.buckets.get(bucket_name)

        # Set default values
        if allocated_tokens is None:
            allocated_tokens = (
                getattr(bucket_config, "max_tokens", DEFAULT_ALLOCATED_TOKENS)
                if bucket_config
                else DEFAULT_ALLOCATED_TOKENS
            )

        if message_role is None:
            message_role = (
                bucket_config.message_role if bucket_config else MessageRole.USER
            )

        # Create or update bucket
        if bucket_name in self.state.buckets:
            # Update existing bucket
            bucket = self.state.buckets[bucket_name]

            # Check whether content update is needed
            needs_update = False
            if bucket.content != content:
                # If it is a Messages type, perform merging processing.
                if bucket._is_messages_type() and isinstance(content, Messages):
                    bucket.content = bucket._merge_messages(content)
                else:
                    bucket.content = content
                needs_update = True
                bucket.is_compressed = False

            if needs_update:
                bucket.is_dirty = True
                # Calculate token count immediately
                bucket.token_count = self._count_tokens_for_content(bucket.content)

            if bucket.priority != priority:
                bucket.priority = priority
            if bucket.allocated_tokens != allocated_tokens:
                bucket.allocated_tokens = allocated_tokens or 0
                bucket.is_dirty = True
        else:
            # Create new bucket
            bucket = ContextBucket(
                name=bucket_name,
                content=content,
                priority=priority,
                allocated_tokens=allocated_tokens or 0,
                message_role=message_role,
            )
            # Calculate token count immediately
            bucket.token_count = self._count_tokens_for_content(content)
            self.state.buckets[bucket_name] = bucket

        # Marked for update
        self.state.dirty_buckets.add(bucket_name)
        # Need to recalculate total token count
        self._calculate_total_tokens()

    def _count_tokens_for_content(self, content: Union[str, Messages]) -> int:
        """Calculate the number of tokens in the content, supporting both string and Messages types."""
        if isinstance(content, Messages):
            # If it is a Messages type, extract the content of all messages and calculate tokens after concatenation.
            contents = []
            for msg in content.messages:
                if hasattr(msg, "content") and msg.content:
                    contents.append(str(msg.content))
            text_content = "\n".join(contents)
            return self.tokenizer.count_tokens(text_content)
        else:
            # If it is a string type, calculate the token directly.
            return self.tokenizer.count_tokens(str(content))

    def remove_bucket(self, bucket_name: str) -> None:
        """Remove a context bucket.

                Remove a context bucket.

        Args:
            bucket_name: Bucket name
        """
        if bucket_name in self.state.buckets:
            del self.state.buckets[bucket_name]
            self.state.dirty_buckets.discard(bucket_name)
            self.state.total_tokens = 0
            # Need to recalculate total token count
            self._calculate_total_tokens()

    def update_bucket_content(
        self, bucket_name: str, content: Union[str, Messages]
    ) -> None:
        """Update bucket content only.

                Update bucket content only.

        Args:
            bucket_name: Bucket name
            content: New content, supports string or Messages type
        """
        if bucket_name in self.state.buckets:
            bucket = self.state.buckets[bucket_name]
            if bucket.content != content:
                # If it is a Messages type, perform merging processing.
                if bucket._is_messages_type() and isinstance(content, Messages):
                    bucket.content = bucket._merge_messages(content)
                else:
                    bucket.content = content
                bucket.is_dirty = True
                bucket.is_compressed = False
                # Calculate token count immediately
                bucket.token_count = self._count_tokens_for_content(bucket.content)
                self.state.dirty_buckets.add(bucket_name)
                # Need to recalculate total token count
                self._calculate_total_tokens()

    def replace_bucket_content(
        self, bucket_name: str, content: Union[str, Messages]
    ) -> None:
        """Replace bucket content directly without merging.

                Directly replace bucket content without merging, used in scenarios where content must strictly match external state (e.g., history).

        Args:
            bucket_name: Bucket name
            content: New content, supports string or Messages type
        """
        if bucket_name in self.state.buckets:
            bucket = self.state.buckets[bucket_name]
            bucket.content = content
            bucket.is_dirty = True
            bucket.is_compressed = False
            bucket.token_count = self._count_tokens_for_content(bucket.content)
            self.state.dirty_buckets.add(bucket_name)
            self._calculate_total_tokens()

    def set_layout_policy(self, policy_name: str) -> None:
        """Set layout policy and bucket order.

                Set the layout policy and bucket order.

        Args:
            policy_name: Policy name
        """
        policy = self.context_config.policies.get(policy_name)
        if policy:
            self.state.layout_policy = policy_name
            self.state.bucket_order = policy.bucket_order
            self.state.total_tokens = 0  # Need to recalculate

    def get_token_stats(self) -> Dict[str, Any]:
        """Get current token usage statistics.

                Get current token usage statistics.

        Returns:
            Dictionary of statistics
        """
        self._update_dirty_buckets()

        stats = {
            "total_tokens": self.state.total_tokens,
            "bucket_count": len(self.state.buckets),
            "buckets": {},
            "compression_needed": False,
        }

        for name, bucket in self.state.buckets.items():
            stats["buckets"][name] = {
                "tokens": bucket.token_count,
                "allocated": bucket.allocated_tokens,
                "priority": bucket.priority,
                "is_compressed": bucket.is_compressed,
                "utilization": (
                    bucket.token_count / bucket.allocated_tokens
                    if bucket.allocated_tokens > 0
                    else 0
                ),
                "needs_compression": (
                    bucket.token_count > bucket.allocated_tokens
                    if bucket.allocated_tokens > 0
                    else False
                ),
            }

            if stats["buckets"][name]["needs_compression"]:
                stats["compression_needed"] = True

        return stats

    def needs_compression(self) -> bool:
        """Check if compression is needed.

                Check if compression is needed.

        Returns:
            Whether compression is needed
        """
        stats = self.get_token_stats()
        return stats["compression_needed"]

    def compress_bucket(self, bucket_name: str, method: Optional[str] = None) -> bool:
        """Compress a specific bucket.

                Compress a specific bucket.

        Args:
            bucket_name: Bucket name
            method: Compression method

        Returns:
            Whether the compression was successful
        """
        if bucket_name not in self.state.buckets:
            logger.warning(f"Bucket {bucket_name} not found.")
            return False

        bucket = self.state.buckets[bucket_name]
        # Check if compression is needed
        if bucket.token_count <= bucket.allocated_tokens:
            return True  # No compression needed, but return success

        # Get compression method
        if method is None:
            bucket_config = self.context_config.buckets.get(bucket_name)
            method = getattr(bucket_config, "compress", None) if bucket_config else None

        try:
            # Using Compressor Service
            if self.compressor and method:
                result = self.compressor.compress(
                    content=bucket.content,
                    target_tokens=bucket.allocated_tokens,
                    method=method,
                )
                bucket.content = result.compressed_content
            else:
                # Fallback to simple truncation

                bucket.content = truncate_to_tokens(
                    bucket.content, bucket.allocated_tokens, self.tokenizer
                )

            # Update token count
            bucket.token_count = self._count_tokens_for_content(bucket.content)
            bucket.is_compressed = True
            bucket.is_dirty = False
            self.state.dirty_buckets.discard(bucket_name)

            # Recalculate total token count
            self._calculate_total_tokens()

            return True

        except Exception as e:
            logger.error(f"Failed to compress bucket '{bucket_name}': {e}")
            raise ContextEngineerException(message="Failed to compress bucket")

    def compress_all(self) -> Dict[str, bool]:
        """Compress all buckets that need compression.

                Compress all buckets that need compression.

        Returns:
            Dictionary of compression results for each bucket
        """
        results = {}

        for bucket_name in self.state.buckets:
            results[bucket_name] = self.compress_bucket(bucket_name)

        return results

    def assemble_context(self) -> Dict[str, Any]:
        """Assemble the final context.

                Assemble the final context.

        Returns:
            Assembly result
        """
        self._update_dirty_buckets()

        # Sort by bucket order
        ordered_buckets = self._get_ordered_buckets()

        # Build content dictionary
        content_sections = {}
        for bucket in ordered_buckets:
            # Correctly handle Messages type and string type content
            if isinstance(bucket.content, Messages):
                # For the Messages type, check if there is a message and it is not empty
                if bucket.content.messages:
                    content_sections[bucket.name] = bucket.content
            else:
                # For string types, check whether it contains non-empty content
                content_str = str(bucket.content)
                if content_str.strip():
                    content_sections[bucket.name] = bucket.content

        return {
            "sections": content_sections,
            "total_tokens": self.state.total_tokens,
            "bucket_order": [b.name for b in ordered_buckets],
            "layout_policy": self.state.layout_policy,
        }

    def to_messages(
        self, user_buckets: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """Convert to message format.

                Convert to message format.

        Args:
            user_buckets: List of user role buckets

        Returns:
            List of messages
        """

        assembled_context = self.assemble_context()

        # Create a simplified context structure for use by formatters

        # Create section objects in the order specified by bucket_order
        sections_list = []

        # Get bucket order
        bucket_order = assembled_context.get("bucket_order", [])
        if bucket_order:
            # Process in the order of bucket_order
            for bucket_name in bucket_order:
                if bucket_name in assembled_context["sections"]:
                    content = assembled_context["sections"][bucket_name]
                    bucket = self.state.buckets.get(bucket_name)
                    if bucket:
                        section = SimpleContextSection(
                            bucket_name, content, bucket.message_role
                        )
                        sections_list.append(section)
        else:
            # If there is no bucket_order, use the original order
            for name, content in assembled_context["sections"].items():
                bucket = self.state.buckets.get(name)
                if bucket:
                    section = SimpleContextSection(name, content, bucket.message_role)
                    sections_list.append(section)

        simple_context = SimpleAssembledContext(
            sections_list, assembled_context, bucket_order
        )
        return self._message_formatter.to_openai_messages_simple(
            simple_context,
            user_sections=user_buckets,
        )

    def to_dph_messages(self) -> Messages:
        """Convert to DPH message format.

                Convert to DPH message format.

        Returns:
            DPH message object
        """

        assembled_context = self.assemble_context()

        # Get bucket order
        bucket_order = assembled_context.get("bucket_order", [])

        # Create a list of section objects
        sections_list = []

        if bucket_order:
            # Process in the order of bucket_order
            for bucket_name in bucket_order:
                if bucket_name in assembled_context["sections"]:
                    content = assembled_context["sections"][bucket_name]
                    bucket = self.state.buckets.get(bucket_name)
                    if bucket:
                        section = SimpleContextSection(
                            bucket_name, content, bucket.message_role
                        )
                        sections_list.append(section)
        else:
            # If there is no bucket_order, use the original order
            for name, content in assembled_context["sections"].items():
                bucket = self.state.buckets.get(name)
                if bucket:
                    section = SimpleContextSection(name, content, bucket.message_role)
                    sections_list.append(section)

        simple_context = SimpleAssembledContext(
            sections_list, assembled_context, bucket_order
        )

        return self._message_formatter.to_dph_messages_simple(
            simple_context,
        )

    def _update_dirty_buckets(self) -> None:
        """Update token counts for dirty buckets."""
        if not self.state.dirty_buckets:
            return

        for bucket_name in list(self.state.dirty_buckets):
            if bucket_name in self.state.buckets:
                bucket = self.state.buckets[bucket_name]
                bucket.token_count = self._count_tokens_for_content(bucket.content)
                bucket.is_dirty = False

        self.state.dirty_buckets.clear()
        self._calculate_total_tokens()

    def _calculate_total_tokens(self) -> None:
        """Calculate total tokens across all buckets."""
        self.state.total_tokens = sum(
            bucket.token_count for bucket in self.state.buckets.values()
        )

    def _get_ordered_buckets(self) -> List[ContextBucket]:
        """Get buckets ordered by layout policy."""
        buckets = list(self.state.buckets.values())

        if not self.state.bucket_order:
            # Sort by priority
            return sorted(buckets, key=lambda b: -b.priority)

        # Sort by bucket order
        bucket_index = {name: idx for idx, name in enumerate(self.state.bucket_order)}
        return sorted(
            buckets,
            key=lambda b: (
                bucket_index.get(b.name, len(self.state.bucket_order)),
                -b.priority,
            ),
        )

    def clear(self) -> None:
        """Clear all context data."""
        self.state = ContextState()
        # Ensure the total number of tokens is 0
        self.state.total_tokens = 0

    def get_bucket_names(self) -> List[str]:
        """Get all bucket names."""
        return list(self.state.buckets.keys())

    def has_bucket(self, bucket_name: str) -> bool:
        """Check if bucket exists."""
        return bucket_name in self.state.buckets
