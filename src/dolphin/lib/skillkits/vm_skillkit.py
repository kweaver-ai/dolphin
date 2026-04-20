"""Deprecated: use dolphin.lib.toolkits.vm_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.vm_skillkit is deprecated. Use dolphin.lib.toolkits.vm_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.vm_toolkit import VMToolkit as VMSkillkit
__all__ = ["VMSkillkit"]
