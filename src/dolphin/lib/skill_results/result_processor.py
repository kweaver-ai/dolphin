"""Result Processor Module
Responsible for processing tool execution results, including caching, reference management, and policy application
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from dolphin.lib.skill_results.cache_backend import (
    CacheBackend,
    CacheEntry,
)
from dolphin.lib.skill_results.result_reference import ResultReference
from dolphin.lib.skill_results.strategy_registry import StrategyRegistry

from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


class ResultProcessor:
    """Result Processor
        Responsible for receiving raw tool results, writing to cache, and returning references
    """

    def __init__(
        self, cache_backend: CacheBackend, strategy_registry: StrategyRegistry
    ):
        self.cache_backend = cache_backend
        self.strategy_registry = strategy_registry

    def process_result(
        self,
        tool_name: str,
        result: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResultReference:
        """Process tool execution results

        Args:
            tool_name: Tool name
            result: Tool execution result
            metadata: Metadata

        Returns:
            ResultReference: Result reference object
        """
        try:
            # Generate unique reference ID
            reference_id = str(uuid.uuid4())

            # Preparing metadata
            if metadata is None:
                metadata = {}

            metadata.update(
                {
                    "tool_name": tool_name,
                    "processed_at": datetime.now().isoformat(),
                    "result_type": type(result).__name__,
                }
            )

            # Calculate result size
            result_size = len(str(result)) if result else 0

            # Create cache entry
            cache_entry = CacheEntry(
                reference_id=reference_id,
                full_result=result,
                metadata=metadata,
                created_at=datetime.now(),
                tool_name=tool_name,
                size=result_size,
            )

            # Store in cache
            self.cache_backend.store(cache_entry)

            logger.debug(
                f"结果处理完成: tool={tool_name}, id={reference_id}, size={result_size}"
            )

            # Return result reference
            return ResultReference(
                reference_id=reference_id,
                cache_backend=self.cache_backend,
                strategy_registry=self.strategy_registry,
            )

        except Exception as e:
            logger.error(f"结果处理failed: tool={tool_name}, error={e}")
            raise

    def get_result_reference(self, reference_id: str) -> Optional[ResultReference]:
        """Get result reference object by reference ID

        Args:
            reference_id: Reference ID

        Returns:
            ResultReference: Result reference object, returns None if not exists
        """
        try:
            if not self.cache_backend.exists(reference_id):
                return None

            return ResultReference(
                reference_id=reference_id,
                cache_backend=self.cache_backend,
                strategy_registry=self.strategy_registry,
            )

        except Exception as e:
            logger.error(f"Get结果引用failed: id={reference_id}, error={e}")
            return None

    def delete_result(self, reference_id: str) -> bool:
        """Delete the cached result of the specified reference

        Args:
            reference_id: Reference ID

        Returns:
            bool: Whether the deletion was successful
        """
        try:
            success = self.cache_backend.delete(reference_id)
            if success:
                logger.info(f"结果删除successful: id={reference_id}")
            else:
                logger.warning(f"结果删除failed: id={reference_id}")
            return success

        except Exception as e:
            logger.error(f"结果删除异常: id={reference_id}, error={e}")
            return False

    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Clean expired cache

        Args:
            max_age_hours: Maximum retention time (in hours)

        Returns:
            int: Number of items cleaned
        """
        try:
            cleaned_count = self.cache_backend.cleanup(max_age_hours)
            logger.info(
                f"过期缓存清理完成: count={cleaned_count}, max_age={max_age_hours}h"
            )
            return cleaned_count

        except Exception as e:
            logger.error(f"过期缓存清理failed: error={e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics

        Returns:
            Dict: Dictionary of statistics
        """
        try:
            cache_stats = self.cache_backend.get_stats()
            strategy_stats = self.strategy_registry.get_stats()

            return {
                "cache": cache_stats,
                "strategies": strategy_stats,
                "processor": {
                    "type": "ResultProcessor",
                    "cache_backend": type(self.cache_backend).__name__,
                    "strategy_registry": type(self.strategy_registry).__name__,
                },
            }

        except Exception as e:
            logger.error(f"Get统计信息failed: error={e}")
            return {"error": str(e)}
