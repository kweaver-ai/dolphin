from abc import ABC, abstractmethod
from typing import Dict, Any, List
from enum import Enum

from dolphin.core.common.enums import MessageRole

# Import existing JSON utilities
from dolphin.core.utils.tools import (
    safe_json_loads,
)
from dolphin.core.logging.logger import get_logger

logger = get_logger("type")


class OutputFormatType(Enum):
    """Enum for output format types"""

    JSON = "json"
    JSONL = "jsonl"
    OBJECT = "object"
    LIST_STR = "list_str"


class OutputFormat(ABC):
    """Abstract base class for output format

        Defines the standard interface for output format handling:
        1. Add format constraint prompts
        2. Parse response results
        3. Get format description information
    """

    def __init__(self, formatType: OutputFormatType):
        """Initialize output format

        Args:
            formatType: Output format type
        """
        self.formatType = formatType

    @abstractmethod
    def addFormatConstraintToMessages(self, messages) -> None:
        """Add format constraint prompts to Messages

        Args:
            messages: Messages object, used to add format constraint prompts
        """
        pass

    @abstractmethod
    def parseResponse(self, responseStr: str) -> Any:
        """Parse the response string into the corresponding data structure

        Args:
            responseStr: The string of the LLM response

        Returns:
            The parsed data structure
        """
        pass

    @abstractmethod
    def getFormatDescription(self) -> str:
        """Get the format description for explaining output format requirements to users.

        Returns:
            Format description string
        """
        pass

    def getFormatType(self) -> OutputFormatType:
        """Get output format type"""
        return self.formatType

    def toDict(self) -> Dict[str, Any]:
        """Convert the output format to dictionary format

        Returns:
            Dictionary representation of format information
        """
        return {"format_type": self.formatType.value}

    def __str__(self) -> str:
        """String Representation"""
        return self.formatType.value

    def __repr__(self) -> str:
        """Debug string representation"""
        return f"{self.__class__.__name__}(format={self.formatType.value})"


class JsonOutputFormat(OutputFormat):
    """JSON format output processor"""

    def __init__(self):
        super().__init__(OutputFormatType.JSON)

    def addFormatConstraintToMessages(self, messages) -> None:
        """Add JSON format constraints to Messages"""
        constraint_message = (
            "请以标准 JSON 格式输出结果。确保输出是有效的 JSON 对象，"
            "不要包含任何额外的文本说明或代码块标记。"
        )
        messages.append_message(MessageRole.USER, constraint_message)

    def parseResponse(self, responseStr: str) -> Dict[str, Any]:
        """Parse JSON response into a dictionary

        Args:
            responseStr: Response string

        Returns:
            Parsed dictionary object

        Raises:
            ValueError: If JSON parsing fails
        """
        from dolphin.core.utils.tools import extract_json

        result = extract_json(responseStr)
        if result is None:
            logger.error("Failed to parse JSON response")
            logger.error(f"Response content: {responseStr}")
            raise ValueError("Invalid JSON format in response")

        return result

    def getFormatDescription(self) -> str:
        """Get JSON format description"""
        return "输出格式：标准 JSON 对象"


class JsonlOutputFormat(OutputFormat):
    """JSONL format output processor"""

    def __init__(self):
        super().__init__(OutputFormatType.JSONL)

    def addFormatConstraintToMessages(self, messages) -> None:
        """Add JSONL format constraints to Messages"""
        constraint_message = "请以 JSON Lines (JSONL) 格式输出结果,不要包含任何额外的文本说明或代码块标记。"
        messages.append_message(MessageRole.USER, constraint_message)

    def parseResponse(self, responseStr: str) -> List[Dict[str, Any]]:
        """Parse JSONL response into a list of dictionaries

        Args:
            responseStr: Response string

        Returns:
            List of parsed dictionaries

        Raises:
            ValueError: If JSONL parsing fails
        """
        from dolphin.core.utils.tools import extract_jsonl

        results = extract_jsonl(responseStr)
        if results is None:
            logger.error("Failed to parse JSONL response")
            logger.error(f"Response content: {responseStr}")
            raise ValueError("Invalid JSONL format in response")
        return results

    def getFormatDescription(self) -> str:
        """Get JSONL format description"""
        return "输出格式：JSON Lines，每行一个 JSON 对象"


