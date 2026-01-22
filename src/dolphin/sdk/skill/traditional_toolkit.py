from typing import Dict, List, Any, Callable
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.utils.tools import Tool


class TriditionalToolkit(Skillkit):
    """
    Traditional toolkit that wraps Tools as OpenAI Functions
    """

    def __init__(self, tools: Dict[str, Tool] = None):
        """
        Initialize with a dictionary of tools

        Args:
            tools: Dictionary mapping tool names to Tool instances
        """
        super().__init__()
        self.tools = tools or {}
        self.openai_functions = self._create_openai_functions()

    def getName(self) -> str:
        """Get the toolkit name"""
        return "triditional_toolkit"

    def _createSkills(self) -> List[SkillFunction]:
        """Create all skill functions wrapped from tools"""
        return list(self.openai_functions.values())

    @staticmethod
    def buildFromTooldict(tooldict: Dict[str, Tool]) -> "TriditionalToolkit":
        """
        Build TriditionalToolkit from a dictionary of tools

        Args:
            tooldict: Dictionary mapping tool names to Tool instances

        Returns:
            TriditionalToolkit instance
        """
        return TriditionalToolkit(tooldict)

    def _create_openai_functions(self) -> Dict[str, SkillFunction]:
        """
        Create skill functions from the tools

        Returns:
            Dictionary mapping function names to SkillFunction instances
        """
        openai_functions = {}

        for tool_name, tool in self.tools.items():
            # Create a wrapper function for the tool
            wrapper_func = self._create_tool_wrapper(tool, tool_name)

            # Create OpenAI tool schema from tool's metadata, use tool_name as function name
            openai_tool_schema = self._tool_to_openai_schema(tool, tool_name)

            # Create SkillFunction with custom schema and tool type information
            openai_function = SkillFunction(
                func=wrapper_func,
                openai_tool_schema=openai_tool_schema,
                result_process_strategies=tool.result_process_strategy_cfg,
            )

            # Add tool type information to the SkillFunction
            openai_function.original_tool = tool
            
            # Copy interrupt_config from tool to SkillFunction if it exists
            if hasattr(tool, 'interrupt_config'):
                openai_function.interrupt_config = tool.interrupt_config

            openai_functions[tool_name] = openai_function

        return openai_functions

    def _create_tool_wrapper(self, tool: Tool, tool_name: str) -> Callable:
        """
        Create a wrapper function for the tool that matches OpenAI function signature

        Args:
            tool: The Tool instance to wrap
            tool_name: The name to use for the function

        Returns:
            Callable wrapper function (async generator for streaming tools)
        """

        async def async_wrapper(**kwargs):
            """
            Async wrapper function that calls the tool's method

            Args:
                **kwargs: Arguments to pass to the tool (should include tool_input and optionally props)

            Yields:
                Tool execution results (streaming for tools with stream methods)
            """
            # Merge parameters to avoid duplicate keyword arguments
            tool_kwargs = {}
            if "tool_input" in kwargs:
                # If tool_input is a dictionary, unpack its contents
                tool_input = kwargs["tool_input"]
                if isinstance(tool_input, dict):
                    tool_kwargs.update(tool_input)
                else:
                    tool_kwargs["tool_input"] = tool_input

            # Process the props parameter to avoid duplication
            if "props" in kwargs:
                tool_kwargs["props"] = kwargs["props"]

            # Add additional parameters
            for key, value in kwargs.items():
                if key not in ["tool_input", "props"]:
                    tool_kwargs[key] = value

            # Priority order: arun_stream > run_stream > run
            if hasattr(tool, "arun_stream"):
                # For async streaming tools, yield each result as it comes
                async_gen = tool.arun_stream(**kwargs)
                async for result in async_gen:
                    yield result
            elif hasattr(tool, "run_stream"):
                # For sync streaming tools, convert to async generator
                sync_gen = tool.run_stream(**kwargs)
                for result in sync_gen:
                    yield result
            elif hasattr(tool, "run"):
                # For non-streaming tools, yield single result
                result = tool.run(**kwargs)
                yield result
            else:
                raise ValueError(
                    f"Tool {tool_name} has no run, run_stream, or arun_stream method"
                )

        # Set function metadata for OpenAI schema generation
        async_wrapper.__name__ = tool_name
        async_wrapper.__doc__ = self._generate_function_docstring(tool)

        return async_wrapper

    def _generate_function_docstring(self, tool: Tool) -> str:
        """
        Generate a docstring for the wrapper function based on tool metadata

        Args:
            tool: The Tool instance

        Returns:
            Formatted docstring
        """
        docstring_parts = [tool.description]

        if tool.inputs:
            docstring_parts.append("\nArgs:")
            for param_name, param_info in tool.inputs.items():
                param_desc = param_info.get("description", "")
                param_type = param_info.get("type", "Any")
                required = param_info.get("required", True)
                required_text = " (required)" if required else " (optional)"
                docstring_parts.append(
                    f"    {param_name} ({param_type}): {param_desc}{required_text}"
                )

        if tool.outputs:
            docstring_parts.append("\nReturns:")
            for output_name, output_info in tool.outputs.items():
                output_desc = output_info.get("description", "")
                output_type = output_info.get("type", "Any")
                docstring_parts.append(f"    {output_type}: {output_desc}")

        return "\n".join(docstring_parts)

    def _tool_to_openai_schema(self, tool: Tool, tool_name: str) -> Dict[str, Any]:
        """
        Convert Tool metadata to OpenAI tool schema

        Args:
            tool: The Tool instance
            tool_name: The name to use for the function

        Returns:
            OpenAI tool schema dictionary
        """
        # Build parameters schema from tool inputs
        if hasattr(tool, "inputs_schema") and tool.inputs_schema:
            parameters_schema = tool.inputs_schema
        else:
            properties = {}
            required = []

            for param_name, param_info in tool.inputs.items():
                param_type = param_info.get("type", "string")
                param_desc = param_info.get("description", "")
                is_required = param_info.get("required", True)

                # Convert type to JSON schema type
                json_type = self._convert_type_to_json_schema(param_type)

                properties[param_name] = {"type": json_type, "description": param_desc}

                if is_required:
                    required.append(param_name)

            parameters_schema = {"type": "object", "properties": properties}

            if required:
                parameters_schema["required"] = required

        # Build complete OpenAI tool schema
        openai_tool_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool.description,
                "parameters": parameters_schema,
            },
        }

        return openai_tool_schema

    def _convert_type_to_json_schema(self, param_type: Any) -> str:
        """
        Convert parameter type to JSON schema type

        Args:
            param_type: Parameter type (can be str, type, or other)

        Returns:
            JSON schema type string
        """
        if isinstance(param_type, str):
            type_mapping = {
                "string": "string",
                "str": "string",
                "int": "integer",
                "integer": "integer",
                "float": "number",
                "number": "number",
                "bool": "boolean",
                "boolean": "boolean",
                "list": "array",
                "array": "array",
                "dict": "object",
                "object": "object",
            }
            return type_mapping.get(param_type.lower(), "string")
        elif param_type is str:
            return "string"
        elif param_type is int:
            return "integer"
        elif param_type is float:
            return "number"
        elif param_type is bool:
            return "boolean"
        elif param_type is list:
            return "array"
        elif param_type is dict:
            return "object"
        else:
            return "string"  # Default fallback
