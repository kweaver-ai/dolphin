from dolphin.core.config.ontology_config import OntologyConfig
from dolphin.lib.ontology.ontology_manager import OntologyManager


class OntologyContext:
    """Global context class, managing ontologies and data sources"""

    def __init__(self, ontologyConfig: OntologyConfig):
        self.ontologyManager = OntologyManager(ontologyConfig)

    def getOntology(self):
        return self.ontologyManager.getOntology()

    @staticmethod
    def loadOntologyContext(ontologyConfig: OntologyConfig) -> "OntologyContext":
        return OntologyContext(ontologyConfig)
