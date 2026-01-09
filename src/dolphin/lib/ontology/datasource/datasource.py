from abc import ABC, abstractmethod
from typing import Any, Dict, List, TYPE_CHECKING

# Modify the import, use the correct DataSourceType
from dolphin.core.common.enums import Messages
from dolphin.core.config import DataSourceType

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from dolphin.lib.ontology.mapping import Mapping


class DataSource(ABC):
    """Data source abstract base class"""

    def __init__(self, name: str, type: DataSourceType, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.schema = None

    @abstractmethod
    def connect(self) -> Any:
        """Establish a connection to the data source"""
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, List[str]]:
        """Get the schema information of the data source (e.g., tables and columns)"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close data source connection"""
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test whether the data source connection is successful"""
        pass

    @abstractmethod
    def executeQuery(self, query: str, fetchColumns: bool = True) -> Dict[str, Any]:
        """Execute query query"""
        pass

    @abstractmethod
    def sampleData(self, conceptName: str, count: int = 10) -> Messages:
        """Get sample data according to concept"""
        pass

    @abstractmethod
    def scan(self) -> List["Mapping"]:
        """Scan the data source schema to generate Concept objects and their corresponding Mappings.

                Returns a list of Mappings, where each Mapping represents the mapping relationship
                from a data source entity (e.g., a table) to its corresponding Concept.
        """
        pass

    @property
    @abstractmethod
    def type(self) -> DataSourceType:
        """Return the data source type (using config.DataSourceType)"""
        pass

    # More general methods, such as execute_query, can be added as needed