class ListStrOutputFormat(OutputFormat):
    """List string format output processor, output format is List[str]"""

    def __init__(self):
        super().__init__(OutputFormatType.LIST_STR)

    def addFormatConstraintToMessages(self, messages) -> None:
        """Add list string format constraints to Messages"""
        constraint_message = (
            "请以字符串列表格式输出结果。输出一个包含多个字符串元素的列表，"
            '格式为JSON数组，每个元素都是字符串类型，例如：["item1", "item2", "item3"]。'
            "不要包含任何额外的文本说明或代码块标记。"
        )
        messages.append_message(MessageRole.USER, constraint_message)

    def parseResponse(self, responseStr: str) -> List[str]:
        """Parse a list string response into a string list

        Args:
            responseStr: Response string

        Returns:
            Parsed string list

        Raises:
            ValueError: If list parsing fails
        """
        # Try to parse directly as JSON
        try:
            result = safe_json_loads(responseStr.strip())
            if isinstance(result, list) and all(
                isinstance(item, str) for item in result
            ):
                return result
            else:
                # If not a list of strings, attempt to convert to a list of strings
                if isinstance(result, list):
                    return [str(item) for item in result]
                else:
                    raise ValueError("Response is not a list")
        except ValueError:
            # Direct parsing failed, try extracting JSON content
            pass

        # Try to extract a JSON array from the response
        try:
            from dolphin.core.utils.tools import extract_json

            result = extract_json(responseStr)
            if isinstance(result, list):
                # Ensure all elements are strings
                return [str(item) for item in result]
            else:
                raise ValueError("Extracted content is not a list")
        except ValueError:
            pass

        # If JSON parsing fails, try simple line splitting
        logger.warning("Failed to parse as JSON list, attempting line-based parsing")
        lines = [
            line.strip() for line in responseStr.strip().split("\n") if line.strip()
        ]
        if lines:
            return lines

        # Fallback: Return the original response as a list of a single string
        logger.warning(
            "All parsing methods failed, returning response as single string list"
        )
        return [responseStr.strip()]

    def getFormatDescription(self) -> str:
        """Get list string format description"""
        return "输出格式：字符串列表 List[str]"


