"""
Memory Management Subsystem for Dolphin Language SDK

This module provides long-term memory capabilities for intelligent agents,
supporting both simple memory storage and complex knowledge management with user isolation.
"""

from dolphin.core.common import KnowledgePoint, SingleMessage
from .storage import MemoryFileSys
from .manager import MemoryManager
from .llm_calls import LLMCall, KnowledgeExtractionCall, KnowledgeMergeCall

from dolphin.core.config.global_config import MemoryConfig

__all__ = [
    "SingleMessage",
    "KnowledgePoint",
    # Storage interfaces
    "MemoryStorage",
    "MemoryFileSys",
    # Unified management
    "MemoryManager",
    "MemoryConfig",
    # LLM processing
    "LLMCall",
    "KnowledgeExtractionCall",
    "KnowledgeMergeCall",
]
