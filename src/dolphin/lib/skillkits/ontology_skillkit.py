"""Deprecated: use dolphin.lib.toolkits.ontology_toolkit instead."""
import warnings
warnings.warn("dolphin.lib.skillkits.ontology_skillkit is deprecated. Use dolphin.lib.toolkits.ontology_toolkit instead.", DeprecationWarning, stacklevel=2)
from dolphin.lib.toolkits.ontology_toolkit import OntologyToolkit as OntologySkillkit
__all__ = ["OntologySkillkit"]