class ObjectTypeOutputFormat(OutputFormat):
    """Object type format output processor"""

    def __init__(self, objectTypeName: str, objectTypeDefinition: Dict[str, Any]):
        """Initialize object type output format

        Args:
            objectTypeName: Object type name
            objectTypeDefinition: Object type definition
        """
        super().__init__(OutputFormatType.OBJECT)
        self.objectTypeName = objectTypeName
        self.objectTypeDefinition = objectTypeDefinition

    def addFormatConstraintToMessages(self, messages) -> None:
        """Add object type format constraints to Messages"""
        constraint_message = self._buildConstraintMessage()
        messages.append_message(MessageRole.USER, constraint_message)

    def _buildConstraintMessage(self) -> str:
        """Build object type format constraint message

                For ObjectType format, the specific schema is passed through function call tools,
                here we only need to indicate that tool invocation should be used
        """
        return f"请使用 {self.objectTypeName} 工具调用来生成结构化输出。"

    def generateFunctionCallTools(self) -> List[Dict[str, Any]]:
        """Generate the tools parameter value for function_call

        Returns:
            List of tool definitions, used for LLM's function_call
        """
        if not self.objectTypeDefinition:
            raise ValueError(
                f"Object type definition not found for '{self.objectTypeName}'"
            )

        tool_definition = {
            "type": "function",
            "function": {
                "name": self.objectTypeName,
                "description": self.objectTypeDefinition.get(
                    "description", f"{self.objectTypeName} object"
                ),
                "parameters": {
                    "type": "object",
                    "properties": self.objectTypeDefinition.get("properties", {}),
                },
            },
        }

        # Only add when the required list is not empty
        required = self.objectTypeDefinition.get("required", [])
        if required:
            tool_definition["function"]["parameters"]["required"] = required

        return [tool_definition]

    def parseResponse(self, responseStr: str) -> Dict[str, Any]:
        """Parse object type response

                For object types, the response is usually the parameter of function_call,
                but it may also be a JSON-formatted object definition.

        Args:
            responseStr: Response string

        Returns:
            Parsed object
        """
        try:
            from dolphin.core.utils.tools import extract_json

            return extract_json(responseStr)
        except ValueError:
            # Both JSON extraction and parsing have failed, return the original string as the content field.
            pass

        # If parsing fails, return the original string as the content field
        logger.warning(
            "Failed to parse object type response as JSON, returning as text content"
        )
        return {"content": responseStr}

    def getFormatDescription(self) -> str:
        """Get object type format description"""
        return f"输出格式：{self.objectTypeName} 对象类型"

    def getObjectTypeName(self) -> str:
        """Get object type name"""
        return self.objectTypeName

    def getObjectTypeDefinition(self) -> Dict[str, Any]:
        """Get object type definition"""
        return self.objectTypeDefinition

    def toDict(self) -> Dict[str, Any]:
        """Convert the output format to dictionary format"""
        result = super().toDict()
        result.update(
            {
                "object_type_name": self.objectTypeName,
                "object_type_definition": self.objectTypeDefinition,
            }
        )
        return result


class OutputFormatFactory:
    """Format factory class"""

    @staticmethod
    def parseFromString(outputValue: str, globalTypes=None) -> OutputFormat:
        """Parse output format from string

        Args:
            outputValue: Output format string, such as "json", "jsonl", "obj/UserProfile"
            globalTypes: ObjectTypeFactory instance, used to retrieve object type definitions

        Returns:
            An OutputFormat instance

        Raises:
            ValueError: When the format is invalid or the object type does not exist
        """
        if not outputValue or not outputValue.strip():
            raise ValueError("Output format value cannot be empty")

        outputValue = outputValue.strip().strip('"').strip("'")

        # Processing JSON format
        if outputValue.lower() == "json":
            return JsonOutputFormat()

        # Processing JSONL format
        elif outputValue.lower() == "jsonl":
            return JsonlOutputFormat()

        # Process list string format
        elif outputValue.lower() == "list_str":
            return ListStrOutputFormat()

        # Object type format: obj/TypeName
        elif outputValue.startswith("obj/"):
            objectTypeName = outputValue[4:]  # Remove the "obj/" prefix

            if not objectTypeName:
                raise ValueError(
                    "Object type name cannot be empty in 'obj/TypeName' format"
                )

            # Get type definitions from global_types
            objectTypeDefinition = None
            if globalTypes:
                try:
                    objectTypes = globalTypes.getTypes([objectTypeName])
                    if objectTypes:
                        objectType = objectTypes[0]
                        objectTypeDefinition = {
                            "title": objectType.title,
                            "description": objectType.description,
                            "type": "object",
                            "properties": objectType.properties,
                            "required": objectType.required,
                        }
                except Exception as e:
                    logger.warning(
                        f"Failed to get object type '{objectTypeName}' from global_types: {e}"
                    )
                    raise ValueError(
                        f"Object type '{objectTypeName}' not found in global_types"
                    )
            else:
                logger.warning(
                    "global_types not provided, object type definition will be None"
                )
                raise ValueError("global_types is required for object type format")

            return ObjectTypeOutputFormat(objectTypeName, objectTypeDefinition)

        else:
            raise ValueError(
                f"Invalid output format: '{outputValue}'. "
                + "Supported formats: 'json', 'jsonl', 'list_str', 'obj/TypeName'"
            )
