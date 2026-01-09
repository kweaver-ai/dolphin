from typing import List, Optional

from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.lib.ontology.ontology_context import OntologyContext


class OntologySkillkit(Skillkit):
    def __init__(self, ontologyContext: Optional[OntologyContext] = None):
        super().__init__()
        self.ontologyContext = ontologyContext

    def setGlobalConfig(self, globalConfig):
        super().setGlobalConfig(globalConfig)
        if (
            self.ontologyContext is None
            and self.globalConfig.ontology_config is not None
        ):
            self.ontologyContext = OntologyContext.loadOntologyContext(
                self.globalConfig.ontology_config
            )

    def getName(self) -> str:
        return "ontology_skillkit"

    def getDesc(self) -> str:
        return "Ontology"

    def getAllConcepts(self, **kwargs) -> str:
        """Get the descriptions of all concepts in the ontology model

        Args:
            None

        Returns:
            str: The descriptions of all concepts in the ontology model
        """
        return self.ontologyContext.getOntology().getAllConceptsDescription()

    def getSampleData(self, conceptNames: List[str], **kwargs) -> str:
        """Get sample data for a specified concept in the ontology model

        Args:
            conceptNames (List[str]): List of concept names

        Returns:
            str: Sample data for the specified concept in the ontology model
        """
        return self.ontologyContext.getOntology().sampleData(conceptNames)

    def getDataSourceSchemas(self, conceptNames: List[str], **kwargs) -> str:
        """Get the schema of data sources for specified concepts in the ontology model

        Args:
            conceptNames (List[str]): List of concept names
        """
        dataSourceSchemas = []
        for conceptName in conceptNames:
            concept = self.ontologyContext.getOntology().getConcept(conceptName)
            if not concept:
                continue
            dataSourceSchemas.append(concept.getDataSourceSchemas())
        return dataSourceSchemas

    def getDataSourcesFromConcepts(self, conceptNames: List[str], **kwargs) -> str:
        """Get the schema of the data source for the specified concept in the ontology model

        Args:
            conceptNames (List[str]): List of concept names

        Returns:
            str: The schema of the data source for the specified concept in the ontology model
        """
        result = self.ontologyContext.getOntology().getDataSourcesFromConcepts(
            conceptNames
        )
        return str(result)

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self.getAllConcepts),
            SkillFunction(self.getSampleData),
            SkillFunction(self.getDataSourceSchemas),
            SkillFunction(self.getDataSourcesFromConcepts),
        ]

    # Add alias method to support getTools
    def getTools(self) -> List[SkillFunction]:
        return self.getSkills()
