"""Deprecated: use dolphin.lib.toolkits.system_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.system_skillkit is deprecated. Use dolphin.lib.toolkits.system_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.system_toolkit import SystemFunctionsToolkit as SystemFunctionsSkillKit
__all__ = ["SystemFunctionsSkillKit"]
