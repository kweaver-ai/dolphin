import re
from dataclasses import dataclass
from dolphin.core.utils.tools import extract_json


@dataclass
class ValidationResult:
    """Syntax Validation Result"""

    is_valid: bool
    error_message: str = ""
    line_number: int = 0

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(True)

    @classmethod
    def error(cls, message: str, line_number: int = 0) -> "ValidationResult":
        return cls(False, message, line_number)


class DPHSyntaxValidator:
    """DPH File Syntax Validator

    Responsibilities:
        1. Validate the overall syntax structure of DPH files
        2. Validate syntax rules for various code blocks
        3. Provide clear error messages
    """

    def __init__(self):
        self.tool_pattern = (
            r"@([\w\u4e00-\u9fff_-]+)\((.*?)\)\s*(->|>>)\s*([\w\u4e00-\u9fff]+)"
        )
        self.content_lines = []  # Store content lines for line number tracking

    def validate(self, content: str) -> ValidationResult:
        """Validate DPH file syntax

        Args:
            content: Content of the DPH file

        Returns:
            ValidationResult: Validation result
        """
        try:
            # Store content lines for line number tracking
            self.content_lines = content.splitlines()

            # 1. Basic Content Check
            result = self._validate_basic_content(content)
            if not result.is_valid:
                return result

            # 2. Try to parse as a code block
            result = self._validate_parsing(content)
            if not result.is_valid:
                return result

            # 3. Verify each code block
            result = self._validate_blocks(content)
            if not result.is_valid:
                return result

            return ValidationResult.success()

        except Exception as e:
            return ValidationResult.error(f"Unexpected validation error: {str(e)}", 0)

    def _get_line_number(self, target_text: str) -> int:
        """Get the line number of the specified text in the content"""
        try:
            if not target_text:
                return 0

            for i, line in enumerate(self.content_lines):
                if target_text.strip() in line:
                    return i + 1  # Return the line number in base 1.
            return 0
        except:
            return 0

    def _validate_basic_content(self, content: str) -> ValidationResult:
        """Verify basic content"""
        if not content or not content.strip():
            return ValidationResult.error("DPH file is empty", 1)

        # Remove comments and check
        cleaned_content = self._remove_comments(content)
        if not cleaned_content.strip():
            return ValidationResult.error("DPH file contains only comments", 1)

        return ValidationResult.success()

    def _validate_parsing(self, content: str) -> ValidationResult:
        """Verify whether correct parsing can be achieved"""
        try:
            parser = Parser(None)
            cleaned_content = self._remove_comments(content)
            blocks = Parser.parse(parser, cleaned_content)

            if not blocks:
                return ValidationResult.error("No valid blocks found in DPH file", 1)

            return ValidationResult.success()

        except Exception as e:
            return ValidationResult.error(f"Parse error: {str(e)}", 0)

    def _validate_blocks(self, content: str) -> ValidationResult:
        """Verify the syntax of each code block"""
        try:
            parser = Parser(None)
            cleaned_content = self._remove_comments(content)
            blocks = Parser.parse(parser, cleaned_content)

            for block_type, block_content in blocks:
                result = self._validate_single_block(block_type, block_content)
                if not result.is_valid:
                    return result

            return ValidationResult.success()

        except Exception as e:
            return ValidationResult.error(f"Block validation error: {str(e)}", 0)

    def _validate_single_block(
        self, block_type: str, block_content: str
    ) -> ValidationResult:
        """Verify a single code block"""
        block_content = block_content.strip()
        line_num = self._get_line_number(block_content)

        # Basic assignment syntax check
        if "->" not in block_content and ">>" not in block_content:
            return ValidationResult.error(
                f"Missing assignment operator (->/>>)  in {block_type} block", line_num
            )

        # Validate by type
        validators = {
            "tool": self._validate_tool_block,
            "assign": self._validate_assign_block,
            "prompt": self._validate_action_block,
            "judge": self._validate_action_block,
            "explore": self._validate_action_block,
        }

        validator = validators.get(block_type, self._validate_generic_block)
        return validator(block_type, block_content)

    def _validate_tool_block(self, block_type: str, content: str) -> ValidationResult:
        """Validation Tool Call Block"""
        if not re.search(self.tool_pattern, content):
            line_num = self._get_line_number(content)
            return ValidationResult.error(
                f"Invalid tool call format in {block_type} block: {content}", line_num
            )
        return ValidationResult.success()

    def _validate_assign_block(self, block_type: str, content: str) -> ValidationResult:
        """Verify assignment block"""
        line_num = self._get_line_number(content)

        if "->" in content:
            parts = content.split("->", 1)
            if len(parts) != 2 or not parts[1].strip():
                return ValidationResult.error(
                    f"Invalid assignment with '->': {content}", line_num
                )
        elif ">>" in content:
            parts = content.split(">>", 1)
            if len(parts) != 2 or not parts[1].strip():
                return ValidationResult.error(
                    f"Invalid assignment with '>>': {content}", line_num
                )

        return ValidationResult.success()

    def _validate_action_block(self, block_type: str, content: str) -> ValidationResult:
        """Verify action block (prompt, judge, explore)"""
        expected_prefix = f"/{block_type}/"
        if not content.startswith(expected_prefix):
            line_num = self._get_line_number(content)
            return ValidationResult.error(
                f"Missing '{expected_prefix}' prefix in {block_type} block", line_num
            )

        return ValidationResult.success()

    def _validate_generic_block(
        self, block_type: str, content: str
    ) -> ValidationResult:
        """Verify generic block"""
        # For blocks of unknown types, perform only basic checks.
        return ValidationResult.success()

    def _remove_comments(self, content: str) -> str:
        """Remove comment lines"""
        lines = content.splitlines()
        filtered_lines = [line for line in lines if not line.strip().startswith("#")]
        return "\n".join(filtered_lines)


