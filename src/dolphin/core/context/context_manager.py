"""
Context Manager module for backward compatibility.

This module provides the ContextEngineer class which is an alias/wrapper
around MessageCompressor for SDK compatibility.

Note: The compression strategies (TruncationStrategy, LevelStrategy)
are now defined in dolphin.core.message.compressor.
"""

from typing import List, Dict, Optional, TYPE_CHECKING

from dolphin.core.common.enums import Messages
from dolphin.core.config.global_config import ContextEngineerConfig

# Import compression classes from the canonical location
from dolphin.core.message.compressor import (
    CompressionResult,
    CompressionStrategy,
    TruncationStrategy,
    LevelStrategy,
)

# Deprecated: SlidingWindowStrategy has been removed.  This alias keeps
# existing code that imports it from this module working at runtime, but
# new code should use TruncationStrategy or LevelStrategy instead.
SlidingWindowStrategy = TruncationStrategy

if TYPE_CHECKING:
    from dolphin.core.config.global_config import (
        ContextConstraints,
        LLMInstanceConfig,
    )
    from dolphin.core.context.context import Context

from dolphin.core.logging.logger import get_logger

logger = get_logger("context_engineer")


# Re-export for backward compatibility
__all__ = [
    "CompressionResult",
    "CompressionStrategy",
    "TruncationStrategy",
    "SlidingWindowStrategy",  # deprecated alias → TruncationStrategy
    "LevelStrategy",
    "ContextEngineer",
]


class ContextEngineer:
    """Context Engineer: Responsible for optimizing message context to meet model constraints.
    
    This class is maintained for backward compatibility with the SDK.
    New code should use MessageCompressor from dolphin.core.message.compressor instead.
    """

    def __init__(self, config: "ContextEngineerConfig" = None, context: "Context" = None):
        self.config = config or ContextEngineerConfig()
        self.context = context
        self.strategies = self._register_default_strategies()
        logger.debug(
            f"ContextEngineer initialized with strategy: {self.config.default_strategy}"
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

    def engineer_context(
        self,
        messages: Messages,
        strategy_name: Optional[str] = None,
        constraints: Optional["ContextConstraints"] = None,
        model_config: Optional["LLMInstanceConfig"] = None,
        **kwargs,
    ) -> CompressionResult:
        """Engineering processing of context

        Args:
            messages: List of original messages
            strategy_name: Name of the compression strategy to use, default uses the default strategy from configuration
            constraints: Compression constraints, default uses constraints from configuration
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
