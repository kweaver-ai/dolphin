"""Deprecated: use dolphin.lib.toolkits.sql_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.sql_skillkit is deprecated. Use dolphin.lib.toolkits.sql_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.sql_toolkit import SQLToolkit as SQLSkillkit
__all__ = ["SQLSkillkit"]
