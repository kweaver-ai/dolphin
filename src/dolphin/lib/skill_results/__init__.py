"""Skill Result Module
Provides features such as result referencing, strategy handling, and strategy registration.
"""

from dolphin.lib.skill_results.result_reference import ResultReference
from dolphin.lib.skill_results.cache_backend import CacheBackend
from dolphin.lib.skill_results.result_processor import ResultProcessor
from dolphin.lib.skill_results.strategies import (
    BaseStrategy,
    DefaultLLMStrategy,
    SummaryLLMStrategy,
    TruncateLLMStrategy,
    DefaultAppStrategy,
    PaginationAppStrategy,
    PreviewAppStrategy,
)
from dolphin.lib.skill_results.strategy_registry import StrategyRegistry

__all__ = [
    "ResultReference",
    "CacheBackend",
    "ResultProcessor",
    "BaseStrategy",
    "DefaultLLMStrategy",
    "SummaryLLMStrategy",
    "TruncateLLMStrategy",
    "DefaultAppStrategy",
    "PaginationAppStrategy",
    "PreviewAppStrategy",
    "StrategyRegistry",
]
