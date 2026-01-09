from typing import Set, Dict, Any
from enum import Enum, auto


class ConceptMemberType(Enum):
    """Type of Concept Members"""

    STRING = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    OBJECT = auto()  # Referencing Other Objects
    RELATION = auto()  # Referencing Other Relations
    ANY = auto()  # Any type


class Concept:
    """Define the contract (structure) for concepts

        A Concept defines a set of required member names and their types.
        Each member can have type constraints used to validate values during instantiation.
    """

    def __init__(self, name: str, members: Dict[str, ConceptMemberType]):
        """Initialize Concept

        Args:
            name (str): The name of the concept
            members (Dict[str, ConceptMemberType]): A mapping from member names to their types

        Raises:
            ValueError: If the name is empty or no members are defined
        """
        if not name:
            raise ValueError("概念名称不能为空")
        if not members:
            raise ValueError("概念必须至少定义一个成员")

        self.name = name
        self.members = members
        self.mappings = []

    def __repr__(self) -> str:
        members_str = {name: type.name for name, type in self.members.items()}
        return f"Concept(name='{self.name}', members={members_str})"

    def addMapping(self, mapping):
        self.mappings.append(mapping)

    def getDataSourceSchemas(self) -> Dict[str, Any]:
        """Get the schema of all associated data sources"""
        dataSourceSchemas = {}
        for mapping in self.mappings:
            dataSourceSchemas[mapping.space] = mapping.getDataSourceSchema()
        return dataSourceSchemas

    def validateMembers(self, provided_members: Set[str]) -> bool:
        """Check whether the provided member set fully matches the requirements defined by this Concept

        Args:
            provided_members (Set[str]): Set of member names to validate

        Returns:
            bool: True if the provided members exactly match the defined members
        """
        return set(self.members.keys()) == provided_members

    def validateMemberValue(self, memberName: str, value: Any) -> bool:
        """Validate whether the member's value meets the type requirements

        Args:
            member_name (str): The name of the member
            value (Any): The value to validate

        Returns:
            bool: True if the value meets the type requirements

        Raises:
            KeyError: If the member name does not exist
        """
        if memberName not in self.members:
            raise KeyError(f"成员 '{memberName}' 未在概念 '{self.name}' 中定义")

        expectedType = self.members[memberName]

        # If the type is ANY, return True directly
        if expectedType == ConceptMemberType.ANY:
            return True

        # Validate according to the expected type
        if expectedType == ConceptMemberType.STRING:
            return isinstance(value, str)
        elif expectedType == ConceptMemberType.BOOLEAN:
            # Note: In Python, bool is a subclass of int; BOOLEAN must be checked first
            return isinstance(value, bool)
        elif expectedType == ConceptMemberType.NUMBER:
            # Exclude bool from NUMBER to avoid misjudging True/False as numbers
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expectedType == ConceptMemberType.OBJECT:
            from .object import Object

            return isinstance(value, Object)
        elif expectedType == ConceptMemberType.RELATION:
            from .relation import Relation

            return isinstance(value, Relation)

        return False  # Unknown type

    def validateValues(self, values: Dict[str, Any]) -> bool:
        """Validate that all values conform to the concept definition

        Args:
            values (Dict[str, Any]): Dictionary of values to validate

        Returns:
            bool: True if all values meet the requirements
        """
        if not self.validateMembers(set(values.keys())):
            return False

        return all(
            self.validateMemberValue(name, value) for name, value in values.items()
        )

    def toDict(self) -> Dict[str, Any]:
        """Convert concepts to dictionary"""
        return {
            "name": self.name,
            "members": {name: type_.name for name, type_ in self.members.items()},
        }
