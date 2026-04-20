"""Deprecated: use dolphin.lib.toolkits.env_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.env_skillkit is deprecated. Use dolphin.lib.toolkits.env_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.env_toolkit import EnvToolkit as EnvSkillkit
__all__ = ["EnvSkillkit"]
