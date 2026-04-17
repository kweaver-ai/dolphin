"""Deprecated: use dolphin.lib.toolkits.plan_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.plan_skillkit is deprecated. Use dolphin.lib.toolkits.plan_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.plan_toolkit import PlanToolkit as PlanSkillkit
__all__ = ["PlanSkillkit"]
