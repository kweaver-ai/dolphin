from abc import ABC, abstractmethod
from datetime import datetime
import json
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

from dolphin.core.common.enums import (
    KnowledgePoint,
    MessageRole,
    Messages,
    CompressLevel,
)
from dolphin.core.config.global_config import (
    ContextEngineerConfig,
)
from dolphin.core.common.constants import (
    estimate_chars_from_tokens,
    estimate_tokens_from_chars,
)
from dolphin.core.context.context import Context
from dolphin.core.common.multimodal import (
    ImageTokenConfig,
)

if TYPE_CHECKING:
    from dolphin.core.config.global_config import (
        ContextConstraints,
        LLMInstanceConfig,
    )

from dolphin.core.logging.logger import get_logger

logger = get_logger("context_engineer")

# Default image token config for estimation
_default_image_config = ImageTokenConfig()


@dataclass
class CompressionResult:
    """Compressed result"""

    compressed_messages: Messages
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float
    strategy_used: str
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)


class CompressionStrategy(ABC):
    """Compress strategy abstract base class"""

    MEMORY_PREFIX = "Here are some knowledge points: "
    DATE_PREFIX = "今天日期是 "
    MESSAGE_FIXED_OVERHEAD_TOKENS = 6
    TOOL_CALL_FIXED_OVERHEAD_TOKENS = 4
    PRECISE_ESTIMATION_LOWER_RATIO = 0.85
    PRECISE_ESTIMATION_UPPER_RATIO = 1.05

    @abstractmethod
    def get_name(self) -> str:
        """Get strategy name"""
        pass

    @abstractmethod
    def estimate_tokens(self, messages: Messages) -> int:
        """Estimate the number of tokens in a message"""
        pass

    def preparation(
        self,
        context: Context,
        messages: Messages,
        constraints: "ContextConstraints",
        **kwargs,
    ) -> tuple[Messages, Messages, Messages, Messages]:
        """Preprocess message list
        
        Returns:
            Tuple of (system_messages, first_user_message, latest_user_message, other_messages)
            - system_messages: All system messages (must be first)
            - first_user_message: First user message after system (must be preserved for GLM API)
            - latest_user_message: Trailing latest user message in the current request (task anchor)
            - other_messages: Remaining messages for truncation/compression
        """
        system_messages = (
            messages.extract_system_messages()
            if constraints.preserve_system
            else Messages()
        )
        if (
            not self._date_in_system_message(system_messages)
            and context.get_var_value("_no_date_in_system_message", "false") != "true"
        ):
            system_messages.prepend_message(
                MessageRole.SYSTEM,
                f"{self.DATE_PREFIX} {datetime.now().strftime('%Y-%m-%d')}",
            )

        if context.get_config().context_engineer_config.import_mem and not kwargs.get(
            "knowledge_extraction", False
        ):
            knowledge_points = context.get_memory_manager().retrieve_relevant_memory(
                context=context, user_id=context.user_id
            )
            if knowledge_points and not self._knowledge_in_system_message(
                system_messages
            ):
                system_messages.append_message(
                    MessageRole.SYSTEM,
                    f"{self.MEMORY_PREFIX} {KnowledgePoint.to_prompt(knowledge_points)}",
                )
        non_system_messages = messages.extract_non_system_messages()

        # to meet the requirement of the deepseek-chat llm, remove the prefix of the messages if it is not the last message
        for i in range(len(non_system_messages)):
            if (
                non_system_messages[i].role == MessageRole.ASSISTANT
                and i != len(non_system_messages) - 1
            ):
                non_system_messages[i].metadata.pop("prefix", None)
        
        # Extract both first and latest user messages.
        # - first_user_message: required by GLM API (first non-system must be user)
        # - latest_user_message: required for preserving the current task anchor
        first_user_message = Messages()
        latest_user_message = Messages()
        other_messages = Messages()
        found_first_user = False
        latest_user_index = -1

        for idx in range(len(non_system_messages) - 1, -1, -1):
            if non_system_messages[idx].role == MessageRole.USER:
                latest_user_index = idx
                break
        
        last_non_system_index = len(non_system_messages) - 1

        for idx, msg in enumerate(non_system_messages):
            if not found_first_user and msg.role == MessageRole.USER:
                first_user_message.add_message(content=msg)
                found_first_user = True
                # If first and latest are the same message, do not duplicate.
                if idx == latest_user_index:
                    continue
            elif (
                msg.role == MessageRole.USER
                and idx == latest_user_index
                and idx == last_non_system_index
            ):
                latest_user_message.add_message(content=msg)
            else:
                other_messages.add_message(content=msg)
        
        return system_messages, first_user_message, latest_user_message, other_messages

    @abstractmethod
    def compress(
        self,
        context: Context,
        messages: Messages,
        constraints: "ContextConstraints",
        **kwargs,
    ) -> CompressionResult:
        """Compress message list

        Args:
            context: Context
            constraints: Compression constraints
            messages: Original message list

        Returns:
            CompressionResult: Compression result
        """
        pass

    def _date_in_system_message(self, system_messages: Messages) -> bool:
        """Determine whether the system message contains a date. If it does, return True; otherwise, return False."""
        for msg in system_messages:
            if msg.content and self.DATE_PREFIX in msg.content:
                return True
        return False

    def _estimate_tokens_with_structure(self, messages: Messages) -> int:
        """Fast token estimation with additional message-structure overhead."""
        total_tokens = 0
        for message in messages:
            total_tokens += self._estimate_single_message_tokens_fast(message)
        return total_tokens

    def _estimate_single_message_tokens_fast(self, message) -> int:
        """Estimate one message tokens including structure and tool metadata."""
        total_tokens = self.MESSAGE_FIXED_OVERHEAD_TOKENS
        total_tokens += estimate_tokens_from_chars(message.role.value)

        metadata = message.metadata or {}
        if metadata:
            total_tokens += estimate_tokens_from_chars(
                self._safe_json_dumps(metadata)
            )

        content = message.content
        if isinstance(content, str):
            total_tokens += estimate_tokens_from_chars(content)
        elif isinstance(content, list):
            for block in content:
                block_type = block.get("type")
                if block_type == "text":
                    total_tokens += estimate_tokens_from_chars(block.get("text", ""))
                elif block_type == "image_url":
                    detail = block.get("image_url", {}).get("detail", "auto")
                    total_tokens += _default_image_config.estimate_tokens(detail=detail)
                else:
                    total_tokens += estimate_tokens_from_chars(
                        self._safe_json_dumps(block)
                    )
        else:
            total_tokens += estimate_tokens_from_chars(str(content))

        if message.tool_calls:
            total_tokens += self.TOOL_CALL_FIXED_OVERHEAD_TOKENS
            total_tokens += estimate_tokens_from_chars(
                self._safe_json_dumps(message.tool_calls)
            )
        if message.tool_call_id:
            total_tokens += 1 + estimate_tokens_from_chars(message.tool_call_id)

        return total_tokens

    def _should_use_precise_count(self, estimated_tokens: int, budget_tokens: int) -> bool:
        """Use precise counting only when estimate is close to the budget boundary."""
        if budget_tokens <= 0:
            return False
        ratio = estimated_tokens / max(budget_tokens, 1)
        return self.PRECISE_ESTIMATION_LOWER_RATIO <= ratio <= self.PRECISE_ESTIMATION_UPPER_RATIO

    def _count_tokens_precise(self, context: Context, messages: Messages) -> Optional[int]:
        """Count tokens using tokenizer backend on serialized message payload."""
        try:
            from dolphin.core.context_engineer.core.tokenizer_service import TokenizerService

            backend = "auto"
            if context is not None:
                backend = context.get_config().context_engineer_config.tokenizer_backend

            tokenizer = TokenizerService(backend=backend)
            serialized = self._safe_json_dumps(messages.get_messages_as_dict())
            return tokenizer.count_tokens(serialized)
        except Exception as exc:
            logger.debug(f"Precise token counting failed, fallback to fast estimation: {exc}")
            return None

    @staticmethod
    def _safe_json_dumps(data: Any) -> str:
        """Serialize data safely for token estimation."""
        try:
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(data)

    def _knowledge_in_system_message(self, system_messages: Messages) -> bool:
        """Determine whether the system message contains knowledge. If it does, return True; otherwise, return False."""
        for msg in system_messages:
            if msg.content and self.MEMORY_PREFIX in msg.content:
                return True
        return False

    def _group_messages(self, messages: Messages) -> List[List]:
        """Group messages to preserve tool_calls/tool pairing.
        
        This method groups messages such that:
        - An assistant message with tool_calls is grouped with all subsequent tool messages
          that correspond to those tool_calls
        - Other messages (user, assistant without tools) form single-message groups
        
        This ensures that compression strategies never break the tool_calls/tool pairing
        which would cause API errors like:
        "messages with role 'tool' must be a response to a preceeding message with 'tool_calls'"
        
        Args:
            messages: The messages to group
            
        Returns:
            List of message groups, where each group is a list of SingleMessage objects.
            Groups should be kept together or dropped together during compression.
        """
        groups = []
        current_group = []
        expecting_tools = False
        expected_tool_ids = set()
        
        for msg in messages:
            is_tool_caller = (
                msg.role == MessageRole.ASSISTANT and 
                (msg.tool_calls or getattr(msg, 'function_call', None))
            )
            
            if is_tool_caller:
                # If we have a pending group, finalize it
                if current_group:
                    groups.append(current_group)
                
                # Start a new group with this assistant message
                current_group = [msg]
                expecting_tools = True
                
                # Collect expected tool_call_ids
                expected_tool_ids = set()
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                        if tc_id:
                            expected_tool_ids.add(tc_id)
                            
            elif msg.role == MessageRole.TOOL and expecting_tools:
                # Add tool message to current group
                current_group.append(msg)
                
                # Check if we've received all expected tools
                tool_call_id = msg.tool_call_id
                if tool_call_id in expected_tool_ids:
                    expected_tool_ids.discard(tool_call_id)
                
                # If all tools received, finalize the group
                if not expected_tool_ids:
                    groups.append(current_group)
                    current_group = []
                    expecting_tools = False
                    
            else:
                # Regular message (user, assistant without tools, etc.)
                # Finalize any pending group first
                if current_group:
                    groups.append(current_group)
                    current_group = []
                    expecting_tools = False
                    expected_tool_ids = set()
                
                # Single-message group
                groups.append([msg])
        
        # Don't forget the last group if any
        if current_group:
            groups.append(current_group)
        
        return groups

    def _flatten_groups(self, groups: List[List]) -> Messages:
        """Flatten message groups back into a Messages object.
        
        Args:
            groups: List of message groups
            
        Returns:
            Messages object containing all messages in order
        """
        result = Messages()
        for group in groups:
            for msg in group:
                result.add_message(content=msg)
        return result

    def _estimate_group_tokens(self, group: List) -> int:
        """Estimate the total tokens for a message group.
        
        Args:
            group: A list of SingleMessage objects
            
        Returns:
            Estimated token count for the entire group
        """
        temp_messages = Messages()
        for msg in group:
            temp_messages.add_message(content=msg)
        return self.estimate_tokens(temp_messages)
    
    def _count_images_in_messages(self, messages: Messages) -> int:
        """Count total number of images in a Messages object.
        
        Args:
            messages: Messages object to count images in
            
        Returns:
            Total number of images
        """
        total_images = 0
        for msg in messages:
            if isinstance(msg.content, list):
                total_images += sum(
                    1 for block in msg.content 
                    if block.get("type") == "image_url"
                )
        return total_images


