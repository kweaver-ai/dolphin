from typing import Any, Dict, Iterator, List, Optional
import ast
import json

from dolphin.core.logging.logger import get_logger

logger = get_logger("utils.tools")


def safe_json_loads(json_str: str, strict: bool = True) -> Dict[str, Any]:
    """A safe JSON parsing function that supports multiple parsing strategies.

        Args:
            json_str: The JSON string to be parsed.
            strict: Whether to use strict mode.

        Returns:
            The parsed dictionary object.

        Raises:
            ValueError: When all parsing strategies fail.
    """
    if not json_str or not json_str.strip():
        return {}

    json_str = json_str.strip()

    # Strategy 1: Use ast.literal_eval for safer parsing
    try:
        value = ast.literal_eval(json_str)
        if isinstance(value, dict) or isinstance(value, list):
            return value
    except Exception:
        pass

    # Strategy 2: Use standard json.loads with strict mode
    try:
        return json.loads(json_str, strict=strict)
    except Exception:
        pass

    # Strategy 3: Replace single quotes with double quotes then parse
    try:
        normalized_content = json_str.replace("'", '"')
        return json.loads(normalized_content, strict=strict)
    except Exception:
        pass

    # Strategy 4: Try non-strict mode if we were in strict mode
    if strict:
        try:
            return json.loads(json_str, strict=False)
        except Exception:
            pass

    # Strategy 6: Advanced string cleaning
    try:
        # Clean up common formatting issues to improve fault tolerance
        if json_str.startswith('{\\"'):
            cleaned = json_str.replace('\\"', '"')
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    # Strategy 7: Replace newlines with spaces
    try:
        cleaned = json_str.replace("\n", " ")
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    # Strategy 8: Append missing closing brace if exactly one more open brace
    try:
        open_brace = json_str.count("{")
        close_brace = json_str.count("}")
        if open_brace == close_brace + 1:
            appended = json_str + "}"
            return json.loads(appended, strict=False)
    except Exception:
        pass

    # Strategy 9: Handle malformed empty object like '{"}' -> treat as {}
    try:
        stripped = json_str.strip()
        if stripped == '{"}':
            return {}
    except Exception:
        pass

    raise ValueError(f"Failed to parse JSON: {json_str}")


def safe_jsonl_loads(jsonl_str: str) -> List[Dict[str, Any]]:
    """Safe JSONL parsing function

        Args:
            jsonl_str: JSONL string to be parsed

        Returns:
            List of parsed dictionaries

        Raises:
            ValueError: If parsing fails
    """
    jsonl_str = jsonl_str.strip()
    if not jsonl_str:
        return []

    results = []
    try:
        results = json.loads(jsonl_str, strict=False)
    except Exception:
        try:
            results = ast.literal_eval(jsonl_str)
            if isinstance(results, list):
                return results
        except Exception:
            pass

    if results:
        if isinstance(results, list):
            return results
        if isinstance(results, dict):
            for key, value in results.items():
                if isinstance(value, list):
                    return value

    results = []
    for line_num, line in enumerate(jsonl_str.split("\n"), 1):
        line = line.strip()
        if not line:
            continue

        try:
            obj = safe_json_loads(line, strict=False)
            results.append(obj)
        except ValueError as e:
            logger.error(f"Failed to parse JSONL line {line_num}: {e}")
            logger.error(f"Line content: {line}")
            raise ValueError(f"Invalid JSON format in JSONL line {line_num}: {e}")

    return results


def extract_json_from_response(response_str: str) -> str:
    """Extract JSON content from response string (handling code block markers)

        Args:
            response_str: Original response string

        Returns:
            Extracted JSON string
    """
    response_str = response_str.strip()

    # Process ```json code block
    if "```json" in response_str:
        start = response_str.find("```json") + 7
        end = response_str.find("```", start)
        if end != -1:
            return response_str[start:end].strip()

    # Process generic code blocks
    elif response_str.startswith("```") and response_str.endswith("```"):
        lines = response_str.split("\n")
        if len(lines) > 2:
            return "\n".join(lines[1:-1])

    elif response_str.startswith("{"):
        # Find the matching } considering nested braces
        start = 0
        count = 1
        end = -1
        for i in range(1, len(response_str)):
            if response_str[i] == "{":
                count += 1
            elif response_str[i] == "}":
                count -= 1
                if count == 0:
                    end = i
                    break
        if end != -1:
            return response_str[start : end + 1].strip()

    return response_str


