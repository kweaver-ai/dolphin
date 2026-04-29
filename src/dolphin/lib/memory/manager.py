"""
Memory Manager - the main orchestrator for the memory system.
"""

from typing import List, Optional

from dolphin.core.common.enums import KnowledgePoint
from .storage import MemoryFileSys
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.logging.logger import get_logger

logger = get_logger("mem")


class MemoryManager:
    """The main orchestrator for the memory system - focused on complex knowledge management."""

    def __init__(self, global_config: GlobalConfig):
        """
        Initializes the MemoryManager.

        :param global_config: Global configuration instance, will create default if None.
        """
        self.global_config = global_config
        self.memory_config = global_config.memory_config

        self.memory_storage = MemoryFileSys(self.memory_config.storage_path)

    def retrieve_relevant_memory(
        self, context, user_id: str, query: str = None, top_k: Optional[int] = None
    ) -> List[KnowledgePoint]:
        """
        Retrieves knowledge relevant to a given query for a specific user to be injected into context.

        :param context: Context instance for accessing skillkits
        :param user_id: The user whose knowledge should be retrieved
        :param query: Query string (not currently used in this implementation)
        :param top_k: Number of knowledge points to return
        """
        if top_k is None:
            top_k = self.memory_config.default_top_k

        if context.get_cur_agent() is None:
            return []

        try:
            memory_skill_result = context.get_skillkit().exec(
                "_read_memory",
                agent_name=context.get_cur_agent().get_name(),
                user_id=user_id,
            )
            if not memory_skill_result:
                return []

            memory_items = memory_skill_result.result
            if not memory_items:
                return []

            converted_points = []
            for item in memory_items:
                try:
                    point = KnowledgePoint(
                        content=item.get("content", ""),
                        score=item.get("score", 50),
                        user_id=item.get("user_id", ""),
                    )
                    converted_points.append(point)
                except Exception as e:
                    logger.warning(
                        f"Failed to convert dialog log to KnowledgePoint: {e}"
                    )
                    continue

            return converted_points[:top_k]

        except Exception as e:
            logger.error(f"Failed to retrieve knowledge for user {user_id}: {e}")
            return []