class TruncationStrategy(CompressionStrategy):
    """Simple truncation strategy: keep the latest messages"""

    def get_name(self) -> str:
        return "truncation"

    def estimate_tokens(self, messages: Messages) -> int:
        """Estimate the number of tokens, including both text and image content."""
        return self._estimate_tokens_with_structure(messages)

    def compress(
        self,
        context: Context,
        constraints: "ContextConstraints",
        messages: Messages,
        **kwargs,
    ) -> CompressionResult:
        """Simple Truncation Compression"""
        if not messages:
            return CompressionResult(
                compressed_messages=Messages(),
                original_token_count=0,
                compressed_token_count=0,
                compression_ratio=1.0,
                strategy_used=self.get_name(),
            )

        system_messages, first_user_message, latest_user_message, other_messages = self.preparation(
            context, messages, constraints, **kwargs
        )
        # Combine for original token count calculation
        all_messages = Messages.combine_messages(
            Messages.combine_messages(
                Messages.combine_messages(system_messages, first_user_message),
                other_messages,
            ),
            latest_user_message,
        )

        max_tokens = constraints.max_input_tokens - constraints.reserve_output_tokens
        original_tokens = self.estimate_tokens(all_messages)
        if self._should_use_precise_count(original_tokens, max_tokens):
            precise_tokens = self._count_tokens_precise(context, all_messages)
            if precise_tokens is not None:
                logger.debug(
                    f"Using precise token count near budget boundary: fast={original_tokens}, precise={precise_tokens}, budget={max_tokens}"
                )
                original_tokens = precise_tokens

        if original_tokens <= max_tokens:
            return CompressionResult(
                compressed_messages=all_messages,
                original_token_count=original_tokens,
                compressed_token_count=original_tokens,
                compression_ratio=1.0,
                strategy_used=self.get_name(),
            )

        logger.debug(
            f"TruncationStrategy compress: original_tokens={original_tokens}, max_tokens={max_tokens} max_input_tokens={constraints.max_input_tokens} reserve_output_tokens={constraints.reserve_output_tokens}"
        )

        # Calculate the number of tokens in system messages and first user message (both preserved)
        system_tokens = self.estimate_tokens(system_messages)
        first_user_tokens = self.estimate_tokens(first_user_message)
        latest_user_tokens = self.estimate_tokens(latest_user_message)
        remaining_tokens = max_tokens - system_tokens - first_user_tokens - latest_user_tokens

        # Group messages to preserve tool_calls/tool pairing
        groups = self._group_messages(other_messages)
        
        # Keep from the latest groups backwards
        compressed_groups = []
        current_tokens = 0
        
        # Iterate backwards through groups
        for group in reversed(groups):
            group_tokens = self._estimate_group_tokens(group)
            
            if current_tokens + group_tokens <= remaining_tokens:
                compressed_groups.insert(0, group)
                current_tokens += group_tokens
            elif len(compressed_groups) == 0:
                # First group (latest) doesn't fit - try to truncate if it's a single text message
                if len(group) == 1 and isinstance(group[0].content, str):
                    chars_to_keep = estimate_chars_from_tokens(remaining_tokens)
                    if chars_to_keep > 0:
                        compressed_msg = group[0].copy()
                        compressed_msg.content = group[0].content[:chars_to_keep]
                        compressed_groups.insert(0, [compressed_msg])
                        current_tokens += remaining_tokens
                # Can't truncate (tool group or multimodal) - skip and stop
                break
            else:
                # Doesn't fit and not the first one -> stop
                break
        
        # Flatten groups back to messages
        compressed_other = self._flatten_groups(compressed_groups)

        # Merge Results: system + first_user + compressed_other + latest_user
        len_system_messages = len(system_messages)
        compressed_messages = system_messages.copy()
        # Add first user message (preserved)
        for msg in first_user_message:
            compressed_messages.add_message(content=msg)
        # Add compressed other messages (history)
        for msg in compressed_other:
            compressed_messages.add_message(
                content=msg
            )  # Preserve original message with all attributes
        # Add latest user message last (current query must be at the end)
        for msg in latest_user_message:
            compressed_messages.add_message(content=msg)
        final_tokens = self.estimate_tokens(compressed_messages)

        # Count images for logging
        original_images = self._count_images_in_messages(all_messages)
        compressed_images = self._count_images_in_messages(compressed_messages)
        dropped_images = original_images - compressed_images
        
        # Enhanced logging with image information
        if dropped_images > 0:
            logger.info(
                f"Compression dropped {dropped_images} image(s) "
                f"(kept {compressed_images}/{original_images}) due to token limit"
            )

        return CompressionResult(
            compressed_messages=compressed_messages,
            original_token_count=original_tokens,
            compressed_token_count=final_tokens,
            compression_ratio=(
                final_tokens / original_tokens if original_tokens > 0 else 1.0
            ),
            strategy_used=self.get_name(),
            metadata={
                "truncated_messages": len(other_messages) - len(compressed_other),
                "preserved_system_messages": len_system_messages,
                "preserved_first_user": len(first_user_message) > 0,
                "preserved_latest_user": len(latest_user_message) > 0,
                "original_images": original_images,
                "compressed_images": compressed_images,
                "dropped_images": dropped_images,
            },
        )


