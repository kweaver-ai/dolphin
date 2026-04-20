"""Deprecated: use dolphin.lib.toolkits.search_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.search_skillkit is deprecated. Use dolphin.lib.toolkits.search_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.search_toolkit import SearchToolkit as SearchSkillkit
__all__ = ["SearchSkillkit"]
