"""Deprecated: use dolphin.lib.toolkits.resource_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.resource_skillkit is deprecated. Use dolphin.lib.toolkits.resource_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.resource_toolkit import ResourceToolkit as ResourceSkillkit
__all__ = ["ResourceSkillkit"]
