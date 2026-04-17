"""Deprecated: use dolphin.lib.toolkits.agent_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.agent_skillkit is deprecated. Use dolphin.lib.toolkits.agent_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.agent_toolkit import AgentToolkit as AgentSkillKit
__all__ = ["AgentSkillKit"]