label_dict = {
    "if": "/if/",
    "for": "/for/",
    "parallel": "/parallel/",
    "def": "/def/",
    "end": "/end/",
    "exit": "/exit/",
    "code": "/code/",
    "python": "/python/",
    "tool": r"@([\w\u4e00-\u9fff_-]+)\((.*?)\)\s*(->|>>)\s*([\w\u4e00-\u9fff]+)",
    "=": r"->\s*[a-zA-Z_]\w*",  # Match the variable name after "->"
    "append": r">>\s*[a-zA-Z_]\w*",
}  # Match the variable name after ">>"}


def split_by_pattern(content):
    # Regular expression matching for each block
    if not content:
        return None
    pattern1 = label_dict["="]
    pattern2 = label_dict["append"]
    pattern = r"{}|{}".format(pattern1, pattern2)
    matches = list(re.finditer(pattern, content))
    split_positions = [m.end() for m in matches]  # Get all matching end positions
    # Split string by ending position
    result = []
    prev_position = 0
    for pos in split_positions:
        result.append(content[prev_position:pos].lstrip("\n"))  # Get segmentation segments
        prev_position = pos  # Update start point
    content_end = content[prev_position:].lstrip("\n")
    # Add the last paragraph
    if len(content_end):
        result.append(content_end)
    # Output result
    return result


def find_gaps(length, intervals):
    # Sort Range
    intervals.sort(key=lambda x: (x[0], x[1]))

    # Merge Intervals
    merged_intervals = []
    for interval in intervals:
        if not merged_intervals or merged_intervals[-1][1] < interval[0]:
            merged_intervals.append(interval)
        else:
            merged_intervals[-1][1] = max(merged_intervals[-1][1], interval[1])

    # Find Gap
    gaps = []
    prev_end = 0
    for start, end in merged_intervals:
        if prev_end < start:
            gaps.append([prev_end, start])
        prev_end = max(prev_end, end)

    # Check the gap from the last interval to n
    if prev_end < length:
        gaps.append([prev_end, length])

    return gaps


