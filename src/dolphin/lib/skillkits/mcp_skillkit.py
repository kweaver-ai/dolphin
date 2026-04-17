"""Deprecated: use dolphin.lib.toolkits.mcp_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.mcp_skillkit is deprecated. Use dolphin.lib.toolkits.mcp_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.mcp_toolkit import MCPToolkit as MCPSkillkit
__all__ = ["MCPSkillkit"]
