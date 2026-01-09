# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
from inspect import Parameter, signature
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, List

from docstring_parser import parse
from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator as JSONValidator
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo
import re
import aiohttp


def to_pascal(snake: str) -> str:
    """Convert a snake_case string to PascalCase.

    Args:
        snake (str): The snake_case string to be converted.

    Returns:
        str: The converted PascalCase string.
    """
    # Check if the string is already in PascalCase
    if re.match(r"^[A-Z][a-zA-Z0-9]*([A-Z][a-zA-Z0-9]*)*$", snake):
        return snake
    # Remove leading and trailing underscores
    snake = snake.strip("_")
    # Replace multiple underscores with a single one
    snake = re.sub("_+", "_", snake)
    # Convert to PascalCase
    return re.sub(
        "_([0-9A-Za-z])",
        lambda m: m.group(1).upper(),
        snake.title(),
    )


def get_pydantic_object_schema(pydantic_params: BaseModel) -> Dict:
    r"""Get the JSON schema of a Pydantic model.

    Args:
        pydantic_params (BaseModel): The Pydantic model to retrieve the schema
            for.

    Returns:
        dict: The JSON schema of the Pydantic model.
    """
    # Import typing module to provide namespace for types like Union, List, etc.
    import typing
    
    # Rebuild model with typing namespace to resolve forward references
    # This is needed when dynamic models use types like Union[str, List[str]]
    try:
        pydantic_params.model_rebuild(_types_namespace={"Union": typing.Union, "List": typing.List, "Optional": typing.Optional, "Any": typing.Any})
    except Exception:
        # If rebuild fails, try without (may work for simple models)
        pass
    
    return pydantic_params.model_json_schema()


def _remove_a_key(d: Dict, remove_key: Any) -> None:
    r"""Remove a key from a dictionary recursively."""
    if isinstance(d, dict):
        for key in list(d.keys()):
            if key == remove_key:
                del d[key]
            else:
                _remove_a_key(d[key], remove_key)


def get_openai_function_schema(func: Callable) -> Dict[str, Any]:
    r"""Generates a schema dict for an OpenAI function based on its signature.

    This function is deprecated and will be replaced by
    :obj:`get_openai_tool_schema()` in future versions. It parses the
    function's parameters and docstring to construct a JSON schema-like
    dictionary.

    Args:
        func (Callable): The OpenAI function to generate the schema for.

    Returns:
        Dict[str, Any]: A dictionary representing the JSON schema of the
            function, including its name, description, and parameter
            specifications.
    """
    openai_function_schema = get_openai_tool_schema(func)["function"]
    return openai_function_schema


def get_openai_tool_schema(func: Callable) -> Dict[str, Any]:
    r"""Generates an OpenAI JSON schema from a given Python function.

    This function creates a schema compatible with OpenAI's API specifications,
    based on the provided Python function. It processes the function's
    parameters, types, and docstrings, and constructs a schema accordingly.

    Note:
        - Each parameter in `func` must have a type annotation; otherwise, it's
          treated as 'Any'.
        - Variable arguments (*args) and keyword arguments (**kwargs) are not
          supported and will be ignored.
        - A functional description including a brief and detailed explanation
          should be provided in the docstring of `func`.
        - All parameters of `func` must be described in its docstring.
        - Supported docstring styles: ReST, Google, Numpydoc, and Epydoc.

    Args:
        func (Callable): The Python function to be converted into an OpenAI
                         JSON schema.

    Returns:
        Dict[str, Any]: A dictionary representing the OpenAI JSON schema of
                the provided function.

    See Also:
        `OpenAI API Reference
            <https://platform.openai.com/docs/api-reference/assistants/object>`_
    """
    params: Mapping[str, Parameter] = signature(func).parameters
    fields: Dict[str, Tuple[type, FieldInfo]] = {}
    for param_name, p in params.items():
        param_type = p.annotation
        param_default = p.default
        param_kind = p.kind
        param_annotation = p.annotation
        # Variable parameters are not supported
        if (
            param_kind == Parameter.VAR_POSITIONAL
            or param_kind == Parameter.VAR_KEYWORD
        ):
            continue
        # If the parameter type is not specified, it defaults to typing.Any
        if param_annotation is Parameter.empty:
            param_type = Any
        # Check if the parameter has a default value
        if param_default is Parameter.empty:
            fields[param_name] = (param_type, FieldInfo())
        else:
            fields[param_name] = (param_type, FieldInfo(default=param_default))

    # Applying `create_model()` directly will result in a mypy error,
    # create an alias to avoid this.
    def _create_mol(name, field):
        return create_model(name, **field)

    model = _create_mol(to_pascal(func.__name__), fields)
    parameters_dict = get_pydantic_object_schema(model)
    # The `"title"` is generated by `model.model_json_schema()`
    # but is useless for openai json schema
    _remove_a_key(parameters_dict, "title")

    docstring = parse(func.__doc__ or "")
    for param in docstring.params:
        if (name := param.arg_name) in parameters_dict["properties"] and (
            description := param.description
        ):
            parameters_dict["properties"][name]["description"] = description

    short_description = docstring.short_description or ""
    long_description = docstring.long_description or ""
    if long_description:
        func_description = f"{short_description}\n{long_description}"
    else:
        func_description = short_description

    openai_function_schema = {
        "name": func.__name__,
        "description": func_description,
        "parameters": parameters_dict,
    }

    openai_tool_schema = {
        "type": "function",
        "function": openai_function_schema,
    }
    return openai_tool_schema