class Parser:
    def __init__(self, context):
        self.parsed_data = None
        self.context = context

    def remove_comment(self, content):
        lines = content.splitlines()
        filtered_lines = [line for line in lines if not line.strip().startswith("#")]
        return "\n".join(filtered_lines)

    @staticmethod
    def parse(self, input_string):
        block_labels = {
            "if": label_dict["if"],
            "for": label_dict["for"],
            "def": label_dict["def"],
            "exit": label_dict["exit"],
            "code": label_dict["code"],
            "python": label_dict["python"],
            "end": label_dict["end"],
            "parallel": label_dict["parallel"],
        }
        label_indexes = []
        for key, value in block_labels.items():
            start_indexes = [
                match.start() for match in re.finditer(re.escape(value), input_string)
            ]
            for i in range(len(start_indexes)):
                label_indexes.append(
                    [key, start_indexes[i], start_indexes[i] + len(value)]
                )
        sorted_label_indexes = sorted(label_indexes, key=lambda x: x[1])
        label_stack = []
        blocks = []
        for i in range(len(sorted_label_indexes)):
            if sorted_label_indexes[i][0] == "end":
                label = label_stack[-1][0]
                start = label_stack[-1][1]
                end = sorted_label_indexes[i][2]
                label_stack.pop()
                if not label_stack:
                    blocks.append([label, start, end])
            else:
                label_stack.append(sorted_label_indexes[i])
        intervals = [[start, end] for label, start, end in blocks]
        gaps = find_gaps(len(input_string), intervals)
        for start, end in gaps:
            blocks.append(["prompt_or_tool", start, end])
        sorted_blocks = sorted(blocks, key=lambda x: x[1])
        blocks_final = []
        for label, start, end in sorted_blocks:
            s = input_string[start:end]
            if label != "prompt_or_tool":
                blocks_final.append([label, input_string[start:end]])
            else:
                s = input_string[start:end].strip()
                if s:
                    promptortool_blocks = split_by_pattern(s)
                    for promptortool_block in promptortool_blocks:
                        tool_pattern = label_dict["tool"]
                        if promptortool_block.startswith("@agent_init"):
                            blocks_final.append(["agent_init", promptortool_block])
                        elif promptortool_block.startswith("/judge/"):
                            blocks_final.append(["judge", promptortool_block])
                        elif promptortool_block.startswith("/explore/"):
                            blocks_final.append(["explore", promptortool_block])
                        elif promptortool_block.startswith("/prompt/"):
                            blocks_final.append(["prompt", promptortool_block])
                        elif bool(re.search(tool_pattern, promptortool_block)):
                            blocks_final.append(["tool", promptortool_block])
                        else:
                            blocks_final.append(["assign", promptortool_block])

        for block in blocks_final:
            if "->" not in block[1] and ">>" not in block[1]:
                raise ValueError("invalid format(no -> or >> in block)")
        return blocks_final

    @staticmethod
    def validate_syntax(content: str) -> tuple[bool, str]:
        """Validate DPH file syntax, delegated to a dedicated validator

        Args:
            content: Content of the DPH file

        Returns:
            tuple[bool, str]: (Is valid, Error message)
        """
        validator = DPHSyntaxValidator()
        result = validator.validate(content)
        return result.is_valid, result.error_message


def re_params_extract(params_content):
    params_content = params_content.strip()
    params = {}
    for param in params_content.split(","):
        param = param.strip()
        key, value = param.split(":", 1)
        params[key.strip()] = value.strip()
    return params


def params_extract_0(params_content):
    stack = 0
    params_content = params_content.strip()

    json_end = 0
    for index, char in enumerate(params_content):
        if char == "{":
            stack += 1
        elif char == "}":
            stack -= 1
        if stack == 0:
            json_end = index + 1
            break

    re_extracted_params = re_params_extract(params_content=params_content[:json_end])
    return re_extracted_params


def params_extract(params_content):
    """
    Extract and parse JSON parameters from tool call content.

    Args:
        params_content (str): Raw parameter content that may contain JSON

    Returns:
        dict or None: Parsed parameters dict, or None if parsing fails
    """
    try:
        return extract_json(params_content)
    except ValueError:
        return None
