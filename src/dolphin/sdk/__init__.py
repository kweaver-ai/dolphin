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
import warnings

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

# Deprecated aliases
class GlobalSkills(GlobalToolkits):
    """Deprecated compatibility wrapper for GlobalToolkits."""

    @property
    def installedSkillset(self):
        """Deprecated alias for installedToolSet."""
        warnings.warn(
            "GlobalSkills.installedSkillset is deprecated, use installedToolSet instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.installedToolSet

    @property
    def agentSkillset(self):
        """Deprecated alias for agentToolSet."""
        warnings.warn(
            "GlobalSkills.agentSkillset is deprecated, use agentToolSet instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.agentToolSet

    def getAllSkills(self):
        """Deprecated alias for getAllTools()."""
        warnings.warn(
            "GlobalSkills.getAllSkills() is deprecated, use getAllTools() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getAllTools()

    def getInstalledSkills(self):
        """Deprecated alias for getInstalledTools()."""
        warnings.warn(
            "GlobalSkills.getInstalledSkills() is deprecated, use getInstalledTools() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getInstalledTools()

    def getAgentSkills(self):
        """Deprecated alias for getAgentTools()."""
        warnings.warn(
            "GlobalSkills.getAgentSkills() is deprecated, use getAgentTools() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getAgentTools()

    def registerAgentSkill(self, agentName: str, agent: BaseAgent):
        """Deprecated alias for registerAgentTool()."""
        warnings.warn(
            "GlobalSkills.registerAgentSkill() is deprecated, use registerAgentTool() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.registerAgentTool(agentName, agent)

    def unregisterAgentSkill(self, agentName: str):
        """Deprecated alias for unregisterAgentTool()."""
        warnings.warn(
            "GlobalSkills.unregisterAgentSkill() is deprecated, use unregisterAgentTool() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.unregisterAgentTool(agentName)


Skillkit = Toolkit
Skillset = ToolSet
SkillFunction = ToolFunction

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
    # Deprecated aliases
    "GlobalSkills",
    "Skillkit",
    "Skillset",
    "SkillFunction",
]
