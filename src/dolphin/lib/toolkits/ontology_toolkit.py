from typing import List, Optional

from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.toolkit import Toolkit
from dolphin.lib.ontology.ontology_context import OntologyContext


class OntologyToolkit(Toolkit):
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
        return "ontology_toolkit"

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

    def _createTools(self) -> List[ToolFunction]:
        return [
            ToolFunction(self.getAllConcepts),
            ToolFunction(self.getSampleData),
            ToolFunction(self.getDataSourceSchemas),
            ToolFunction(self.getDataSourcesFromConcepts),
        ]

    # Add alias method to support getTools
    def getTools(self) -> List[ToolFunction]:
        return self.getTools()
