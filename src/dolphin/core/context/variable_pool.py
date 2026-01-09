"""Dolphin Language SDK - Variable Pool Module

Variable Classification Description:
==============

1. User Variables
   - Variables defined by user scripts
   - Returned when retrieved via the get_user_variables() method
   - Example: result, user_input, calculation, etc.

2. Internal Variables
   - Automatically recognized: All variables starting with an underscore (_) are automatically treated as internal variables
   - Special internal variables: props, usage
   - Automatically excluded when retrieved via the get_user_variables() method

   List of internal variables:
   - _progress: Execution progress details
   - _user_id: User ID (optionally included)
   - _session_id: Session ID (optionally included)
   - _max_answer_len: Maximum answer length (optionally included)
   - _status: Current execution status
   - _previous_status: Previous execution status
   - props: Execution properties
   - usage: Usage statistics

Methods to retrieve variables:
- get_user_variables(): Get user variables, excluding all internal variables
- get_user_variables(include_system_context_vars=True): Get user variables, including system context variables
- get_all_variables(): Get all variables (including internal variables)
"""

import re

from dolphin.core.common.constants import KEY_STATUS, KEY_PREVIOUS_STATUS
from dolphin.core.common.types import SourceType, Var
from dolphin.core.context.var_output import VarOutput


