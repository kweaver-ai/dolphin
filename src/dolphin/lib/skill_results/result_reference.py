"""Result reference module
Provides functions for referencing, caching, and handling strategies for result data
"""

from typing import Any, Dict, Optional, TYPE_CHECKING
from datetime import datetime, timedelta

from dolphin.lib.skill_results.cache_backend import CacheBackend, CacheEntry

if TYPE_CHECKING:
    from dolphin.lib.skill_results.strategy_registry import StrategyRegistry

from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


class ResultReference:
    """Result reference class, providing reference access to cached results"""

    def __init__(
        self,
        reference_id: str,
        cache_backend: CacheBackend,
        strategy_registry: "StrategyRegistry",
    ):
        self.reference_id = reference_id
        self.cache_backend = cache_backend
        self._strategy_registry = strategy_registry
        self._cached_entry: Optional[CacheEntry] = None

    def get_full_result(self) -> Optional[Any]:
        """Get complete results"""
        try:
            if self._cached_entry is None:
                self._cached_entry = self.cache_backend.get(self.reference_id)

            if self._cached_entry:
                return self._cached_entry.full_result
            return None
        except Exception as e:
            logger.error(f"Failed to get full result for {self.reference_id}: {e}")
            return None

    def get_metadata(self) -> Optional[Dict[str, Any]]:
        """Get metadata"""
        try:
            if self._cached_entry is None:
                self._cached_entry = self.cache_backend.get(self.reference_id)

            if self._cached_entry:
                return self._cached_entry.metadata
            return None
        except Exception as e:
            logger.error(f"Failed to get metadata for {self.reference_id}: {e}")
            return None

    # === Unified Entry: Retrieval Based on Category ===
    def get_for_category(
        self, category: str, strategy_name: str = "default", **kwargs
    ) -> Optional[Any]:
        """Get processed data based on category (e.g., category='llm' or 'frontend')"""
        try:
            strategy = self._strategy_registry.get_strategy(strategy_name, category)
            if strategy is None:
                logger.warning(f"策略不存在: {category}:{strategy_name}")
                return None

            if not strategy.supports(category):
                logger.warning(f"策略不支持 category: {category}")
                return None

            return strategy.process(self, **kwargs)
        except Exception as e:
            logger.error(f"策略处理failed: {category}:{strategy_name}, 错误: {e}")
            return None

    def get(self, strategy_spec: str = "", **kwargs) -> Any:
        """Unified acquisition: supports 'llm:summary' / 'app/pagination' / 'summary' (auto-detected)."""
        if not strategy_spec:
            # Channel not specified:优先尝试 llm，再尝试 app
            result = self.get_for_category("llm", "default", **kwargs)
            if result is not None:
                return result
            return self.get_for_category("app", strategy_name="default", **kwargs)

        # Parsing strategy specifications
        if ":" in strategy_spec:
            category, name = strategy_spec.split(":", 1)
            return self.get_for_category(category, name, **kwargs)
        elif "/" in strategy_spec:
            category, name = strategy_spec.split("/", 1)
            return self.get_for_category(category, name, **kwargs)
        else:
            # Unknown channel: try common categories
            for k in ("llm", "app"):
                result = self.get_for_category(k, strategy_spec, **kwargs)
                if result is not None:
                    return result
            # Try another category
            for k in self._strategy_registry.list_strategies().keys():
                if k in ("llm", "app"):
                    continue
                result = self.get_for_category(k, strategy_spec, **kwargs)
                if result is not None:
                    return result
            return None

    def exists(self) -> bool:
        """Check if reference exists"""
        return self.cache_backend.exists(self.reference_id)

    def get_info(self) -> Dict[str, Any]:
        """Get reference information"""
        try:
            if self._cached_entry is None:
                self._cached_entry = self.cache_backend.get(self.reference_id)

            if self._cached_entry:
                return {
                    "reference_id": self.reference_id,
                    "tool_name": self._cached_entry.tool_name,
                    "size": self._cached_entry.size,
                    "created_at": self._cached_entry.created_at.isoformat(),
                    "metadata": self._cached_entry.metadata,
                }
            return {"reference_id": self.reference_id, "exists": False}
        except Exception as e:
            logger.error(f"Failed to get info for {self.reference_id}: {e}")
            return {"reference_id": self.reference_id, "error": str(e)}

    def delete(self) -> bool:
        """Delete reference"""
        try:
            success = self.cache_backend.delete(self.reference_id)
            if success:
                self._cached_entry = None
            return success
        except Exception as e:
            logger.error(f"Failed to delete reference {self.reference_id}: {e}")
            return False

    def set_data(self, data: Any) -> None:
        """Set result data"""
        self._data = data

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        """Set metadata"""
        self._metadata = metadata.copy()

    def update_metadata(self, updates: Dict[str, Any]) -> None:
        """Update metadata"""
        self._metadata.update(updates)

    def is_expired(self) -> bool:
        """Check if expired"""
        if self._cache_ttl is None:
            return False
        return datetime.now() - self._created_at > timedelta(seconds=self._cache_ttl)

    def get_age(self) -> float:
        """Get data age (seconds)"""
        return (datetime.now() - self._created_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "reference_id": self.reference_id,
            "data": self._data,
            "metadata": self._metadata,
            "created_at": self._created_at.isoformat(),
            "cache_ttl": self._cache_ttl,
        }

    def __str__(self) -> str:
        return f"ResultReference(id={self.reference_id}, data_type={type(self._data).__name__})"

    def __repr__(self) -> str:
        return self.__str__()
