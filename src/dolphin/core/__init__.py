# -*- coding: utf-8 -*-
"""
Dolphin Core - 核心运行时引擎（内核态）

职责：
- 执行引擎（Executor）
- 上下文管理（Context）
- 上下文工程（Context Engineer）
- 消息压缩（Message Compressor）
- 变量池（Variable Pool）
- 语法解析器（Parser）
- 协程调度（Coroutine）
- 代码块执行（Code Block）
- LLM 调用抽象层
- Skill 核心（Skillkit、skill_function、skill_matcher）
- 轨迹记录（Trajectory）
- Agent 核心定义（BaseAgent、AgentState）
- Runtime 核心（RuntimeInstance、RuntimeGraph）

依赖规则：
- dolphin.core 无内部依赖（仅依赖第三方库）
"""

# Context
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.context.variable_pool import VariablePool

# Executor
from dolphin.core.executor.executor import Executor
# DolphinExecutor is available via lazy import from dolphin.core.executor
from dolphin.core.executor.debug_controller import DebugController

# Runtime
from dolphin.core.runtime.runtime_instance import RuntimeInstance
from dolphin.core.runtime.runtime_graph import RuntimeGraph

# Agent
from dolphin.core.agent.base_agent import BaseAgent
from dolphin.core.agent.agent_state import AgentState

# Skill
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skillset import Skillset
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skill_matcher import SkillMatcher

# LLM
from dolphin.core.llm.llm import LLM
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.llm.llm_call import LLMCall

# Config
from dolphin.core.config.global_config import GlobalConfig

# Common
from dolphin.core.common.enums import MessageRole, SkillType
from dolphin.core.common.exceptions import DolphinException

# Logging
from dolphin.core.logging.logger import get_logger

# Trajectory
from dolphin.core.trajectory.trajectory import Trajectory
from dolphin.core.trajectory.recorder import Recorder

# Interfaces
from dolphin.core.interfaces import IMemoryManager

__all__ = [
    # Context
    "Context",
    "ContextManager",
    "VariablePool",
    # Executor
    "Executor",
    # DolphinExecutor is available via lazy import
    "DebugController",
    # Runtime
    "RuntimeInstance",
    "RuntimeGraph",
    # Agent
    "BaseAgent",
    "AgentState",
    # Skill
    "Skillkit",
    "Skillset",
    "SkillFunction",
    "SkillMatcher",
    # LLM
    "LLM",
    "LLMClient",
    "LLMCall",
    # Config
    "GlobalConfig",
    # Common
    "MessageRole",
    "SkillType",
    "DolphinException",
    # Logging
    "get_logger",
    # Trajectory
    "Trajectory",
    "Recorder",
    # Interfaces
    "IMemoryManager",
]
