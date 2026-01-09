"""
LLM Call abstractions for the memory system.

This module provides abstract interfaces for LLM operations in the memory system,
including prompt assembly, post-processing, and formatting.
"""

import json
from datetime import datetime
from typing import List, Any

from dolphin.core.llm.llm_call import LLMCall

from dolphin.core.common.enums import KnowledgePoint, MessageRole, Messages
from dolphin.core.logging.logger import get_logger
from dolphin.lib.memory.utils import validate_knowledge_point

logger = get_logger("mem")


class KnowledgeExtractionCall(LLMCall):
    """LLM call for extracting knowledge from conversations."""

    def execute(
        self, conversation_history: Messages, user_id: str
    ) -> List[KnowledgePoint]:
        """Execute knowledge extraction for a specific conversation and user."""
        if len(conversation_history.get_messages()) == 0:
            return []

        return super().execute(
            llm_args={"knowledge_extraction": True},
            conversation_history=conversation_history,
            user_id=user_id,
        )

    def _log(self, time_cost: float, **kwargs) -> str:
        """Log the execution result."""
        logger.info(
            f"Knowledge extraction execution user_id[{kwargs.get('user_id', 'unknown')}] time[{time_cost} seconds]"
        )

    def _build_prompt(self, conversation_history: Messages, **kwargs) -> str:
        """Build prompt for knowledge extraction."""
        conversation_text = ""
        for msg in conversation_history.get_messages():
            if msg.role == MessageRole.SYSTEM:
                continue

            conversation_text += f"{msg.role.value}: {msg.content}\n"

        """You are a professional knowledge management expert. Your task is to analyze the following conversation and extract valuable knowledge. The knowledge should be categorized into one of the following three types:

        1. **WorldModel**: Facts about the external world, ontologies, data sources, or user-provided correction information.
        2. **ExperientialKnowledge**: Methodologies, strategies, or lessons learned from agent task execution.
        3. **OtherKnowledge**: Any other information worth remembering, such as user preferences or specific details.

        For each piece of knowledge, provide a concise summary, its type, and a relevance score from 0 to 100 indicating its importance for future interactions.

        Notes:
        1. Do not include information related to specific database data, as this information is volatile.
        2. Knowledge points should have complete predicates, not just single nouns.

        Please output your findings strictly in JSONL format, with one JSON object per line. Each object should contain the fields: content, type, score, metadata. Do not include any other text or explanations.

        Conversation history:
        {conversation_text}
        """

    def _post_process(
        self, llm_output: str, user_id: str, **kwargs
    ) -> List[KnowledgePoint]:
        """Parse and validate LLM extraction result."""
        knowledge_points = []

        for line in llm_output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            try:
                raw_point = json.loads(line)
                # Add user_id and timestamp to metadata
                raw_point["user_id"] = user_id
                if "metadata" not in raw_point:
                    raw_point["metadata"] = {}
                raw_point["metadata"]["extraction_time"] = datetime.now().isoformat()

                # Validate and convert
                validated_point = validate_knowledge_point(
                    KnowledgePoint(**raw_point), user_id
                )
                knowledge_points.append(validated_point)

            except Exception as e:
                logger.warning(f"Failed to parse knowledge point: {line} - {e}")
                continue

        return knowledge_points


class KnowledgeMergeCall(LLMCall):
    """LLM call for merging and deduplicating knowledge."""

    def execute(
        self, all_knowledge_points: List[KnowledgePoint]
    ) -> List[KnowledgePoint]:
        """Execute knowledge merging for a list of knowledge points."""
        return super().execute(
            llm_args={"knowledge_extraction": True},
            all_knowledge_points=all_knowledge_points,
        )

    def _log(self, time_cost: float, **kwargs) -> str:
        """Log the execution result."""
        logger.info(
            f"Knowledge merge execution user_id[{kwargs.get('user_id', 'unknown')}] time[{time_cost} seconds]"
        )

    def _no_merge_result(self, **kwargs) -> Any:
        """No merge result."""
        return kwargs.get("all_knowledge_points", None)

    def _build_prompt(self, all_knowledge_points: List[KnowledgePoint]) -> str:
        """Build prompt for knowledge merging."""
        if len(all_knowledge_points) <= 1:
            return ""  # No need to merge if only one or zero points

        knowledge_json = json.dumps(all_knowledge_points, indent=2, ensure_ascii=False)

        """You are a knowledge management expert. Please analyze the following knowledge points and perform intelligent merging:

        1. Identify similar, redundant, or mergeable knowledge points
        2. Merge related knowledge points into more comprehensive content
        3. Keep unique and valuable knowledge points unchanged
        4. Ensure no important information is lost during merging
        5. Update scores based on综合 importance and reliability

        Current knowledge points:
        {knowledge_json}

        Return the optimized knowledge base as a JSON array, where each element follows the KnowledgePoint format.
        Prioritize quality over quantity — fewer but higher-quality knowledge points are better.

        Return only the JSON array, without any additional text.
        """

    def _post_process(
        self, llm_output: str, all_knowledge_points: List[KnowledgePoint]
    ) -> List[KnowledgePoint]:
        """Parse and validate LLM merge result."""
        if len(all_knowledge_points) <= 1:
            return all_knowledge_points

        try:
            merged_knowledge = json.loads(llm_output)

            # Validate each point and ensure user_id consistency
            user_id = (
                all_knowledge_points[0]["user_id"] if all_knowledge_points else None
            )
            validated_knowledge = []

            for point in merged_knowledge:
                try:
                    validated_point = validate_knowledge_point(point, user_id)
                    validated_knowledge.append(validated_point)
                except Exception as e:
                    logger.warning(f"Invalid merged knowledge point: {e}")
                    continue

            return validated_knowledge

        except Exception as e:
            # Fallback: return original knowledge if LLM output is invalid
            logger.warning(f"LLM merge failed, keeping original knowledge: {e}")
            return self._simple_deduplication(all_knowledge_points)

    def _simple_deduplication(
        self, knowledge_points: List[KnowledgePoint]
    ) -> List[KnowledgePoint]:
        """Simple deduplication as fallback."""
        seen_content = set()
        deduplicated = []

        # Sort by score to keep highest scored items
        sorted_points = sorted(knowledge_points, key=lambda p: p["score"], reverse=True)

        for point in sorted_points:
            content_key = point["content"].strip().lower()
            if content_key not in seen_content:
                seen_content.add(content_key)
                deduplicated.append(point)

        return deduplicated
