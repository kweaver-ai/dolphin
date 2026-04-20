"""Deprecated: use dolphin.lib.toolkits.noop_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.noop_skillkit is deprecated. Use dolphin.lib.toolkits.noop_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.noop_toolkit import NoopToolkit as NoopSkillkit
__all__ = ["NoopSkillkit"]
