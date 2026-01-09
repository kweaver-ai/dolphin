import json
import os
from typing import Dict, Any, List, Optional


class ObjectType:
    def __init__(
        self,
        title: str,
        description: str,
        properties: Dict[str, Dict[str, Any]],
        required: List[str],
    ):
        self.title: str = title
        self.description: str = description
        self.properties: Dict[str, Dict[str, Any]] = properties
        self.required: List[str] = required

    @classmethod
    def load(cls, jsonData: Dict[str, Any]) -> "ObjectType":
        """
        Load and validate ObjectType from JSON data.

        Args:
            jsonData: Dictionary representing the ObjectType.

        Returns:
            An ObjectType instance.

        Raises:
            ValueError: If the JSON data format is invalid.
        """
        requiredFields = ["title", "description", "type", "properties"]
        for field in requiredFields:
            if field not in jsonData:
                raise ValueError(f"Missing required field: {field}")

        if jsonData.get("type") != "object":
            raise ValueError(f"Type must be 'object', but got '{jsonData.get('type')}'")

        title = jsonData["title"]
        description = jsonData["description"]
        properties = jsonData["properties"]
        required = jsonData.get(
            "required", []
        )  # required is optional, but should be a list if present

        if not isinstance(title, str) or not title:
            raise ValueError("Field 'title' must be a non-empty string")
        if not isinstance(description, str):
            raise ValueError("Field 'description' must be a string")
        if not isinstance(properties, dict):
            raise ValueError("Field 'properties' must be a dictionary")
        if not isinstance(required, list):
            raise ValueError("Field 'required' must be a list")

        # Validate properties structure and required list
        for propName, propData in properties.items():
            if not isinstance(propData, dict):
                raise ValueError(f"Value of property '{propName}' must be a dictionary")
            if "type" not in propData or not isinstance(propData["type"], str):
                raise ValueError(
                    f"Property '{propName}' is missing or has an invalid 'type' field"
                )
            # Further validation based on type could be added here
            if "description" not in propData or not isinstance(
                propData["description"], str
            ):
                raise ValueError(
                    f"Property '{propName}' is missing or has an invalid 'description' field"
                )

        for reqProp in required:
            if reqProp not in properties:
                raise ValueError(
                    f"Required property '{reqProp}' is not defined in properties"
                )

        return cls(
            title=title,
            description=description,
            properties=properties,
            required=required,
        )


class ObjectTypeFactory:
    def __init__(self):
        self.objectTypes: Dict[str, ObjectType] = {}

    def load_from_json(self, json_data: Dict[str, Any]):
        try:
            objectTypeInstance = ObjectType.load(json_data)
            self.objectTypes[objectTypeInstance.title] = objectTypeInstance
        except Exception as e:
            raise Exception(
                f"An unexpected error occurred while loading ObjectType from {json_data}: {e}"
            ) from e

    def load(self, filepath: str):
        """
        Load an ObjectType from the specified .type file.

        Args:
            filepath: The path to the .type file.

        Raises:
            FileNotFoundError: If the file does not exist or is not a file.
            ValueError: If the file content is not valid JSON or the ObjectType definition is invalid.
            json.JSONDecodeError: If the file content is not valid JSON.
            Exception: For other unexpected errors during file processing.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found or is not a file: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            jsonData = json.load(f)

        self.load_from_json(jsonData)

    def getTypes(self, titles: Optional[List[str]] = None) -> List[ObjectType]:
        """
        Get all loaded ObjectType instances.

        Returns:
            A list of all loaded ObjectType instances.
        """
        if titles is None:
            return list(self.objectTypes.values())
        else:
            for title in titles:
                if title not in self.objectTypes:
                    raise ValueError(f"ObjectType title '{title}' not found")
            return [self.objectTypes[title] for title in titles]

    @staticmethod
    def getOpenaiJsonSchema(objectTypes: List[ObjectType]) -> Dict[str, Any]:
        """
        Convert a list of ObjectType instances to OpenAI JSON Schema format.

        Args:
            objectTypes: A list of ObjectType instances.

        Returns:
            A string representing the OpenAI JSON Schema for tools/functions.
        """
        schemas = []
        for objectType in objectTypes:
            schema = {
                "type": "function",
                "function": {
                    "name": objectType.title,
                    "description": objectType.description,
                    "parameters": {
                        "type": "object",
                        "properties": objectType.properties,
                    },
                },
            }
            # Only include 'required' key if the list is not empty
            if objectType.required:
                schema["function"]["parameters"]["required"] = objectType.required

            schemas.append(schema)
        return schemas