class LevelStrategy(CompressionStrategy):
    """Level compression strategy: compress all messages except the last one using normal compression level"""

    def get_name(self) -> str:
        return "level"

    def estimate_tokens(self, messages: Messages) -> int:
        """Estimate the number of tokens, including both text and image content."""
        return self._estimate_tokens_with_structure(messages)

    def compress(
        self,
        context: Context,
        constraints: "ContextConstraints",
        messages: Messages,
        **kwargs,
    ) -> CompressionResult:
        """Level compression: apply normal compression to all messages except the last one"""
        if not messages:
            return CompressionResult(
                compressed_messages=Messages(),
                original_token_count=0,
                compressed_token_count=0,
                compression_ratio=1.0,
                strategy_used=self.get_name(),
            )

        original_tokens = self.estimate_tokens(messages)

        # Get system, first user, and other messages
        system_messages, first_user_message, latest_user_message, other_messages = self.preparation(
            context, messages, constraints, **kwargs
        )

        # Apply compression to all other messages except the last two
        compressed_other = Messages()
        for i, msg in enumerate(other_messages):
            if i < len(other_messages) - 2:  # Not the last two messages
                # Create a copy and compress it
                compressed_msg = msg.copy()
                compressed_msg.compress(CompressLevel.NORMAL)
                compressed_other.add_message(content=compressed_msg)
            else:  # Last two messages, keep original
                compressed_other.add_message(content=msg)

        # Combine results: system + first_user + compressed_other + latest_user
        compressed_messages = Messages.combine_messages(
            Messages.combine_messages(
                Messages.combine_messages(system_messages, first_user_message),
                compressed_other,
            ),
            latest_user_message,
        )
        final_tokens = self.estimate_tokens(compressed_messages)

        return CompressionResult(
            compressed_messages=compressed_messages,
            original_token_count=original_tokens,
            compressed_token_count=final_tokens,
            compression_ratio=(
                final_tokens / original_tokens if original_tokens > 0 else 1.0
            ),
            strategy_used=self.get_name(),
            metadata={
                "compressed_messages": (
                    len(other_messages) - 1 if len(other_messages) > 0 else 0
                ),
                "preserved_system_messages": len(system_messages),
                "preserved_first_user": len(first_user_message) > 0,
                "preserved_latest_user": len(latest_user_message) > 0,
                "preserved_last_message": True,
            },
        )