class OpenAIFunction:
    r"""An abstraction of a function that OpenAI chat models can call. See
    https://platform.openai.com/docs/api-reference/chat/create.

    By default, the tool schema will be parsed from the func, or you can
    provide a user-defined tool schema to override.

    Args:
        func (Callable): The function to call.The tool schema is parsed from
            the signature and docstring by default.
        openai_tool_schema (Optional[Dict[str, Any]], optional): A user-defined
            openai tool schema to override the default result.
            (default: :obj:`None`)
    """

    def __init__(
        self,
        func: Callable,
        openai_tool_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.func = func
        self.openai_tool_schema = openai_tool_schema or get_openai_tool_schema(func)

    @staticmethod
    def validate_openai_tool_schema(
        openai_tool_schema: Dict[str, Any],
    ) -> None:
        r"""Validates the OpenAI tool schema against
        :obj:`ToolAssistantToolsFunction`.
        This function checks if the provided :obj:`openai_tool_schema` adheres
        to the specifications required by OpenAI's
        :obj:`ToolAssistantToolsFunction`. It ensures that the function
        description and parameters are correctly formatted according to JSON
        Schema specifications.
        Args:
            openai_tool_schema (Dict[str, Any]): The OpenAI tool schema to
                validate.
        Raises:
            ValidationError: If the schema does not comply with the
                specifications.
            ValueError: If the function description or parameter descriptions
                are missing in the schema.
            SchemaError: If the parameters do not meet JSON Schema reference
                specifications.
        """
        # Check the type
        if not openai_tool_schema["type"]:
            raise ValueError("miss type")
        # Check the function description
        if not openai_tool_schema["function"]["description"]:
            raise ValueError("miss function description")

        # Validate whether parameters
        # meet the JSON Schema reference specifications.
        # See https://platform.openai.com/docs/guides/gpt/function-calling
        # for examples, and the
        # https://json-schema.org/understanding-json-schema/ for
        # documentation about the format.
        parameters = openai_tool_schema["function"]["parameters"]
        try:
            JSONValidator.check_schema(parameters)
        except SchemaError as e:
            raise e
        # Check the parameter description
        properties: Dict[str, Any] = parameters["properties"]
        for param_name in properties.keys():
            param_dict = properties[param_name]
            if "description" not in param_dict:
                raise ValueError(f'miss description of parameter "{param_name}"')

    def get_openai_tool_schema(self) -> Dict[str, Any]:
        r"""Gets the OpenAI tool schema for this function.

        This method returns the OpenAI tool schema associated with this
        function, after validating it to ensure it meets OpenAI's
        specifications.

        Returns:
            Dict[str, Any]: The OpenAI tool schema for this function.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema

    def set_openai_tool_schema(self, schema: Dict[str, Any]) -> None:
        r"""Sets the OpenAI tool schema for this function.

        Allows setting a custom OpenAI tool schema for this function.

        Args:
            schema (Dict[str, Any]): The OpenAI tool schema to set.
        """
        self.openai_tool_schema = schema

    def get_openai_function_schema(self) -> Dict[str, Any]:
        r"""Gets the schema of the function from the OpenAI tool schema.

        This method extracts and returns the function-specific part of the
        OpenAI tool schema associated with this function.

        Returns:
            Dict[str, Any]: The schema of the function within the OpenAI tool
                schema.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema["function"]

    def set_openai_function_schema(
        self,
        openai_function_schema: Dict[str, Any],
    ) -> None:
        r"""Sets the schema of the function within the OpenAI tool schema.

        Args:
            openai_function_schema (Dict[str, Any]): The function schema to set
                within the OpenAI tool schema.
        """
        self.openai_tool_schema["function"] = openai_function_schema

    def get_function_name(self) -> str:
        r"""Gets the name of the function from the OpenAI tool schema.

        Returns:
            str: The name of the function.
        """
        return self.openai_tool_schema["function"]["name"]

    def set_function_name(self, name: str) -> None:
        r"""Sets the name of the function in the OpenAI tool schema.

        Args:
            name (str): The name of the function to set.
        """
        self.openai_tool_schema["function"]["name"] = name

    def get_function_description(self) -> str:
        r"""Gets the description of the function from the OpenAI tool
        schema.

        Returns:
            str: The description of the function.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema["function"]["description"]

    def set_function_description(self, description: str) -> None:
        r"""Sets the description of the function in the OpenAI tool schema.

        Args:
            description (str): The description for the function.
        """
        self.openai_tool_schema["function"]["description"] = description

    def get_paramter_description(self, param_name: str) -> str:
        r"""Gets the description of a specific parameter from the function
        schema.

        Args:
            param_name (str): The name of the parameter to get the
                description.

        Returns:
            str: The description of the specified parameter.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema["function"]["parameters"]["properties"][
            param_name
        ]["description"]

    def set_paramter_description(
        self,
        param_name: str,
        description: str,
    ) -> None:
        r"""Sets the description for a specific parameter in the function
        schema.

        Args:
            param_name (str): The name of the parameter to set the description
                for.
            description (str): The description for the parameter.
        """
        self.openai_tool_schema["function"]["parameters"]["properties"][param_name][
            "description"
        ] = description

    def get_parameter(self, param_name: str) -> Dict[str, Any]:
        r"""Gets the schema for a specific parameter from the function schema.

        Args:
            param_name (str): The name of the parameter to get the schema.

        Returns:
            Dict[str, Any]: The schema of the specified parameter.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema["function"]["parameters"]["properties"][
            param_name
        ]

    def set_parameter(self, param_name: str, value: Dict[str, Any]):
        r"""Sets the schema for a specific parameter in the function schema.

        Args:
            param_name (str): The name of the parameter to set the schema for.
            value (Dict[str, Any]): The schema to set for the parameter.
        """
        try:
            JSONValidator.check_schema(value)
        except SchemaError as e:
            raise e
        self.openai_tool_schema["function"]["parameters"]["properties"][
            param_name
        ] = value

    @property
    def parameters(self) -> Dict[str, Any]:
        r"""Getter method for the property :obj:`parameters`.

        Returns:
            Dict[str, Any]: the dictionary containing information of
                parameters of this function.
        """
        self.validate_openai_tool_schema(self.openai_tool_schema)
        return self.openai_tool_schema["function"]["parameters"]["properties"]

    @parameters.setter
    def parameters(self, value: Dict[str, Any]) -> None:
        r"""Setter method for the property :obj:`parameters`. It will
        firstly check if the input parameters schema is valid. If invalid,
        the method will raise :obj:`jsonschema.exceptions.SchemaError`.

        Args:
            value (Dict[str, Any]): the new dictionary value for the
                function's parameters.
        """
        try:
            JSONValidator.check_schema(value)
        except SchemaError as e:
            raise e
        self.openai_tool_schema["function"]["parameters"]["properties"] = value


class SkillFunction(OpenAIFunction):
    def __init__(
        self,
        func: Callable,
        openai_tool_schema: Optional[Dict[str, Any]] = None,
        block_as_parameter: Optional[Tuple[str, str]] = None,
        result_process_strategies: Optional[List[Dict[str, str]]] = None,
        owner_skillkit: Optional[
            Any
        ] = None,  # Skillkit object (set by Skillkit._bindOwnerToSkills)
    ):
        super().__init__(func, openai_tool_schema)

        self.owner_skillkit = owner_skillkit

        self.block_as_parameter = block_as_parameter
        """Strategy for handling tool call results
                Example:
                [
                {"category": "llm", "strategy": "default"},
                {"category": "app", "strategy": "default"},
                ]
        """
        self.result_process_strategies = result_process_strategies or [
            {
                "strategy": "default",
                "category": "llm",
            },
            {
                "strategy": "default",
                "category": "app",
            },
        ]

    @property
    def owner_name(self) -> Optional[str]:
        """Get the owner skillkit name.

        Returns the skillkit name via getName() method.
        Returns None if no owner is set.
        """
        if self.owner_skillkit is None:
            return None
        if hasattr(self.owner_skillkit, "getName"):
            return self.owner_skillkit.getName()
        return None

    def get_owner_skillkit(self) -> Optional[Any]:
        """Get the owner skillkit object."""
        return self.owner_skillkit

    def set_owner_skillkit(self, owner_skillkit: Optional[Any]) -> None:
        """Set the owner skillkit object."""
        self.owner_skillkit = owner_skillkit

    def get_block_parameter_info(self):
        return self.block_as_parameter

    # Get result processing strategy
    def get_result_process_strategies(self):
        return self.result_process_strategies

    # Get the first available APP strategy
    def get_first_valid_app_strategy(self) -> Optional[str]:
        for strategy in self.result_process_strategies:
            if strategy.get("category") == "app":
                return strategy.get("strategy")
        return None

    # Get the first available LLM strategy
    def get_first_valid_llm_strategy(self) -> Optional[str]:
        for strategy in self.result_process_strategies:
            if strategy.get("category") == "llm":
                return strategy.get("strategy")
        return None


class DynamicAPISkillFunction(SkillFunction):
    """
    Initialize dynamic API tool

    Args:
        name: Tool name
        description: Tool description
        parameters: OpenAI function call parameter schema
        api_url: API endpoint URL
        original_schema: Original openapi schema information
        fixed_params: Fixed parameters dictionary
        headers: HTTP tool request headers dictionary (e.g., authentication info: x-account-type, x-account-id)
        result_process_strategies: Result processing strategies (optional), inherited from SkillFunction
        owner_skillkit: Owner skillkit (optional), inherited from SkillFunction
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        api_url: str,
        original_schema: Optional[Dict[str, Any]] = None,
        fixed_params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        result_process_strategies: Optional[List[Dict[str, str]]] = None,
        owner_skillkit: Optional[Any] = None,
    ):
        # Build OpenAI tool schema
        openai_tool_schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

        # Save dynamic tool-specific attributes (must be done before creating wrapper function)
        self.api_url = api_url
        self.original_schema = original_schema or {}
        self.fixed_params = fixed_params or {}
        self.headers = headers or {}

        # Create wrapper function that calls arun_stream
        # This ensures Skillkit correctly executes arun_stream when calling self.func
        async def wrapper_func(**kwargs):
            """Wrapper function that calls arun_stream"""
            async for result in self.arun_stream(**kwargs):
                yield result

        # Call parent class constructor
        super().__init__(
            func=wrapper_func,
            openai_tool_schema=openai_tool_schema,
            result_process_strategies=result_process_strategies,
            owner_skillkit=owner_skillkit,
        )

    async def arun_stream(self, **kwargs):
        """
        Call action API

        Args:
            **kwargs: Call parameters (including tool_input, props, gvp, etc.)

        Yields:
            API call result
        """
        if self.result_process_strategies != "kn_action_recall":
            yield {
                "error": "The system supports only the following policy: kn_action_recall."
            }
        try:
            # Extract parameters
            tool_input = kwargs.get("tool_input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}

            # Extract other parameters from kwargs (excluding system parameters)
            final_params = {
                k: v
                for k, v in kwargs.items()
                if k not in ["tool_input", "props", "gvp"]
            }
            # Merge parameters (tool_input takes priority)
            # final_params = {**params, **tool_input}
            # Apply fixed parameter replacement
            # Handle nested fixed_params structure with body, header, path, query keys
            if isinstance(self.fixed_params, dict):
                # Process body parameters - merge into final_params
                body_params = self.fixed_params.get("body")
                if isinstance(body_params, dict):
                    for param_name, fixed_value in body_params.items():
                        if fixed_value is not None:
                            final_params["body"][param_name] = fixed_value

                # Process header parameters - merge into final_params (special key)
                header_params = self.fixed_params.get("header")
                if isinstance(header_params, dict):
                    final_params["header"] = final_params.get("header", {})
                    for header_name, fixed_value in header_params.items():
                        if fixed_value is not None:
                            final_params["header"][header_name] = str(fixed_value)

                # Process path parameters - merge into final_params (special key)
                path_params = self.fixed_params.get("path")
                if isinstance(path_params, dict):
                    final_params["path"] = final_params.get("path", {})
                    for param_name, fixed_value in path_params.items():
                        if fixed_value is not None:
                            final_params["path"][param_name] = str(fixed_value)

                # Process query parameters - merge into final_params (special key)
                query_params = self.fixed_params.get("query")
                if isinstance(query_params, dict):
                    final_params["query"] = final_params.get("query", {})
                    for param_name, fixed_value in query_params.items():
                        if fixed_value is not None:
                            final_params["query"][param_name] = str(fixed_value)
            else:
                # Backward compatibility: flat fixed_params structure
                for param_name, fixed_value in self.fixed_params.items():
                    if fixed_value and param_name in final_params:
                        final_params[param_name] = fixed_value

            # Call API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=final_params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        yield result
                    else:
                        error_msg = f"API call failed: HTTP {response.status}"
                        error_text = await response.text()
                        yield {"error": error_msg, "details": error_text}

        except Exception as e:
            error_msg = f"Dynamic API tool execution error: {str(e)}"
            import traceback

            traceback.print_exc()
            yield {"error": error_msg, "traceback": traceback.format_exc()}
