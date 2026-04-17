"""Deprecated: use dolphin.lib.toolkits.cognitive_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.cognitive_skillkit is deprecated. Use dolphin.lib.toolkits.cognitive_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.cognitive_toolkit import CognitiveToolkit as CognitiveSkillkit
__all__ = ["CognitiveSkillkit"]