class MessageCompressor:
    """Message compressor: responsible for compressing and pruning messages under constraints (original ContextEngineer)."""

    def __init__(
        self,
        config: Optional[ContextEngineerConfig] = None,
        context: Context = None,
    ):
        # Compatible with two types of configuration
        self.config = config or ContextEngineerConfig()
        self.context = context
        self.strategies = self._register_default_strategies()
        logger.debug(
            f"MessageCompressor initialized with strategy: {self.config.default_strategy}"
        )

    def _register_default_strategies(self) -> Dict[str, CompressionStrategy]:
        """Register default compression strategy"""
        strategies = {
            "level": LevelStrategy(),
            "truncation": TruncationStrategy(),
        }
        # Merge user-defined policy configurations
        for name, strategy_config in self.config.strategy_configs.items():
            # Here, corresponding strategy instances can be created based on strategy_config
            # Skip temporarily, keep extension interface
            pass
        return strategies

    def compress_messages(
        self,
        messages: Messages,
        strategy_name: Optional[str] = None,
        constraints: Optional["ContextConstraints"] = None,
        model_config: Optional["LLMInstanceConfig"] = None,
        **kwargs,
    ) -> CompressionResult:
        """Compress message context

        Args:
            messages: Original message list
            strategy_name: Specifies the compression strategy to use, default uses the default strategy in configuration
            constraints: Compression constraints, default uses constraints in configuration
            model_config: Model configuration, used to automatically adjust constraints

        Returns:
            CompressionResult: Compression result
        """
        # Select Strategy
        strategy_name = strategy_name or self.config.default_strategy
        if strategy_name not in self.strategies:
            # Migrate removed sliding_window_* strategies to truncation
            if strategy_name.startswith("sliding_window"):
                logger.warning(
                    "Strategy '%s' has been removed; falling back to 'truncation'.",
                    strategy_name,
                )
                strategy_name = "truncation"
            else:
                available = ", ".join(sorted(self.strategies.keys()))
                logger.warning(
                    "Unknown context strategy '%s' (available: %s); falling back to 'truncation'.",
                    strategy_name,
                    available,
                )
                strategy_name = "truncation"
                if strategy_name not in self.strategies:
                    self.strategies["truncation"] = TruncationStrategy()

        strategy = self.strategies[strategy_name]

        # Select constraint conditions; if model_config is provided, adjust constraints according to model capabilities.
        if constraints is None:
            constraints = self.config.constraints

            # Automatically adjust constraints according to model_config
            if model_config is not None:
                from dolphin.core.config.global_config import ContextConstraints

                # Dynamically create constraints suitable for the current model
                adjusted_constraints = ContextConstraints(
                    max_input_tokens=constraints.max_input_tokens,
                    reserve_output_tokens=model_config.max_tokens,  # Use the model's max_tokens as reserved output
                    preserve_system=constraints.preserve_system,
                )
                constraints = adjusted_constraints

                logger.debug(
                    f"Adjusted constraints for model {model_config.model_name}: "
                    f"max_input={constraints.max_input_tokens}, "
                    f"reserve_output={constraints.reserve_output_tokens}"
                )

        # Perform compression
        result = strategy.compress(
            context=self.context, messages=messages, constraints=constraints, **kwargs
        )

        # Log records
        if result.compression_ratio < 1.0:
            self.context.info(
                f"Context compressed using {strategy_name}: "
                f"{result.original_token_count} -> {result.compressed_token_count} tokens "
                f"(ratio: {result.compression_ratio:.2f})"
            )

        return result

    def register_strategy(self, name: str, strategy: CompressionStrategy):
        """Register a new compression strategy"""
        self.strategies[name] = strategy
        logger.debug(f"Registered new compression strategy: {name}")

    def get_available_strategies(self) -> List[str]:
        """Get the list of available compression strategies"""
        return list(self.strategies.keys())

    def estimate_tokens(self, messages: Messages) -> int:
        """Estimate the number of tokens in a message"""
        # Token estimation method using default strategy
        default_strategy = self.strategies.get(
            self.config.default_strategy, TruncationStrategy()
        )
        return default_strategy.estimate_tokens(messages)
