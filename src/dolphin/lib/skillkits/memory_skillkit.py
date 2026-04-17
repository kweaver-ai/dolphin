"""Deprecated: use dolphin.lib.toolkits.memory_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.memory_skillkit is deprecated. Use dolphin.lib.toolkits.memory_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.memory_toolkit import MemoryToolkit as MemorySkillkit
__all__ = ["MemorySkillkit"]