def extract_jsonl_from_response(response_str: str) -> str:
    """Extract JSONL content from response string (handling code block markers)

        Args:
            response_str: Original response string

        Returns:
            Extracted JSONL string
    """
    response_str = response_str.strip()

    # Handle ```jsonl or ```json code blocks
    start_markers = ["```jsonl", "```json"]
    for marker in start_markers:
        if marker in response_str:
            start = response_str.find(marker) + len(marker)
            end = response_str.find("```", start)
            if end != -1:
                return response_str[start:end].strip()
            break

    # Process generic code blocks
    if response_str.startswith("```") and response_str.endswith("```"):
        lines = response_str.split("\n")
        if len(lines) > 2:
            return "\n".join(lines[1:-1])

    elif response_str.startswith("["):
        # Find the matching ] considering nested braces
        start = 0
        count = 1
        end = -1
        for i in range(1, len(response_str)):
            if response_str[i] == "[":
                count += 1
            elif response_str[i] == "]":
                count -= 1
                if count == 0:
                    end = i
                    break
        if end != -1:
            return response_str[start : end + 1].strip()

    return response_str


def extract_json(content: str) -> Dict[str, Any]:
    """Extract JSON content from response string (handling code block markers)

        Args:
            content: Original response string
    """
    content = extract_json_from_response(content)
    result = safe_json_loads(content)
    if isinstance(result, dict) or isinstance(result, list):
        return result
    else:
        raise ValueError(f"Invalid JSON format: {content}")


def extract_jsonl(content: str) -> List[Dict[str, Any]]:
    """Extract JSONL content from response string (handling code block markers)

        Args:
            content: Original response string
    """
    content = extract_jsonl_from_response(content)
    result = safe_jsonl_loads(content)
    if isinstance(result, list):
        return result
    else:
        raise ValueError(f"Invalid JSONL format: {content}")


class Tool:
    # The unique name of the tool that clearly communicates its purpose
    name: str
    # Tool description, explaining the functions of the tool, facilitating the selection and invocation of LLM
    description: str
    # Tool type, eg: flow, component, api, etc
    # type: str
    # Input parameters of the tool
    inputs: Dict
    # Output format of the tool
    outputs: Dict

    result_process_strategy_cfg: list[Dict[str, str]] = None

    def __init__(
        self,
        name: str,
        description: str,
        inputs: Dict,
        outputs: Dict,
        props: Optional[dict] = None,
        result_process_strategy_cfg: list[Dict[str, str]] = None,
    ):
        self.name = name
        self.description = description
        self.inputs = inputs
        self.outputs = outputs
        self.props = props
        self.intervention = props.get("intervention", False)
        self.result_process_strategy_cfg = result_process_strategy_cfg

    def tool_info(self) -> dict:
        """The tool's information."""
        return {
            "name": self.name,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }

    def run(self, **kwargs) -> Any:
        """
        Run the tool
        """
        raise NotImplementedError

    async def arun(self, **kwargs) -> Any:
        """
        Run the tool asynchronously.
        """
        raise NotImplementedError

    def run_stream(self, **kwargs) -> Iterator[Any]:
        """
        Run the tool with streaming output.
        """
        raise NotImplementedError

    async def arun_stream(self, **kwargs) -> Iterator[Any]:
        """
        Run the tool with streaming output asynchronously.
        """
        raise NotImplementedError


class ToolInterrupt(Exception):
    """Exception raised when the tool is interrupted."""

    def __init__(
        self,
        message="The tool was interrupted.",
        tool_name: str = None,
        tool_args: List[Dict] = None,
        tool_config: Dict = None,
        *args,
        **kwargs,
    ):
        super().__init__(message, *args, **kwargs)
        self.tool_name = tool_name if tool_name else ""
        self.tool_args = tool_args if tool_args else []
        self.tool_config = tool_config if tool_config else {}
