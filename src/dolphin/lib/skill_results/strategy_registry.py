"""Strategy Registrator
Provides registration, lookup, and management functions for strategies
"""

from typing import Dict, Optional, List, TYPE_CHECKING

from .strategies import (
    BaseStrategy,
    DefaultLLMStrategy,
    SummaryLLMStrategy,
    TruncateLLMStrategy,
    DefaultAppStrategy,
    PaginationAppStrategy,
    PreviewAppStrategy,
)

if TYPE_CHECKING:
    pass

from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


class StrategyRegistry:
    """Strategy Registrator
        - Default support category: 'llm', 'app', and other categories can be extended
        - Multiple named strategies can exist under each category
        - Supports registration, lookup, execution, and other operations
    """

    def __init__(self):
        # Strategies organized by category
        self._strategies: Dict[str, Dict[str, BaseStrategy]] = {}
        self._default_strategies: Dict[str, str] = {}

        # Register default policy
        self._register_default_strategies()

    def _register_default_strategies(self):
        """Register default strategy"""
        # LLM
        self.register("default", DefaultLLMStrategy(), category="llm")
        self.register("summary", SummaryLLMStrategy(), category="llm")
        self.register("truncate", TruncateLLMStrategy(), category="llm")

        # App
        self.register("default", DefaultAppStrategy(), category="app")
        self.register("pagination", PaginationAppStrategy(), category="app")
        self.register("preview", PreviewAppStrategy(), category="app")

        # Set default policy
        self._default_strategies = {
            "llm": "default",
            "app": "default",
        }

    def register(
        self, name: str, strategy: BaseStrategy, category: Optional[str] = None
    ) -> None:
        """Register strategy
                - name: Strategy name
                - strategy: Strategy instance
                - category: Strategy category, if None then use the strategy's own category
        """
        if category is None:
            category = strategy.get_category()

        if category not in self._strategies:
            self._strategies[category] = {}

        self._strategies[category][name] = strategy
        logger.debug(f"注册策略: {category}:{name} -> {strategy.__class__.__name__}")

    def get_strategy(self, name: str, category: str) -> Optional[BaseStrategy]:
        """Get strategy
                - name: Strategy name, supports 'llm:summary' / 'app/pagination' format
                - category: Strategy category
        """
        # Parse the category information in name
        if ":" in name:
            category, name = name.split(":", 1)
        elif "/" in name:
            category, name = name.split("/", 1)

        # If category is a wildcard, try all supported categories
        if category == "*":
            for k in ("llm", "app"):
                if k in self._strategies and name in self._strategies[k]:
                    return self._strategies[k][name]
            return None

        # If category is a list, try each category
        if isinstance(category, (list, tuple)):
            for k in category:
                if k in self._strategies and name in self._strategies[k]:
                    return self._strategies[k][name]
            return None

        # If category is a wildcard, try all supported categories
        # if category in ("llm", "app"):
        if category in self._strategies and name in self._strategies[category]:
            return self._strategies[category][name]

        return None

    def get_default_strategy(self, category: str) -> Optional[BaseStrategy]:
        """Get default policy"""
        if category not in self._default_strategies:
            return None

        default_name = self._default_strategies[category]
        return self.get_strategy(default_name, category)

    def list_strategies(self, category: Optional[str] = None) -> Dict[str, List[str]]:
        """List all strategies"""
        if category is None:
            return {
                cat: list(strategies.keys())
                for cat, strategies in self._strategies.items()
            }
        elif category in self._strategies:
            return {category: list(self._strategies[category].keys())}
        else:
            return {}

    def has_strategy(self, name: str, category: str) -> bool:
        """Check if the specified policy exists"""
        return self.get_strategy(name, category) is not None

    def remove_strategy(self, name: str, category: str) -> bool:
        """Remove Strategy"""
        if category in self._strategies and name in self._strategies[category]:
            del self._strategies[category][name]
            logger.debug(f"移除策略: {category}:{name}")
            return True
        return False

    def clear(self) -> None:
        """Clear all strategies"""
        self._strategies.clear()
        self._default_strategies.clear()
        logger.debug("清空所有策略")

    def __len__(self) -> int:
        """Return total number of strategies"""
        return sum(len(strategies) for strategies in self._strategies.values())

    def __repr__(self) -> str:
        return f"StrategyRegistry(strategies={len(self)}, categories={list(self._strategies.keys())})"