class VariablePool:
    def __init__(self):
        self.variable_pool = {}

    def copy(self):
        new_variable_pool = VariablePool()
        new_variable_pool.variable_pool = self.variable_pool.copy()
        return new_variable_pool

    def init_variables(self, variables):
        self.variable_pool = {name: Var(value) for name, value in variables.items()}

    def contain_var(self, name):
        return name in self.variable_pool

    def get_var(self, name):
        return self.variable_pool.get(name)

    def get_var_value(self, name, default_value=None):
        var = self.variable_pool.get(name)
        if not var:
            return default_value

        val = var.value
        # Compatibility with dictionary structure after restoration from snapshot (VarOutput.to_dict format)
        if isinstance(val, dict) and "value" in val and "source_type" in val:
            inner = val.get("value")
            # List scenario: extract the value of each element
            if isinstance(inner, list):
                return [
                    (
                        item.get("value")
                        if isinstance(item, dict) and "value" in item
                        else item
                    )
                    for item in inner
                ]
            # Normal scenario: return the value field directly
            return inner

        return val

    def get_var_path_value(self, varpath, default_value=None):
        """
        Get value from variable pool using dot notation path
        Example: get_var_path_value('user.profile.name')
        :param varpath: Variable path with dot notation
        :return: Value at the specified path
        :raises: AttributeError if variable or path not found
        """
        if not varpath:
            return default_value

        parts = varpath.split(".")
        base_var = parts[0]

        # Get base variable
        var = self.get_var(base_var)
        if var is None:
            return default_value

        value = var.value

        # Navigate through the path
        for part in parts[1:]:
            if isinstance(value, dict):
                if part not in value:
                    return default_value
                value = value[part]
            else:
                return default_value

        return value

    def get_all_variables(self):
        return {name: var.to_dict() for name, var in self.variable_pool.items()}

    def get_user_variables(self, include_system_context_vars=False):
        """Get user-defined variables, excluding internal variables.

        Args:
            include_system_context_vars: Whether to include system context variables (e.g., _user_id, _session_id, etc.)
                                                 Default is False for backward compatibility

                Internal variable rules:
                - All variables starting with an underscore (_) are automatically considered internal variables (unless explicitly included)
                - Special internal variables: props, usage

                If include_system_context_vars=True, the following system context variables will be included:
                - _user_id: User ID
                - _session_id: Session ID
                - _max_answer_len: Maximum answer length
        """
        # Automatically recognize all variables starting with an underscore as built-in variables
        underscore_vars = {
            name for name in self.variable_pool.keys() if name.startswith("_")
        }

        # Extra internal variables (not starting with underscore)
        additional_internal_vars = {"props", KEY_PREVIOUS_STATUS, KEY_STATUS, "usage"}

        # System context variables (if requested by the user, these variables are not excluded)
        system_context_vars = {"_user_id", "_session_id", "_max_answer_len"}

        # Set of variables that need to be excluded in the end
        if include_system_context_vars:
            # Include system context variables: exclude all variables starting with underscores and additional internal variables, except for system context variables
            internal_vars = (
                underscore_vars - system_context_vars
            ) | additional_internal_vars
        else:
            # Default behavior: exclude all underscore variables and additional internal variables
            internal_vars = underscore_vars | additional_internal_vars

        return {
            name: var.to_dict()
            for name, var in self.variable_pool.items()
            if name not in internal_vars
        }

    def get_all_variables_values(self):
        result = {}
        for name, var in self.variable_pool.items():
            val = var.value
            if isinstance(val, dict) and "value" in val and "source_type" in val:
                inner = val.get("value")
                if isinstance(inner, list):
                    result[name] = [
                        (
                            item.get("value")
                            if isinstance(item, dict) and "value" in item
                            else item
                        )
                        for item in inner
                    ]
                else:
                    result[name] = inner
            else:
                result[name] = val
        return result

    def keys(self):
        return self.variable_pool.keys()

    def set_var(self, name, value):
        if isinstance(value, Var):
            self.variable_pool[name] = value
        else:
            self.variable_pool[name] = Var(value)

    def set_var_output(
        self, name, value, source_type=SourceType.OTHER, skill_info=None
    ):
        # Create VarOutput with all parameters
        self.variable_pool[name] = VarOutput(name, value, source_type, skill_info)

    def delete_var(self, name):
        if name in self.variable_pool:
            del self.variable_pool[name]

    def sync_variables(self, variable_pool: "VariablePool"):
        for name, var in variable_pool.variable_pool.items():
            self.variable_pool[name] = var

    def clear(self):
        self.variable_pool.clear()

    def get_variable_type(self, variable_str):
        """Get variable value from string, including simple variables, array indices, and nested attributes
                :param variable_str: Variable string, for example '$var', '$arr[0]', '$obj.attr'
                :return: Variable value
        """
        variable_name = variable_str[1:]
        variable_name = convert_object_to_dict_access(variable_name)
        if "." not in variable_str and "[" not in variable_str:
            var = self.get_var(variable_name)
            if var is None:
                raise AttributeError(
                    f"Variable '{variable_name}' not found in variable pool"
                )
            value = var.value
        else:
            while "[0" in variable_name and "[0]" not in variable_name:
                variable_name = variable_name.replace("[0", "[")

            variable_first_name = (
                variable_name.split(".")[0].strip().split("[")[0].strip()
            )
            var = self.get_var(variable_first_name)
            if var is None:
                raise AttributeError(
                    f"Variable '{variable_first_name}' not found in variable pool"
                )
            variable_value = var.value
            variable_full_index = variable_name.replace(
                variable_first_name, str(variable_value), 1
            )
            try:
                value = eval(variable_full_index)
            except Exception:
                raise AttributeError(f"failed to eval '{variable_full_index}'")

        if (
            isinstance(value, list)
            and len(value) > 0
            and isinstance(value[0], dict)
            and "agent_name" in value[0]
        ):
            result = ""
            for item in value:
                if (
                    isinstance(item, dict)
                    and item.get("agent_name") == "main"
                    and "answer" in item
                ):
                    result += item["answer"]
            value = result
        return value

    @staticmethod
    def find_substring_positions(main_string, substring):
        positions = []
        start = 0

        while True:
            # Find the position of a substring
            pos = main_string.find(substring, start)
            if pos == -1:
                break
            positions.append(pos)
            # Update the starting position to avoid infinite loops
            start = pos + 1
        return positions

    def recognize_variable(self, dolphin_str):
        # Identify the positions of all variables in the string - Simple variables: `$variableName` - Array indices: `$variableName[index]` - Nested properties: `$variableName.key1.key2`
        """Identify the positions of all variables in a string
                :param dolphin_str: The string to be identified
                :return: A list of tuples containing variable names and their positions [('variable name', (start position, end position)), ...]
        """
        prompt_variable_pattern = re.compile(
            r"\$[a-zA-Z_][a-zA-Z0-9_]*(?:(?:\.[a-zA-Z_][a-zA-Z0-9_]*)|(?:\[\d+\]))*"
        )
        matches = prompt_variable_pattern.findall(dolphin_str)

        result = []

        # Sort by length, with the longest variable names first
        matches.sort(key=len, reverse=True)

        # Record processed positions to avoid overlap
        processed_positions = set()

        for match in matches:
            index_list = VariablePool.find_substring_positions(dolphin_str, match)

            for start_pos in index_list:
                end_pos = start_pos + len(match)

                # Check whether this position has already been processed
                if any(
                    start_pos >= existing_start and end_pos <= existing_end
                    for existing_start, existing_end in processed_positions
                ):
                    continue

                # Check whether a variable exists in the variable pool
                variable_base_name = match[1:].split(".")[0].split("[")[0].strip()
                if variable_base_name in self.variable_pool.keys():
                    result.append((match, (start_pos, end_pos)))
                    processed_positions.add((start_pos, end_pos))

        return result


def convert_object_to_dict_access(access_str):
    """
    Convert object attribute access to dictionary access format
    Example: "result.text[0].content[0].answer" -> "result['text'][0]['content'][0]['answer']"
    """
    parts = []
    current = ""
    i = 0
    while i < len(access_str):
        if access_str[i] == ".":
            if current:
                parts.append(current)
                current = ""
            i += 1
        elif access_str[i] == "[":
            if current:
                parts.append(current)
                current = ""
            # Find matching closing bracket
            bracket_count = 1
            j = i + 1
            while j < len(access_str) and bracket_count > 0:
                if access_str[j] == "[":
                    bracket_count += 1
                elif access_str[j] == "]":
                    bracket_count -= 1
                j += 1
            parts.append(access_str[i:j])
            i = j
        else:
            current += access_str[i]
            i += 1
    if current:
        parts.append(current)

    result = parts[0]
    for i, part in enumerate(parts[1:], 1):
        if part.startswith("["):
            result += part
        else:
            result += f"['{part}']"

    return result
