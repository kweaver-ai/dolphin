# -*- coding: utf-8 -*-
"""
Dolphin SDK - 开发者 SDK（开发框架）

职责：
- Agent 开发框架（DolphinAgent）
- Tool 扩展开发（GlobalToolkits）
- 运行时环境（Env）
- 开发者友好的 API 封装

依赖规则：
- dolphin.sdk → 依赖 dolphin.lib, dolphin.core
"""

# Agent
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.sdk.agent.agent_factory import AgentFactory

# Runtime
from dolphin.sdk.runtime.env import Env

# Tool
from dolphin.sdk.tool.global_toolkits import GlobalToolkits
from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit

# 重新导出 core/lib 组件以便捷使用
from dolphin.core import (
    BaseAgent,
    AgentState,
    Context,
    ToolSet,
    Toolkit,
    ToolFunction,
)

from dolphin.lib import (
    Ontology,
    OntologyManager,
)

__all__ = [
    # Agent
    "DolphinAgent",
    "AgentFactory",
    # Runtime
    "Env",
    # Skill
    "GlobalToolkits",
    "TriditionalToolkit",
    # Re-exported from core
    "BaseAgent",
    "AgentState",
    "Context",
    "ToolSet",
    "Toolkit",
    "ToolFunction",
    # Re-exported from lib
    "Ontology",
    "OntologyManager",
]
