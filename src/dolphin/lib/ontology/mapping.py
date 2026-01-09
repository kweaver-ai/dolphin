from typing import Dict, Any, Set, Optional, Iterator, Tuple


class Mapping:
    """Define the mapping relationship from data source fields to Concept members

        This class maintains a bidirectional mapping relationship between data source fields and concept members,
        and provides functions for validation, querying, and conversion.
    """

    def __init__(
        self,
        dataSource: "DataSource",
        space: str,
        concept: "Concept",
        fieldToMemberMap: Dict[str, str],
    ):
        """Initialize Mapping

        Args:
            dataSource (DataSource): The associated data source instance
            space (str): The associated data source space
            concept (Concept): The associated Concept instance
            fieldToMemberMap (Dict[str, str]): Mapping from data source field names to Concept member names
                For example: {'column_name': 'memberName', 'another_col': 'otherMember'}

        Raises:
            TypeError: If parameter types are incorrect
            ValueError: If the mapping relationship is invalid
        """
        # Imports go here to ensure type checking works, but avoid top-level circular imports.
        from dolphin.lib.ontology.basic.concept import Concept
        from dolphin.lib.ontology.datasource.datasource import DataSource

        if not isinstance(dataSource, DataSource):
            raise TypeError("dataSource 必须是 DataSource 的实例")
        if not isinstance(concept, Concept):
            raise TypeError("concept 必须是 Concept 的实例")
        if not isinstance(fieldToMemberMap, dict):
            raise TypeError("fieldToMemberMap 必须是一个字典")
        if not fieldToMemberMap:
            raise ValueError("fieldToMemberMap 不能为空")

        # Verify whether the members of the mapping exist in Concept
        mappedMembers = set(fieldToMemberMap.values())
        conceptMembers = set(concept.members.keys())
        if not mappedMembers.issubset(conceptMembers):
            unknownMembers = mappedMembers - conceptMembers
            raise ValueError(
                f"映射包含未在 Concept '{concept.name}' 中定义的成员: {unknownMembers}"
            )

        # Verify the uniqueness of field names
        if len(set(fieldToMemberMap.keys())) != len(fieldToMemberMap):
            raise ValueError("字段名映射存在重复")

        # Verify the uniqueness of member names (optional, depending on whether multiple fields are allowed to map to the same member)
        if len(set(fieldToMemberMap.values())) != len(fieldToMemberMap):
            raise ValueError("成员名映射存在重复，每个字段必须映射到唯一的成员")

        self.dataSource = dataSource
        self.space = space
        self.concept = concept
        concept.addMapping(self)

        self.fieldToMemberMap = fieldToMemberMap

        self.dataSourceSchema = None

        # Build a reverse mapping for fast lookup
        self._memberToFieldMap = {
            member: field for field, member in fieldToMemberMap.items()
        }

    def __repr__(self) -> str:
        return (
            f"Mapping(dataSource='{self.dataSource.name}', "
            f"space='{self.space}', "
            f"concept='{self.concept.name}', "
            f"map={self.fieldToMemberMap})"
        )

    def getMemberForField(self, fieldName: str) -> Optional[str]:
        """Get the corresponding Concept member name from the data source field name

        Args:
            fieldName (str): The field name of the data source

        Returns:
            Optional[str]: The corresponding member name, or None if it does not exist
        """
        return self.fieldToMemberMap.get(fieldName)

    def getFieldForMember(self, memberName: str) -> Optional[str]:
        """Get the corresponding data source field name based on the Concept member name

        Args:
            memberName (str): The concept member name

        Returns:
            Optional[str]: The corresponding field name, or None if it does not exist
        """
        return self._memberToFieldMap.get(memberName)

    def getAllMappings(self) -> Iterator[Tuple[str, str]]:
        """Get the mapping relationship from all fields to members.

        Returns:
            Iterator[Tuple[str, str]]: An iterator of (field_name, member_name) tuples
        """
        return iter(self.fieldToMemberMap.items())

    def getUnmappedMembers(self) -> Set[str]:
        """Get unmapped concept members

        Returns:
            Set[str]: Set of unmapped concept member names
        """
        return set(self.concept.members.keys()) - set(self.fieldToMemberMap.values())

    def getDataSourceSchema(self) -> Dict[str, Any]:
        """Get the schema of the data source"""
        if self.dataSourceSchema:
            return self.dataSourceSchema

        schema = {}
        dataSourceSchema = self.dataSource.get_schema()
        for field, member in self.fieldToMemberMap.items():
            schemaPerSpace = dataSourceSchema[self.space]
            for singleSchema in schemaPerSpace:
                if singleSchema["name"] == field:
                    schema[field] = singleSchema["type"]
                    break
        self.dataSourceSchema = schema
        return schema

    def validateFieldValue(self, fieldName: str, value: Any) -> bool:
        """Validate whether the field value meets the type requirements of the corresponding member

        Args:
            fieldName (str): Name of the data source field
            value (Any): The value to be validated

        Returns:
            bool: Returns True if the value meets the type requirements

        Raises:
            KeyError: If the field name does not exist
        """
        memberName = self.getMemberForField(fieldName)
        if memberName is None:
            raise KeyError(f"字段 '{fieldName}' 未在映射中定义")
        return self.concept.validateMemberValue(memberName, value)

    def transformFieldValues(self, fieldValues: Dict[str, Any]) -> Dict[str, Any]:
        """Convert data source field values to concept member values

        Args:
            fieldValues (Dict[str, Any]): Mapping from field names to values

        Returns:
            Dict[str, Any]: Mapping from member names to values

        Raises:
            ValueError: If invalid field values exist
        """
        memberValues = {}
        for fieldName, value in fieldValues.items():
            memberName = self.getMemberForField(fieldName)
            if memberName is None:
                continue  # Skip unmapped fields
            if not self.validateFieldValue(fieldName, value):
                raise ValueError(
                    f"字段 '{fieldName}' 的值类型不符合成员 '{memberName}' 的要求"
                )
            memberValues[memberName] = value
        return memberValues
