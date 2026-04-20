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
- Tool 核心（Toolkit、tool_function、tool_matcher）
- 轨迹记录（Trajectory）
- Agent 核心定义（BaseAgent、AgentState）
- Runtime 核心（RuntimeInstance、RuntimeGraph）

依赖规则：
- dolphin.core 无内部依赖（仅依赖第三方库）
"""
import warnings

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

# Tool
from dolphin.core.tool.toolkit import Toolkit
from dolphin.core.tool.toolset import ToolSet
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.tool_matcher import ToolMatcher

# Backward-compatibility aliases (deprecated)
class Skillkit(Toolkit):
    """Deprecated compatibility wrapper for Toolkit."""

    def getSkills(self):
        """Deprecated alias for getTools()."""
        warnings.warn(
            "Skillkit.getSkills() is deprecated, use Toolkit.getTools() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getTools()


class Skillset(ToolSet):
    """Deprecated compatibility wrapper for ToolSet."""

    def addSkill(self, skill: ToolFunction):
        """Deprecated alias for addTool()."""
        warnings.warn(
            "Skillset.addSkill() is deprecated, use ToolSet.addTool() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.addTool(skill)

    def addSkillkit(self, skillkit: Toolkit):
        """Deprecated alias for addToolkit()."""
        warnings.warn(
            "Skillset.addSkillkit() is deprecated, use ToolSet.addToolkit() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.addToolkit(skillkit)

    def getSkills(self):
        """Deprecated alias for getTools()."""
        warnings.warn(
            "Skillset.getSkills() is deprecated, use ToolSet.getTools() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getTools()


SkillFunction = ToolFunction
SkillMatcher = ToolMatcher

# LLM
from dolphin.core.llm.llm import LLM
from dolphin.core.llm.llm_client import LLMClient

# Config
from dolphin.core.config.global_config import GlobalConfig

# Common
from dolphin.core.common.enums import MessageRole, ToolType, SkillType
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
    # Tool
    "Toolkit",
    "ToolSet",
    "ToolFunction",
    "ToolMatcher",
    # Tool (deprecated aliases)
    "Skillkit",
    "Skillset",
    "SkillFunction",
    "SkillMatcher",
    # LLM
    "LLM",
    "LLMClient",
    # Config
    "GlobalConfig",
    # Common
    "MessageRole",
    "ToolType",
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
