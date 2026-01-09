import re


def escape(prompt: str):
    # to prevent 'format' exception in get_template_vars
    return prompt.replace("{", "{{").replace("}", "}}")


def unescape(prompt: str):
    return re.sub(r"\{{2,}", "{", re.sub(r"\}{2,}", "}", prompt))


def get_nested_value(var_name, data: dict):
    """Recursively parse nested variable names, supporting a mix of array indexing and attribute access
        For example: var[0].field[1].subfield, user['name'], header["x-user"]
    """
    if not var_name:
        return data

    # If the variable name starts with a square bracket, process the content within the square brackets directly.
    if var_name.startswith("["):
        bracket_end = var_name.find("]")
        if bracket_end == -1:
            raise ValueError(f"变量名 '{var_name}' 中的方括号不匹配")

        # Extract content within square brackets
        bracket_content = var_name[1:bracket_end]

        # Check if it's a string key (quoted)
        if (bracket_content.startswith("'") and bracket_content.endswith("'")) or (
            bracket_content.startswith('"') and bracket_content.endswith('"')
        ):
            # String key, remove quotes
            key_name = bracket_content[1:-1]

            # Get dictionary value
            if not isinstance(data, dict):
                raise ValueError("数据不是字典类型，无法使用键访问")

            if key_name not in data:
                raise ValueError(f"键 '{key_name}' 不存在于数据中")

            dict_value = data[key_name]
            remaining = var_name[bracket_end + 1 :]

            if not remaining:
                return dict_value
            elif remaining.startswith("."):
                # Continue recursive processing
                if not isinstance(dict_value, dict):
                    raise ValueError("字典值不是字典类型，无法使用点号访问")
                return get_nested_value(remaining[1:], dict_value)
            elif remaining.startswith("["):
                # Continue recursive processing
                return get_nested_value(remaining, dict_value)
            else:
                raise ValueError(f"变量名 '{var_name}' 格式错误，无法解析")

        else:
            # Numeric Indexing (Array Access)
            try:
                index = int(bracket_content)
            except ValueError:
                # Index is not a number
                raise ValueError(f"数组索引 '{bracket_content}' 不是有效的数字")

            # Get array elements
            if not isinstance(data, list):
                raise ValueError("数据不是列表类型，无法使用索引访问")

            if not (0 <= index < len(data)):
                raise ValueError(f"数组索引 {index} 超出范围 [0, {len(data)})")

            array_element = data[index]
            remaining = var_name[bracket_end + 1 :]

            if not remaining:
                return array_element
            elif remaining.startswith("."):
                # Continue recursive processing
                if not isinstance(array_element, dict):
                    raise ValueError("数组元素不是字典类型，无法使用点号访问")
                return get_nested_value(remaining[1:], array_element)
            elif remaining.startswith("["):
                # Continue recursive processing
                if not isinstance(array_element, list):
                    raise ValueError("数组元素不是列表类型，无法使用索引访问")
                return get_nested_value(remaining, array_element)
            else:
                raise ValueError(f"变量名 '{var_name}' 格式错误，无法解析")

    # Find the position of the first operator
    dot_pos = var_name.find(".")
    bracket_start = var_name.find("[")

    # If there are neither dots nor square brackets, return directly.
    if dot_pos == -1 and bracket_start == -1:
        if var_name not in data:
            raise ValueError(f"变量 '{var_name}' 不存在于数据中")
        return data.get(var_name)

    # Determine the first operator
    first_op_pos = -1
    if dot_pos == -1:
        first_op_pos = bracket_start
    elif bracket_start == -1:
        first_op_pos = dot_pos
    else:
        first_op_pos = min(dot_pos, bracket_start)

    # Extract the name of the key currently being accessed
    current_key = var_name[:first_op_pos]
    rest = var_name[first_op_pos:]

    # Get current value
    if current_key not in data:
        raise ValueError(f"变量 '{current_key}' 不存在于数据中")
    current_value = data.get(current_key)

    # If there are no remaining parts, return the current value
    if not rest:
        return current_value

    # Process the remaining part
    if rest.startswith("."):
        # Dot access, recursively process the remaining part
        if not isinstance(current_value, dict):
            raise ValueError(f"变量 '{current_key}' 不是字典类型，无法使用点号访问")
        return get_nested_value(rest[1:], current_value)
    elif rest.startswith("["):
        # Bracket Access
        bracket_end = rest.find("]")
        if bracket_end == -1:
            # No matching right parenthesis found
            raise ValueError(f"变量名 '{var_name}' 中的方括号不匹配")

        # Extract content within square brackets
        bracket_content = rest[1:bracket_end]

        # Check if it's a string key (quoted)
        if (bracket_content.startswith("'") and bracket_content.endswith("'")) or (
            bracket_content.startswith('"') and bracket_content.endswith('"')
        ):
            # String key, remove quotes
            key_name = bracket_content[1:-1]

            # Get dictionary value
            if not isinstance(current_value, dict):
                raise ValueError(f"变量 '{current_key}' 不是字典类型，无法使用键访问")

            if key_name not in current_value:
                raise ValueError(f"键 '{key_name}' 不存在于字典 '{current_key}' 中")

            dict_value = current_value[key_name]
            remaining = rest[bracket_end + 1 :]

            if not remaining:
                return dict_value
            elif remaining.startswith("."):
                # Continue recursive processing
                if not isinstance(dict_value, dict):
                    raise ValueError(
                        f"字典值 '{current_key}['{key_name}']' 不是字典类型，无法使用点号访问"
                    )
                return get_nested_value(remaining[1:], dict_value)
            elif remaining.startswith("["):
                # Continue recursive processing
                return get_nested_value(remaining, dict_value)

        else:
            # Numeric Indexing (Array Access)
            try:
                index = int(bracket_content)
            except ValueError:
                # Index is not a number
                raise ValueError(f"数组索引 '{bracket_content}' 不是有效的数字")

            # Get array elements
            if not isinstance(current_value, list):
                raise ValueError(f"变量 '{current_key}' 不是列表类型，无法使用索引访问")

            if not (0 <= index < len(current_value)):
                raise ValueError(f"数组索引 {index} 超出范围 [0, {len(current_value)})")

            array_element = current_value[index]
            remaining = rest[bracket_end + 1 :]

            if not remaining:
                return array_element
            elif remaining.startswith("."):
                # Continue recursive processing
                if not isinstance(array_element, dict):
                    raise ValueError(
                        f"数组元素 '{current_key}[{index}]' 不是字典类型，无法使用点号访问"
                    )
                return get_nested_value(remaining[1:], array_element)
            elif remaining.startswith("["):
                # Continue recursive processing
                if not isinstance(array_element, list):
                    raise ValueError(
                        f"数组元素 '{current_key}[{index}]' 不是列表类型，无法使用索引访问"
                    )
                return get_nested_value(remaining, array_element)
            else:
                raise ValueError(f"变量名 '{var_name}' 格式错误，无法解析")

    raise ValueError(f"变量名 '{var_name}' 格式错误，无法解析")
