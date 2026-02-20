from __future__ import annotations
import json
import re
import ast
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, AsyncGenerator

from dolphin.core import flags
from dolphin.core.common.constants import (
    KEY_STATUS,
    KEY_HISTORY,
    KEY_PENDING_TURN,
    PIN_MARKER,
)
from dolphin.core.context_engineer.config.settings import BuildInBucket
from dolphin.core.common.exceptions import SkillException
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.common.enums import (
    CategoryBlock,
    MessageRole,
    Messages,
    SkillInfo,
    SkillType,
    Status,
    StreamItem,
    TypeStage,
)
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import (
    console,
    console_block_start,
    console_agent_skill_enter,
    console_agent_skill_exit,
    console_skill_call,
    console_skill_response,
    get_logger,
)
from dolphin.core.trajectory.recorder import Recorder
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skill_matcher import SkillMatcher
from dolphin.core.runtime.runtime_instance import ProgressInstance
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.common.types import SourceType
from dolphin.core.common.output_format import (
    ObjectTypeOutputFormat,
    OutputFormat,
    OutputFormatFactory,
)
from dolphin.lib.skill_results.skillkit_hook import SkillkitHook
from dolphin.lib.skill_results.cache_backend import MemoryCacheBackend
from dolphin.lib.skill_results.strategy_registry import StrategyRegistry
from dolphin.lib.skill_results.strategies import (
    DefaultAppStrategy,
    DefaultLLMStrategy,
)


logger = get_logger(__name__)


@dataclass
class _ToolResponseIndex:
    """Index tool responses by tool_call_id for stable adjacent emission."""

    by_id: dict[str, list[Any]] = field(default_factory=dict)

    @classmethod
    def from_messages(
        cls, source_messages: Messages, matched_tool_call_ids: set[str]
    ) -> "_ToolResponseIndex":
        """Build index for tool responses that have a matched declaration."""
        index = cls()
        for msg in source_messages.get_messages():
            role = getattr(msg, "role", None)
            tool_call_id = getattr(msg, "tool_call_id", None)
            if (
                role == MessageRole.TOOL
                and tool_call_id
                and tool_call_id in matched_tool_call_ids
            ):
                index.by_id.setdefault(tool_call_id, []).append(msg)
        return index

    def pop_first(self, tool_call_id: str) -> Any | None:
        """Pop first response for given tool_call_id."""
        responses = self.by_id.get(tool_call_id) or []
        if not responses:
            return None
        return responses.pop(0)


class _HistoryPersistenceEngine:
    """Encapsulates history persistence and tool-chain adjacency rules."""

    @staticmethod
    def normalize_tool_calls(raw_tool_calls) -> list:
        """Normalize tool_calls into JSON-friendly list entries."""
        normalized = []
        for tool_call in raw_tool_calls or []:
            if isinstance(tool_call, dict):
                normalized.append(dict(tool_call))
            elif hasattr(tool_call, "to_dict") and callable(getattr(tool_call, "to_dict")):
                normalized.append(tool_call.to_dict())
            else:
                try:
                    normalized.append(dict(tool_call))
                except Exception:
                    normalized.append(tool_call)
        return normalized

    def extract_tool_call_ids(self, source_messages: Messages) -> tuple[set[str], set[str]]:
        """Extract assistant-declared and tool-responded tool_call IDs."""
        declared_ids: set[str] = set()
        responded_ids: set[str] = set()

        for msg in source_messages.get_messages():
            role = getattr(msg, "role", None)
            if role == MessageRole.ASSISTANT and getattr(msg, "has_tool_calls", None):
                if msg.has_tool_calls():
                    for tool_call in self.normalize_tool_calls(msg.tool_calls):
                        if isinstance(tool_call, dict):
                            tool_call_id = tool_call.get("id")
                            if tool_call_id:
                                declared_ids.add(tool_call_id)
            elif role == MessageRole.TOOL and getattr(msg, "tool_call_id", None):
                responded_ids.add(msg.tool_call_id)

        return declared_ids, responded_ids

    def filter_tool_calls_by_ids(self, raw_tool_calls, matched_ids: set[str]) -> list[dict]:
        """Keep tool calls with IDs that have both call and response."""
        filtered = []
        for tool_call in self.normalize_tool_calls(raw_tool_calls):
            if isinstance(tool_call, dict) and tool_call.get("id") in matched_ids:
                filtered.append(tool_call)
        return filtered

    @staticmethod
    def append_pinned_user_message(
        msg: Any,
        content: str,
        role: Any,
        persisted_turn_messages: list[dict],
        existing_contents: set[str],
    ) -> None:
        """Persist pinned user content once as assistant text."""
        if role != MessageRole.USER or PIN_MARKER not in content:
            return
        cleaned = content.replace(PIN_MARKER, "").strip()
        if not cleaned or cleaned in existing_contents:
            return

        persisted_turn_messages.append(
            {
                "role": MessageRole.ASSISTANT.value,
                "content": cleaned,
                "timestamp": getattr(msg, "timestamp", None)
                or datetime.now().isoformat(),
                "metadata": {"pinned": True, "source": "tool"},
            }
        )
        existing_contents.add(cleaned)

    @staticmethod
    def build_persisted_tool_response_message(
        response_msg: Any, tool_call_id: str
    ) -> dict[str, Any]:
        """Convert one tool response to persisted history dict."""
        response_content = getattr(response_msg, "content", "") or ""
        response_has_pin_marker = PIN_MARKER in response_content
        cleaned_response_content = (
            response_content.replace(PIN_MARKER, "").strip()
            if response_has_pin_marker
            else response_content
        )
        response_metadata = (
            {"pinned": True, "source": "tool"} if response_has_pin_marker else None
        )
        return {
            "role": MessageRole.TOOL.value,
            "content": cleaned_response_content,
            "tool_call_id": tool_call_id,
            "timestamp": getattr(response_msg, "timestamp", None)
            or datetime.now().isoformat(),
            **({"metadata": response_metadata} if response_metadata else {}),
        }

    def append_adjacent_tool_responses(
        self,
        matched_tool_calls: list[dict],
        tool_response_index: _ToolResponseIndex,
        persisted_turn_messages: list[dict],
    ) -> None:
        """Append matching tool responses right after assistant(tool_calls)."""
        for tool_call in matched_tool_calls:
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
                continue

            response_msg = tool_response_index.pop_first(tool_call_id)
            if not response_msg:
                continue

            persisted_turn_messages.append(
                self.build_persisted_tool_response_message(response_msg, tool_call_id)
            )

    def collect_persisted_messages_from_source(
        self,
        source_messages: Messages,
        persisted_turn_messages: list[dict],
        existing_contents: set[str],
        include_tool_chain: bool,
    ) -> None:
        """Collect persisted messages and enforce tool-call adjacency."""
        matched_tool_call_ids: set[str] = set()
        tool_response_index = _ToolResponseIndex()
        if include_tool_chain:
            declared_ids, responded_ids = self.extract_tool_call_ids(source_messages)
            matched_tool_call_ids = declared_ids & responded_ids
            tool_response_index = _ToolResponseIndex.from_messages(
                source_messages, matched_tool_call_ids
            )

        for msg in source_messages.get_messages():
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            self.append_pinned_user_message(
                msg=msg,
                content=content,
                role=role,
                persisted_turn_messages=persisted_turn_messages,
                existing_contents=existing_contents,
            )

            if not include_tool_chain:
                continue

            if role == MessageRole.ASSISTANT and msg.has_tool_calls():
                matched_tool_calls = self.filter_tool_calls_by_ids(
                    msg.tool_calls, matched_tool_call_ids
                )
                if not matched_tool_calls:
                    continue

                persisted_turn_messages.append(
                    {
                        "role": MessageRole.ASSISTANT.value,
                        "content": content,
                        "tool_calls": matched_tool_calls,
                        "timestamp": getattr(msg, "timestamp", None)
                        or datetime.now().isoformat(),
                    }
                )
                self.append_adjacent_tool_responses(
                    matched_tool_calls=matched_tool_calls,
                    tool_response_index=tool_response_index,
                    persisted_turn_messages=persisted_turn_messages,
                )
                continue

            if role == MessageRole.TOOL and msg.tool_call_id:
                continue


class BasicCodeBlock:
    """
    Base class for all Dolphin Language code blocks.

    This class provides core functionality for executing code blocks including:
    - Block lifecycle management (initialization, execution, cleanup)
    - Message and context management
    - LLM interaction (llm_chat, llm_chat_stream)
    - Variable replacement and output handling
    - Skill execution and tool calling
    - Trajectory recording and history management

    Key Methods for Subclasses:
    - execute(): Main entry point for block execution
    - llm_chat_stream(): Stream LLM responses with tool call support
    - _save_trajectory(): Save execution trajectory before bucket cleanup (used by explore blocks)
    - _update_history_and_cleanup(): Update history variable and save trajectory (used by explore blocks)

    Note: The _save_trajectory() and _update_history_and_cleanup() methods are typically called
    by explore-type blocks (ExploreBlock, ExploreBlockV2) to maintain conversation history and
    preserve tool call traces in the trajectory.
    """

    def __init__(self, context: Context):
        self.context = context
        self._history_persistence_engine = _HistoryPersistenceEngine()
        self.llm_client: Optional[LLMClient] = None
        self.category: Optional[CategoryBlock] = None
        self.params: Dict[str, Any] = {}
        self.content: Optional[str] = None
        self.name = self.__class__.__name__  # Add name based on class name
        self.assign_type: Optional[str] = None
        self.output_var: Optional[str] = None
        self.output_format: Optional[OutputFormat] = None
        self.recorder: Optional[Recorder] = None
        # tool_choice support (auto|none|required|provider-specific)
        self.tool_choice: Optional[str] = None
        # Whether to enable skill deduplication (used only in explore blocks)
        # Default is False to avoid incorrectly blocking legitimate repeated detection/polling tool calls.
        # Recent observations show that deduplication can prematurely stop valid polling scenarios
        # (e.g., repeatedly checking task status until completion).
        # Set to True explicitly via /explore/(enable_skill_deduplicator=true) when needed.
        self.enable_skill_deduplicator: bool = False
        self.skills = None
        self.system_prompt = ""

        # Get skillkit_hook from Context, use the default if not available
        if context and context.has_skillkit_hook():
            self.skillkit_hook = context.get_skillkit_hook()
        else:
            # Register with default strategy
            default_strategy_app = DefaultAppStrategy()
            default_strategy_llm = DefaultLLMStrategy()
            strategy_registry = StrategyRegistry()
            strategy_registry.register("default", default_strategy_app, category="app")
            strategy_registry.register("default", default_strategy_llm, category="llm")
            self.skillkit_hook = SkillkitHook(
                cache_backend=MemoryCacheBackend(),
                strategy_registry=strategy_registry,
            )
            
            # Set it back to Context so other components can use it
            # This ensures context retention strategies work correctly
            if context:
                context.set_skillkit_hook(self.skillkit_hook)

    @staticmethod
    def _normalize_bool_param(value: Any, default: bool) -> bool:
        """Normalize boolean-like params from DPH parsing.

        DPH params may be parsed as strings such as "true"/"false".
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return default

    def validate(self, content):
        """Verify the correctness of the content
        :param content: The content to be verified
        :return: Boolean value indicating whether the content is valid
        """
        pass

    async def execute(
        self, content, category: CategoryBlock, replace_variables=True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute code block asynchronously
        :param content: Block content
        :param category: Block category
        :param replace_variables: Whether to replace variables
        :yields: Response stream as a dictionary
        """
        # Set block in runtime graph first
        if (
            self.context
            and hasattr(self.context, "runtime_graph")
            and self.context.runtime_graph
        ):
            self.context.runtime_graph.set_block(self)

        # Prepare for trajectory tracking - each stage/block starts with clean state
        if self.context:
            # Reset context state for new block execution
            # This unified method handles:
            # 1. Trajectory stage baseline marking
            # 2. Message mirror reset
            # 3. Transient bucket cleanup (SCRATCHPAD, SYSTEM, QUERY)
            self.context.reset_for_block()

        self.parse_block_content(content, category, replace_variables)
        # Add an empty yield statement to make this method an asynchronous generator
        yield {}  # Return an empty dictionary as a placeholder, maintaining the generator property

    def get_cur_progress(self):
        assert self.recorder is not None, "recorder is None"
        return self.recorder.getProgress()

    def find_matching_paren(self, s: str, start: int) -> int:
        """Find the matching right parenthesis position, ignoring parentheses within strings.

        Handles special cases:
        - Single and double quotes
        - Triple quotes (''' and \""")
        - Escape sequences (only within quoted strings)
        - Word apostrophes (e.g., don't)

        Args:
            s: The input string to search
            start: The position of the opening parenthesis

        Returns:
            The position of the matching closing parenthesis, or -1 if not found
        """
        count = 1
        i = start + 1
        in_single = False
        in_double = False
        in_triple_single = False
        in_triple_double = False

        def is_word_apostrophe(idx: int) -> bool:
            if s[idx] != "'" or idx == 0 or idx + 1 >= len(s):
                return False
            return s[idx - 1].isalnum() and s[idx + 1].isalnum()

        while i < len(s):
            # Check for triple quotes first (before single/double quote handling)
            if s[i : i + 3] == "'''" and not in_double and not in_triple_double:
                in_triple_single = not in_triple_single
                i += 3
                continue
            if s[i : i + 3] == '"""' and not in_single and not in_triple_single:
                in_triple_double = not in_triple_double
                i += 3
                continue

            # Skip characters inside triple-quoted strings
            if in_triple_single or in_triple_double:
                i += 1
                continue

            c = s[i]

            # Handle escape sequences ONLY inside quoted strings
            # This prevents incorrect parsing when backslashes appear outside strings
            if c == "\\" and i + 1 < len(s) and (in_single or in_double):
                i += 2
                continue

            # Handle single quotes (excluding word apostrophes like "don't")
            if c == "'" and not in_double and not is_word_apostrophe(i):
                in_single = not in_single
                i += 1
                continue

            # Handle double quotes
            if c == '"' and not in_single:
                in_double = not in_double
                i += 1
                continue

            # Count parentheses only when outside all string types
            if not (in_single or in_double or in_triple_single or in_triple_double):
                if c == "(":
                    count += 1
                elif c == ")":
                    count -= 1
                    if count == 0:
                        return i

            i += 1

        return -1

    def split_parameters_smartly(self, params_str: str) -> List[str]:
        """
        Intelligently splits parameter strings, correctly handling brackets, braces, and quotes.

        This method replaces the repetitive parameter splitting logic found in various Block classes.

        Args:
            params_str: The parameter string, e.g., 'tools=[a,b], model="gpt-4", params={"key":"value"}'

        Returns:
            A list of split parameters, e.g., ['tools=[a,b]', 'model="gpt-4"', 'params={"key":"value"}']
        """
        items = []
        current_item = ""
        in_brackets = 0  # 方括号计数
        in_braces = 0  # 大括号计数
        in_quotes = False
        quote_char = None

        def is_word_apostrophe(idx: int) -> bool:
            if params_str[idx] != "'" or idx == 0 or idx + 1 >= len(params_str):
                return False
            return params_str[idx - 1].isalnum() and params_str[idx + 1].isalnum()

        for idx, char in enumerate(params_str):
            if char in ['"', "'"] and not (char == "'" and is_word_apostrophe(idx)):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
                current_item += char
            elif char == "[":
                in_brackets += 1
                current_item += char
            elif char == "]":
                in_brackets -= 1
                current_item += char
            elif char == "{":
                in_braces += 1
                current_item += char
            elif char == "}":
                in_braces -= 1
                current_item += char
            elif char == "," and not in_quotes and in_brackets == 0 and in_braces == 0:
                items.append(current_item.strip())
                current_item = ""
            else:
                current_item += char

        if current_item.strip():
            items.append(current_item.strip())

        return items

    def parse_tools_parameter(self, value: str) -> List[str]:
        """Unified method for parsing tool parameters, supporting both quoted and unquoted tool names.

        This method addresses inconsistencies in how different Block classes handle the 'tools' parameter,
        especially the "name 'execPython' is not defined" error caused by ExploreBlock using eval().

        Args:
            value: The tool parameter string, for example:
                - '["execBash", "execPython"]'  # With quotes
                - '[execBash, execPython]'      # Without quotes
                - 'execBash'                    # Single tool

        Returns:
            A list of parsed tool names.

        Raises:
            SyntaxError: When brackets in array format are unmatched.

        Examples:
            >>> parser = BasicCodeBlock()
            >>> parser.parse_tools_parameter('["execBash", "execPython"]')
            ['execBash', 'execPython']
            >>> parser.parse_tools_parameter('[execBash, execPython]')
            ['execBash', 'execPython']
        """
        if not value or not value.strip():
            return []

        value = value.strip()

        # 检查数组格式的语法错误
        if value.startswith("["):
            if not value.endswith("]"):
                raise SyntaxError(f"Unmatched brackets in tools parameter: {value}")

        # 处理数组格式: ["tool1", "tool2"] 或 [tool1, tool2]
        if value.startswith("[") and value.endswith("]"):
            tools_str = value[1:-1].strip()
            if not tools_str:
                return []

            # 检查引号是否匹配
            quote_count_single = tools_str.count("'")
            quote_count_double = tools_str.count('"')
            if quote_count_single % 2 != 0:
                raise SyntaxError(
                    f"Unmatched single quotes in tools parameter: {value}"
                )
            if quote_count_double % 2 != 0:
                raise SyntaxError(
                    f"Unmatched double quotes in tools parameter: {value}"
                )

            # 使用状态机解析工具列表，正确处理引号和逗号
            tools = []
            current_tool = ""
            in_quotes = False
            quote_char = None

            for char in tools_str:
                if char in ['"', "'"]:
                    if not in_quotes:
                        # 进入引号
                        in_quotes = True
                        quote_char = char
                    elif char == quote_char:
                        # 匹配到相同引号，结束
                        in_quotes = False
                        quote_char = None
                    else:
                        # 引号内的其他引号，当做普通字符
                        current_tool += char
                elif char == "," and not in_quotes:
                    # 不在引号内的逗号，分隔工具
                    cleaned_tool = current_tool.strip().strip("\"'")
                    if cleaned_tool:
                        tools.append(cleaned_tool)
                    current_tool = ""
                else:
                    # 其他字符直接添加
                    current_tool += char

            # 处理最后一个工具
            cleaned_tool = current_tool.strip().strip("\"'")
            if cleaned_tool:
                tools.append(cleaned_tool)

            return tools

        # 处理单个工具或逗号分隔的工具
        return [tool.strip().strip("\"'") for tool in value.split(",") if tool.strip()]

    def parse_parameter_value(self, key: str, value: str, expected_type: str = None) -> Any:
        """
        解析单个参数值，根据参数类型进行特殊处理

        统一了各个Block类中重复的参数值处理逻辑，现在也支持 ToolBlock 的复杂参数类型

        Args:
            key: 参数名
            value: 参数值字符串
            expected_type: 期望的参数类型（可选），如 "string", "integer", "number", "boolean" 等

        Returns:
            解析后的参数值
        """
        original_value = value.strip()

        # 标记是否是明确的字符串（带引号）
        is_explicit_string = False

        # 处理字符串值（带引号）
        if (original_value.startswith('"') and original_value.endswith('"')) or (
            original_value.startswith("'") and original_value.endswith("'")
        ):
            original_value = original_value[1:-1]  # 移除引号
            is_explicit_string = True  # 标记为明确的字符串类型

        # 处理变量引用（以 $ 开头）
        if original_value.startswith("$"):
            original_value = self.context.get_variable_type(original_value)

        # 优先处理特殊参数类型（避免被通用JSON解析干扰）
        if key == "history":
            if (
                not original_value
                or not isinstance(original_value, str)
                or (
                    original_value.lower() != "true"
                    and original_value.lower() != "false"
                    and original_value.lower() != "True"
                    and original_value.lower() != "False"
                )
            ):
                raise SyntaxError(
                    f"history must be a boolean value, but got {original_value}"
                )

            return original_value.lower() == "true" or original_value.lower() == "True"
        elif key == "tools":
            assert (
                isinstance(original_value, str) and original_value
            ), "tools must be a string"

            return self.parse_tools_parameter(original_value)
        elif key == "output":
            # 处理输出格式参数
            return {"type": "output_format", "value": original_value}
        elif key in ["model", "system_prompt", "ttc_mode", "tool_choice", "mode"]:
            return original_value

        if type(original_value) != str:
            return original_value

        # 如果是明确的字符串类型（带引号），直接返回字符串，不做类型转换
        if is_explicit_string:
            return original_value

        # 处理字典或JSON数组
        if original_value.startswith("{") or original_value.startswith("["):
            try:
                return ast.literal_eval(original_value)
            except:
                try:
                    return json.loads(original_value)
                except json.JSONDecodeError:
                    return original_value

        # 根据期望类型进行转换（如果提供了 expected_type）
        if expected_type:
            # 如果期望类型是 string，则保持为字符串，不做自动类型推断
            if expected_type in ["string", "str"]:
                return original_value
            # 如果期望类型是 integer/int，尝试转换为整数
            elif expected_type in ["integer", "int"] and original_value.isdigit():
                return int(original_value)
            # 如果期望类型是 number/float，尝试转换为浮点数
            elif expected_type in ["number", "float"]:
                try:
                    return float(original_value)
                except ValueError:
                    return original_value
            # 如果期望类型是 boolean/bool，尝试转换为布尔值
            elif expected_type in ["boolean", "bool"]:
                if original_value.lower() == "true":
                    return True
                elif original_value.lower() == "false":
                    return False
                return original_value
            # 其他类型按原值返回
            else:
                return original_value

        # 如果没有提供 expected_type，则使用旧的自动类型推断逻辑
        # 但要注意：这可能导致类型不匹配的问题
        # 处理数值类型（仅当不是明确的字符串时）
        if original_value.isdigit():
            return int(original_value)
        elif (
            original_value.replace(".", "", 1).isdigit()
            and original_value.count(".") == 1
        ):
            return float(original_value)

        # 处理布尔值
        if original_value.lower() == "true":
            return True
        elif original_value.lower() == "false":
            return False

        # 通用参数处理
        return original_value

    def parse_parameters_from_string(self, params_str: str) -> Dict[str, Any]:
        """
        从参数字符串解析出参数字典

        这个方法统一了所有Block类的参数解析逻辑，替代各自的实现

        Args:
            params_str: 括号内的参数字符串，如 'tools=[a,b], model="gpt-4"'

        Returns:
            解析后的参数字典
        """
        params = {}

        if not params_str.strip():
            return params

        # 处理JSON对象（先用占位符替换）
        json_placeholders = {}
        placeholder_count = 0

        def replace_json(match):
            nonlocal placeholder_count
            key = match.group(1).strip()
            json_str = match.group(2).strip()
            placeholder = f"__JSON_PLACEHOLDER_{placeholder_count}__"
            placeholder_count += 1
            json_placeholders[key] = json_str
            return f"{key}={placeholder}"

        json_pattern = re.compile(r"(\w+)\s*=\s*({.*?})")
        params_str = json_pattern.sub(replace_json, params_str)

        # 智能分割参数
        items = self.split_parameters_smartly(params_str)

        for item in items:
            if "=" not in item:
                continue

            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()

            # 处理JSON占位符
            if key in json_placeholders:
                try:
                    value = json.loads(json_placeholders[key])
                except:
                    value = json_placeholders[key]
            else:
                value = self.parse_parameter_value(key, value)

            params[key] = value

        return params

    def should_quote_variable_value(self, value: str) -> bool:
        """
        判断变量值是否需要用引号包围
        如果值包含逗号、括号等可能影响参数解析的字符，则需要引号保护

        Args:
            value: 变量值

        Returns:
            是否需要引号包围
        """
        if not isinstance(value, str):
            return False

        # 检查是否包含可能导致解析问题的字符
        special_chars = [",", "(", ")", "[", "]", "{", "}", "="]
        return any(char in value for char in special_chars)

    def parse_block_content(self, content: str, category=None, replace_variables=True):
        """
        统一的Block内容解析方法

        支持两种格式：
        1. 普通块格式: "/block_prefix/(params) main_content -> output_var"
        2. 工具块格式: "@tool_name(args) -> output_var"

        Args:
            content: 完整的Block内容
            category: Block类别，对于tool格式可以为None

        Raises:
            ValueError: 内容格式无效时
        """
        content = content.strip()
        self.category = category

        # 检测是否为工具格式（以 @ 开头）
        if content.startswith("@"):
            self._parse_tool_format(content)

            self.progress = ProgressInstance(context=self.context)

            # Ensure progress is registered to runtime_graph for tool format
            if (
                self.context
                and hasattr(self.context, "runtime_graph")
                and self.context.runtime_graph
            ):
                # Ensure block is set before setting progress
                if self.context.runtime_graph.cur_block is None:
                    self.context.runtime_graph.set_block(self)
                self.context.runtime_graph.set_progress(self.progress)

            self.recorder = Recorder(
                context=self.context,
                progress=self.progress,
                assign_type=self.assign_type,
                output_var=self.output_var,
            )
            return

        # 获取替换变量后的content
        if self.context and replace_variables:
            content = self._variable_replace(content)

        # 处理普通块格式
        if category is None:
            raise ValueError("category is required for non-tool format")

        # 移除block前缀
        prefix = "/" + category.value + "/"
        if content.startswith(prefix):
            content = content[len(prefix) :].strip()

        # 解析参数（如果有）
        params_dict = {}
        if content.startswith("("):
            params_end = self.find_matching_paren(content, 0)
            if params_end == -1:
                raise ValueError(f"Unmatched parentheses in: {content}")

            params_str = content[1:params_end]
            params_dict = self.parse_parameters_from_string(params_str)
            content = content[params_end + 1 :].strip()

        # 解析主内容和赋值
        # 注意顺序：先匹配 ">>" 再匹配 "->"，避免 "->>" 情况下优先匹配到 "->"
        pattern = re.compile(r"(.*?)\s*(>>|->)\s*([\w\u4e00-\u9fff]+)$", re.DOTALL)
        match = pattern.match(content)
        if not match:
            raise ValueError(f"Invalid block format: {content}")

        main_content = match.group(1).strip()
        assign_type = match.group(2)
        output_var = match.group(3)

        self.content = main_content
        self.params = params_dict
        self.assign_type = assign_type
        self.output_var = output_var

        if "history" not in self.params:
            self.params["history"] = False

        # system_prompt 变量解析
        self.system_prompt = self.params.get("system_prompt", "")
        if self.system_prompt:
            self.system_prompt = self._variable_replace(self.system_prompt)

        self.history = params_dict.get("history", "")
        self.model = params_dict.get("model", "")
        # tool_choice (optional)
        self.tool_choice = params_dict.get("tool_choice", None)

        self.skills = params_dict.get("skills", None)
        if self.skills is None:
            self.skills = params_dict.get("tools", None)

        self._validate_skills()

        self.ttc_mode = params_dict.get("ttc_mode", None)
        self.no_cache = self._normalize_bool_param(params_dict.get("no_cache", False), False)
        self.flags = params_dict.get("flags", "")
        # 是否启用技能调用去重（仅 explore 块会实际使用该参数）
        self.enable_skill_deduplicator = self._normalize_bool_param(
            params_dict.get("enable_skill_deduplicator", False), False
        )

        # 处理输出格式参数
        output_param = params_dict.get("output", None)
        if (
            output_param
            and isinstance(output_param, dict)
            and output_param.get("type") == "output_format"
        ):
            try:
                global_types = self.context.get_global_types()
                self.output_format = OutputFormatFactory.parseFromString(
                    output_param["value"], global_types
                )
            except ValueError as e:
                console(
                    f"Warning: Failed to parse output format '{output_param['value']}': {e}"
                )
                self.output_format = None
        else:
            self.output_format = None

        self.progress = ProgressInstance(context=self.context, flags=self.flags)

        # Check if runtime_graph exists before using it (for testing compatibility)
        if (
            self.context
            and hasattr(self.context, "runtime_graph")
            and self.context.runtime_graph
        ):
            # Ensure block is set before setting progress
            if self.context.runtime_graph.cur_block is None:
                self.context.runtime_graph.set_block(self)
            self.context.runtime_graph.set_progress(self.progress)

        self.recorder = Recorder(
            context=self.context,
            progress=self.progress,
            assign_type=self.assign_type,
            output_var=self.output_var,
        )

    def _validate_skills(self):
        """Validate that all requested skills/patterns match at least one available skill."""
        if self.skills is not None and self.context:
            current_skillkit = self.context.get_skillkit()
            if current_skillkit:
                available_skills = current_skillkit.getSkills()
                owner_names = SkillMatcher.get_owner_skillkits(available_skills)

                for pattern in self.skills:
                    if not any(
                        SkillMatcher.match_skill(
                            skill, pattern, owner_names=owner_names
                        )
                        for skill in available_skills
                    ):
                        # Build a user-friendly error message
                        available_skill_names = [
                            s.get_function_name() for s in available_skills
                        ]
                        error_lines = [
                            f"Skill pattern '{pattern}' did not match any available skills.",
                            "",
                            f"Available skills ({len(available_skill_names)}):",
                        ]
                        if available_skill_names:
                            # Show up to 20 skills to avoid overly long error messages
                            displayed_skills = available_skill_names[:20]
                            for s in displayed_skills:
                                error_lines.append(f"  - {s}")
                            if len(available_skill_names) > 20:
                                error_lines.append(
                                    f"  ... and {len(available_skill_names) - 20} more"
                                )
                        else:
                            error_lines.append("  (none)")

                        error_lines.extend(
                            [
                                "",
                                "Possible fixes:",
                                "  1. Check if the skill name/pattern is spelled correctly",
                                "  2. Ensure the skill is registered in your skillkit configuration",
                                "  3. Verify that the required skillkit module is loaded",
                                "  4. If using wildcards, ensure the pattern matches at least one skill (e.g. '*_resource*')",
                                "  5. If using skillkit namespace, use '<skillkit>.<pattern>' (e.g. 'resource_skillkit.*')",
                            ]
                        )

                        raise SkillException(
                            code=f"SKILL_NOT_FOUND: {pattern}",
                            message="\n".join(error_lines),
                        )

    def _parse_tool_format(self, content: str):
        """
        解析工具格式: @tool_name(args) -> output_var

        Args:
            content: 工具调用内容

        Raises:
            ValueError: 格式无效时
        """
        # 修改正则表达式以支持中文字符和Unicode字符
        tool_pattern = re.compile(
            r"@([\w\u4e00-\u9fff_-]+)\((.*?)\)\s*(->|>>)\s*([\w\u4e00-\u9fff]+)",
            re.DOTALL,
        )
        match = tool_pattern.match(content.strip())

        if not match:
            raise ValueError(f"Invalid tool call format[{content}]")

        tool_name = match.group(1)
        args_str = match.group(2).strip()
        assign_type = match.group(3)
        output_var = match.group(4)

        # 解析参数，传入 tool_name 以便获取 schema
        args_dict = self.parse_tool_parameters_from_string(args_str, tool_name)

        self.content = tool_name  # 对于工具块，content 存储工具名
        self.params = args_dict
        self.assign_type = assign_type
        self.output_var = output_var
        self.category = CategoryBlock.TOOL  # 工具块的 category 为 TOOL

    def parse_tool_parameters_from_string(self, params_str: str, tool_name: str = None) -> Dict[str, Any]:
        """
        专门用于解析 ToolBlock 参数的方法，支持复杂的参数格式

        支持位置参数和命名参数：
        - 位置参数：tool($arg1, $arg2)
        - 命名参数：tool(arg1=$value1, arg2=$value2)

        Args:
            params_str: 参数字符串
            tool_name: 工具名称（可选），用于获取工具 schema 以确定参数类型

        Returns:
            解析后的参数字典
        """
        params = {}

        if not params_str.strip():
            return params

        # 获取工具的 schema 信息（如果提供了 tool_name）
        tool_schema = None
        if tool_name and hasattr(self, 'context') and self.context:
            try:
                skillkit = self.get_skillkit()
                if skillkit:
                    # 获取工具的 schema
                    skill = skillkit.getSkill(tool_name)
                    if skill:
                        tool_schema = skill.get_openai_tool_schema()
            except Exception:
                logger.debug(
                    f"Tool schema fetch failed for tool={tool_name}; falling back to default parsing.",
                    exc_info=True,
                )

        # 提取参数类型映射
        param_types = {}
        if tool_schema and "function" in tool_schema:
            function_def = tool_schema["function"]
            if "parameters" in function_def and "properties" in function_def["parameters"]:
                properties = function_def["parameters"]["properties"]
                for param_name, param_info in properties.items():
                    param_types[param_name] = param_info.get("type", "string")

        # 处理多行参数，移除换行和多余空格
        params_str = re.sub(r"\s*\n\s*", " ", params_str)

        # 使用更智能的参数分割，而不是正则表达式
        param_items = self.split_parameters_smartly(params_str)

        positional_index = 0

        for item in param_items:
            item = item.strip()
            if not item:
                continue

            if "=" in item:
                # 命名参数
                key, value = item.split("=", 1)
                key = key.strip()
                value = value.strip()
                # 从 schema 中获取期望类型
                expected_type = param_types.get(key)
                params[key] = self.parse_parameter_value(key, value, expected_type)
            else:
                # 位置参数 - 使用索引作为键名
                value = item.strip()
                key = f"arg_{positional_index}"
                params[key] = self.parse_parameter_value(key, value)
                positional_index += 1

        return params

    async def llm_chat(
        self,
        lang_mode: str,
        with_skill: bool = False,
        early_stop_on_tool_call: bool = False,
    ):
        assert self.recorder, "recorder is None"
        messages = Messages()

        normalized_history = self.context.get_history_messages()

        if self.system_prompt:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                self.system_prompt,
            )
        if self.content:
            self.context.add_bucket(
                BuildInBucket.QUERY.value,
                self.content,
            )
        if self.history and normalized_history:
            # 使用专用 helper 确保 history bucket 与变量池中的历史快照一致
            self.context.set_history_bucket(normalized_history)

        messages = self.context.context_manager.to_dph_messages()

        # 如果有输出格式要求，则添加格式约束到 messages
        if self.output_format:
            self.output_format.addFormatConstraintToMessages(messages)

        # 准备 LLM 调用参数
        llm_params = {
            "messages": messages,
            "model": self.model,
            "ttc_mode": self.ttc_mode,
            "output_var": self.output_var,
            "lang_mode": lang_mode,
            "no_cache": self.no_cache,
        }

        if with_skill:
            llm_params["tools"] = self.get_skillkit().getSkillsSchema()
            if self.tool_choice:
                llm_params["tool_choice"] = self.tool_choice
        elif self.output_format and isinstance(
            self.output_format, ObjectTypeOutputFormat
        ):
            # 如果是 ObjectType 格式，添加 function_call tools
            try:
                tools = self.output_format.generateFunctionCallTools()
                llm_params["tools"] = tools
                if self.tool_choice:
                    llm_params["tool_choice"] = self.tool_choice
            except Exception as e:
                console(f"Warning: Failed to generate function call tools: {e}")

        # CLI rendering is handled by the CLI layer via output events.
        # Core should not import or manage terminal rendering components.
        on_chunk = None

        last_stream_item: Optional[StreamItem] = None
        assert self.content, "content is None"
        async for stream_item in self.llm_chat_stream(
            llm_params,
            self.recorder,
            self.content,
            early_stop_on_tool_call,
            on_stream_chunk=on_chunk,
        ):
            last_stream_item = stream_item
            yield stream_item.to_dict()

        assert last_stream_item, f"failed read from llm[{llm_params}]"

        # 如果有输出格式要求，解析最终结果并将解析后的对象存储到变量中
        final_answer = last_stream_item.answer
        if self.output_format:
            if final_answer:
                try:
                    parsed_result = self.output_format.parseResponse(final_answer)
                    console(
                        f"\n[Parsed Result]: {parsed_result}",
                        verbose=self.context.is_verbose(),
                    )

                    # 创建一个包含解析后对象的新结果项，用于存储到变量
                    # 保持原始的 answer 和 think，但主要输出是解析后的对象
                    last_stream_item.set_output_var_value(parsed_result)

                    self.recorder.update(
                        item=last_stream_item,
                        is_completed=True,
                        source_type=SourceType.LLM,
                    )
                    yield last_stream_item.to_dict()

                except Exception as e:
                    console(f"\nWarning: Failed to parse output format: {e}")
                    # 保持原始答案，不中断流程
                    self.recorder.update(
                        item=last_stream_item,
                        is_completed=True,
                        source_type=SourceType.LLM,
                    )
                    yield last_stream_item.to_dict()
            elif (
                isinstance(self.output_format, ObjectTypeOutputFormat)
                and last_stream_item.has_complete_tool_call()
            ):
                last_stream_item.set_output_var_value(last_stream_item.tool_args)
                self.recorder.update(
                    item=last_stream_item.tool_args,
                    is_completed=True,
                    source_type=SourceType.LLM,
                )
                yield last_stream_item.tool_args
        else:
            self.recorder.update(
                item=last_stream_item, is_completed=True, source_type=SourceType.LLM
            )
            yield last_stream_item.to_dict()

        console("\n", verbose=self.context.is_verbose())

    def block_start_log(self, block_name: str, content: Optional[str] = None):
        assert self.output_var
        console_block_start(
            block_name, self.output_var, content, verbose=self.context.verbose, is_cli=self.context.is_cli_mode()
        )

    def record_llm_response_to_trajectory(
        self, last_item: Optional[Dict[str, Any]]
    ) -> None:
        """
        Record LLM response to trajectory tracking
        Extract answer from the last item returned by llm_chat and add it to context

        Args:
            last_item: The last item yielded from llm_chat
        """
        if last_item and "answer" in last_item:
            answer_content = last_item["answer"]
            if isinstance(answer_content, dict) and "answer" in answer_content:
                answer_text = answer_content["answer"]
            elif isinstance(answer_content, str):
                answer_text = answer_content
            else:
                answer_text = str(answer_content)
            self.context.add_assistant_message(answer_text)

    def get_skillkit(self):
        """获取当前代码块可用的技能集（仅依赖 Context.get_skillkit 主流程逻辑）"""
        return self.context.get_skillkit(self.skills)

    async def skill_run(
        self,
        source_type: SourceType,
        skill_name: str,
        skill_params_json: Dict[str, Any] = {},
        props=None,
    ):
        from dolphin.core.utils.tools import ToolInterrupt
        if self.context.is_skillkit_empty():
            self.context.warn(f"skillkit is None, skill_name[{skill_name}]")
            return

        skill = self.context.get_skill(skill_name)
        if not skill:
            from dolphin.lib.skillkits.system_skillkit import SystemFunctions
            skill = SystemFunctions.getSkill(skill_name)

        if skill is None:
            async for result in self.yield_message(
                f"没有{skill_name}工具可以调用！", ""
            ):
                yield result
            return

        # Create initial SKILL stage to track skill execution start
        # Only create new stage if this is a new tool call (intervention=True)
        # For resumed tool calls (intervention=False), update the existing stage using saved_stage_id
        if props is None:
            props = {}
        
        is_resumed_call = not props.get('intervention', True)
        saved_stage_id = props.get('saved_stage_id')
        
        if not is_resumed_call:
            # First-time call: create new Stage
            assert self.recorder, "recorder is None"
            self.recorder.getProgress().add_stage(
                agent_name=skill_name,
                stage=TypeStage.SKILL,
                status=Status.PROCESSING,
                skill_info=SkillInfo.build(
                    skill_type=SkillType.TOOL,
                    skill_name=skill_name,
                    skill_args=skill_params_json,
                ),
                input_content=str(skill_params_json),
                interrupted=False,
            )
            
            # ✅ FIX: Save the newly created Stage ID to intervention_vars for potential interrupt
            # This must be done AFTER creating the stage, not before
            # Determine the correct intervention_vars key based on source_type
            progress = self.recorder.getProgress()
            if len(progress.stages) > 0:
                new_stage_id = progress.stages[-1].id
                
                # Map source_type to intervention_vars key
                # Priority: judge_block > tool_block (both use SourceType.SKILL) > explore_block
                var_key = None
                intervention_vars = None
                
                if source_type == SourceType.EXPLORE:
                    var_key = "intervention_explore_block_vars"
                    intervention_vars = self.context.get_var_value(var_key)
                elif source_type == SourceType.SKILL:
                    # Check judge block first (also uses SourceType.SKILL)
                    judge_vars = self.context.get_var_value("intervention_judge_block_vars")
                    if judge_vars is not None:
                        var_key = "intervention_judge_block_vars"
                        intervention_vars = judge_vars
                    else:
                        var_key = "intervention_tool_block_vars"
                        intervention_vars = self.context.get_var_value(var_key)
                
                # Update the intervention_vars with the correct Stage ID
                if intervention_vars is not None and var_key is not None:
                    intervention_vars["stage_id"] = new_stage_id
                    self.context.set_variable(var_key, intervention_vars)

            # notify app
            async for result in self.yield_message(answer="", think=""):
                yield result
        else:
            # *** FIX: Resumed call - Set _next_stage_id to use saved ID ***
            # Don't create stage here; let the normal flow handle it
            # This avoids creating extra stages and ensures consistency
            assert self.recorder, "recorder is None"
            
            if saved_stage_id:
                # Set _next_stage_id so the next add_stage() call will use this ID
                progress = self.recorder.getProgress()
                progress._next_stage_id = saved_stage_id
                logger.debug(f"Resumed tool call for {skill_name}, set _next_stage_id = {saved_stage_id}")
            else:
                logger.debug(f"Resumed tool call for {skill_name}, no saved_stage_id provided")
            
            # NOTE: Do NOT call yield_message() in resume branch!
            # The resumed tool execution will create the stage naturally through recorder.update()

        agent_as_skill = self.context.get_agent_skill(skill)
        if agent_as_skill is not None:
            cur_agent = self.context.get_cur_agent()
            if (
                cur_agent is not None
                and agent_as_skill.get_name() == cur_agent.get_name()
            ):
                error_message = f"禁止代理 {skill_name} 调用自身为技能。"
                self.context.error(error_message)
                if self.recorder is not None:
                    self.recorder.update(
                        item={"think": "", "answer": error_message},
                        source_type=source_type,
                        skill_name=skill_name,
                        skill_args=skill_params_json,
                        is_completed=True,
                        has_error=True,
                    )
                async for result in self.yield_message(answer=error_message, think=""):
                    yield result
                return
            self.context.delete_variable(KEY_STATUS)
            agent_as_skill.set_context(self.context)

        # 使用 arun 进行流式执行
        have_answer = False
        cur_agent = self.context.get_cur_agent()

        # props already initialized above, just update it
        props.update({"gvp": self.context})
        try:
            # Check for tool interrupt configuration (ToolInterrupt mechanism)
            # Default: all tool calls support interrupt if tool has interrupt_config
            # Skip interrupt check if this is a resumed tool call (intervention=False)
            if props.get('intervention', True):
                interrupt_config = getattr(skill, 'interrupt_config', None)
                
                if interrupt_config and interrupt_config.get('requires_confirmation'):
                    # Format confirmation message (support parameter interpolation)
                    message = interrupt_config.get('confirmation_message', 'Tool requires confirmation')
                    if message and skill_params_json:
                        try:
                            message = message.format(**skill_params_json)
                        except (KeyError, ValueError):
                            # If parameter interpolation fails, use original message
                            pass
                    
                    # Construct tool arguments list
                    tool_args = [
                        {"key": k, "value": v, "type": type(v).__name__}
                        for k, v in skill_params_json.items()
                    ]
                    
                    # Throw ToolInterrupt (checked before execution)
                    raise ToolInterrupt(
                        message=message,
                        tool_name=skill_name,
                        tool_args=tool_args,
                        tool_config=interrupt_config
                    )
            
            console_skill_call(
                skill_name, skill_params_json, verbose=self.context.verbose, skill=skill, is_cli=self.context.is_cli_mode()
            )
            if agent_as_skill is not None:
                console_agent_skill_enter(skill_name, verbose=self.context.verbose, is_cli=self.context.is_cli_mode())
            result = None
            async for result in Skillkit.arun(
                skill=skill,
                skill_params=skill_params_json if skill_params_json is not None else {},
                props=props,
            ):
                # Debug: log result type and keys
                self.context.debug(
                    f"[BasicCodeBlock.skill_run] Tool {skill_name} returned result type: {type(result)}"
                )
                if isinstance(result, dict):
                    if "answer" in result:
                        self.context.debug(
                            f"[BasicCodeBlock.skill_run] answer : {result['answer']}"
                        )
                
                # Check if this is a dynamic tool response and load tools immediately
                if (
                    isinstance(result, dict)
                    and "answer" in result
                    and isinstance(result["answer"], dict)
                    and "_dynamic_tools" in result["answer"]
                ):
                    # Load dynamic tools into current skillkit
                    self.context.info(
                        f"[BasicCodeBlock] Detected dynamic tool response, loading tools..."
                    )
                    loaded_count = self._load_dynamic_tools(result["answer"])
                    self.context.info(
                        f"[BasicCodeBlock] Loaded {loaded_count} dynamic tools"
                    )
                else:
                    self.context.debug(
                        f"[BasicCodeBlock.skill_run] Not a dynamic tool response (result={'dict' if isinstance(result, dict) else type(result)}, has_answer={'answer' in result if isinstance(result, dict) else False})"
                    )

                # After tool execution, store the result in cache
                try:
                    ref = self.skillkit_hook.on_tool_after_execute(skill_name, result)
                    # Remove problematic code
                except Exception as e:
                    import traceback

                    raise e

                # Save the Reference object as raw output
                raw_output = ref
                # Process the response data to return to frontend
                try:
                    result = self.skillkit_hook.on_before_reply_app(
                        reference_id=ref.reference_id, skill=skill
                    )
                except Exception as e:
                    raise e

                self.recorder.update(
                    item=result,
                    raw_output=raw_output,
                    source_type=SourceType.SKILL,
                    skill_name=skill_name,
                    skill_args=skill_params_json,
                )

                have_answer = True
                yield result

            # Restore the original current agent after skill execution
            if agent_as_skill is not None:
                self.context.set_cur_agent(cur_agent)

            # *** FIX: Update stage status to COMPLETED ***
            # This updates the stage status and triggers set_variable() to update _progress in context
            self.recorder.update(
                item=result,
                source_type=SourceType.SKILL,
                skill_name=skill_name,
                skill_args=skill_params_json,
                is_completed=True,
            )
            
            # *** FIX: Yield completion update in a format that explore_block_v2 recognizes ***
            # Use a nested structure that matches the check in explore_block_v2.py line 422-427
            # This prevents explore_block_v2 from calling recorder.update() again
            if self.context:
                progress_var = self.context.get_var_value("_progress")
                completion_data = {
                    "answer": {
                        "answer": result.get("output") if isinstance(result, dict) else str(result),
                        "think": "",
                    },
                    "_status": "running",
                    "_progress": progress_var if progress_var else []
                }
                yield completion_data
            else:
                yield result
            
            if agent_as_skill is not None:
                console_agent_skill_exit(skill_name, verbose=self.context.verbose, is_cli=self.context.is_cli_mode())
        except ToolInterrupt as e:
            # Restore original agent even in case of interruption
            if agent_as_skill is not None:
                self.context.set_cur_agent(cur_agent)

            raise e
        except Exception as e:
            # Restore original agent even in case of exception
            if agent_as_skill is not None:
                self.context.set_cur_agent(cur_agent)

            self.context.error(
                f"error in skill_run[{skill_name}], error type: {type(e)}, error info: {str(e)}"
            )
            error_message = f"调用{skill_name}工具时发生错误。错误信息: {str(e)}"
            self.recorder.update(
                item={"think": "", "answer": error_message},
                source_type=source_type,
                is_completed=True,
                has_error=True,
            )
            async for result in self.yield_message(answer=error_message, think=""):
                yield result

        answer = self.recorder.get_answer()

        # Optimize console output:
        # If this skill is an Agent (agent_as_skill is not None), we SKIP printing the response.
        # Reason: Sub-agents stream their output to the console during execution (Live Markdown).
        # Printing the final result again is redundant duplication.
        if agent_as_skill is None:
            # Ensure we pass the full answer to the UI so JSON parsing succeeds.
            # The UI module handles visual truncation of large structures intelligently.
            console_skill_response(
                skill_name=skill_name,
                response=answer,
                max_length=1024,
                verbose=self.context.verbose,
                skill=skill,
                params=skill_params_json,
                is_cli=self.context.is_cli_mode(),
            )
        self.context.debug(
            f"call_skill function_name[{skill_name}] "
            f"tool_message[{str(skill_params_json).strip()}] "
            f"resp[{str(self.recorder.get_progress_answers())[: self.context.get_max_answer_len()]}]"
        )

        if not have_answer:
            self.recorder.update(
                item={
                    "think": "",
                    "answer": f"调用{skill_name}工具时未正确返回结果。",
                },
                source_type=source_type,
                is_completed=True,
                has_error=True,
            )

    async def llm_chat_stream(
        self,
        llm_params: dict,
        recorder: Recorder | None,
        content: str,
        early_stop_on_tool_call: bool = False,
        on_stream_chunk=None,
        session_counter: int = 0,
    ):
        """
        LLM chat stream with optional early stopping on tool call detection.

        Args:
            llm_params: LLM parameters
            recorder: Recorder instance
            content: Input content
            early_stop_on_tool_call: If True, stop streaming when a complete tool call is detected
            on_stream_chunk: Optional callback for CLI rendering.
                Signature: (chunk_text: str, full_text: str, is_final: bool) -> None
                If None, uses default console() output.
            session_counter: Session-level tool call batch counter for generating stable
                fallback tool_call_ids. Passed to StreamItem.parse_from_chunk().
        """
        # Store the model name in context for consistency across multiple rounds
        if "model" in llm_params and llm_params["model"]:
            self.context.set_last_model_name(llm_params["model"])

        (
            recorder.getProgress().add_stage(
                agent_name="main",
                stage=TypeStage.LLM,
                status=Status.PROCESSING,
                input_content=content,
                input_messages=llm_params["messages"],
            )
            if recorder
            else None
        )

        assert self.llm_client, "llm_client is None"

        tool_call_detected = False
        complete_tool_call = None

        stream_item = None
        cur_len = 0
        emitted_output_events = False
        last_full_text = ""

        try:
            async for chunk in self.llm_client.mf_chat_stream(**llm_params):
                # Checkpoint: Check user interrupt during LLM streaming
                self.context.check_user_interrupt()

                stream_item = StreamItem()
                stream_item.parse_from_chunk(chunk, session_counter=session_counter)

                # Rendering: use callback if provided, otherwise default console output
                chunk_text = stream_item.answer[cur_len:]
                if on_stream_chunk:
                    on_stream_chunk(
                        chunk_text=chunk_text,
                        full_text=stream_item.answer,
                        is_final=False,
                    )
                else:
                    # CLI path: emit output events for the CLI layer to render.
                    # Non-CLI path: preserve legacy behavior (print to stdout).
                    if self.context.is_cli_mode():
                        self.context.write_output(
                            "llm_stream",
                            {
                                "chunk_text": chunk_text,
                                "full_text": stream_item.answer,
                                "is_final": False,
                            },
                        )
                        emitted_output_events = True
                        last_full_text = stream_item.answer
                    else:
                        console(chunk_text, verbose=self.context.is_verbose(), end="")

                cur_len = len(stream_item.answer)

                if recorder:
                    recorder.update(item=stream_item, raw_output=stream_item.answer)

                # Update tool call detection flags
                if stream_item.has_tool_call():
                    tool_call_detected = True
                    if stream_item.has_complete_tool_call():
                        complete_tool_call = stream_item.get_tool_call()

                yield stream_item

                # If a complete tool call is detected and early-stop is enabled, stop streaming.
                if early_stop_on_tool_call and tool_call_detected and complete_tool_call:
                    break
        finally:
            if emitted_output_events:
                self.context.write_output(
                    "llm_stream",
                    {
                        "chunk_text": "",
                        "full_text": last_full_text,
                        "is_final": True,
                    },
                )

    async def yield_None(self, function_name):
        yield {
            "answer": {"answer": f"没有{function_name}工具可以调用！", "think": ""},
            "block_answer": "",
        }

    async def yield_message(self, answer, think):
        yield {"answer": {"answer": answer, "think": think}, "block_answer": ""}

    def update_recorder(
        self,
        item,
        source_type: SourceType,
        skill_name: str,
        skill_args: Dict[str, Any],
        is_completed: bool = False,
    ):
        assert self.recorder, "recorder is None"
        if source_type == SourceType.EXPLORE:
            if isinstance(item, dict) and "answer" in item:
                if isinstance(item["answer"], dict) and "answer" in item["answer"]:
                    self.recorder.update(
                        item={
                            "answer": item.get("answer", "").get("answer", ""),
                            "think": item.get("answer", "").get("think", ""),
                            "block_answer": item.get("block_answer", ""),
                        },
                        source_type=SourceType.EXPLORE,
                    )
                else:
                    self.recorder.update(
                        item={
                            "answer": item.get("answer", ""),
                            "think": item.get("think", ""),
                            "block_answer": item.get("block_answer", ""),
                        },
                        source_type=SourceType.EXPLORE,
                    )
            else:
                self.recorder.update(
                    item={"answer": item, "block_answer": item},
                    source_type=SourceType.EXPLORE,
                )
        else:
            if source_type == SourceType.SKILL:
                self.recorder.update(
                    item=item,
                    source_type=source_type,
                    skill_name=skill_name,
                    skill_args=skill_args,
                    is_completed=is_completed,
                )

    def _variable_replace(self, content: str) -> str:
        variable_index_list = self.context.recognize_variable(content)

        if variable_index_list:
            # Sort by position in reverse order to avoid offset issues during replacement
            variable_index_list.sort(key=lambda x: x[1][0], reverse=True)

            for variable_name, (start, end) in variable_index_list:
                variable_value = self.context.get_variable_type(variable_name)
                variable_value_str = str(variable_value)

                # If the variable value contains special characters, wrap with quotes
                if self.should_quote_variable_value(variable_value_str):
                    # Skip if value is already quoted
                    if not (
                        (
                            variable_value_str.startswith('"')
                            and variable_value_str.endswith('"')
                        )
                        or (
                            variable_value_str.startswith("'")
                            and variable_value_str.endswith("'")
                        )
                    ):
                        # Escape backslashes and double quotes within the value
                        # to prevent parsing errors when the value contains these characters
                        escaped_value = variable_value_str.replace('\\', '\\\\').replace('"', '\\"')
                        variable_value_str = f'"{escaped_value}"'

                content = content.replace(variable_name, variable_value_str)
        return content

    def _save_trajectory(self, stage_name: str = "explore"):
        """
        Save execution trajectory to file, preserving tool calls and conversation context.

        This method should be called BEFORE bucket cleanup (removing SCRATCHPAD/QUERY)
        to ensure the complete conversation context including tool calls is preserved
        in the trajectory file.

        The method temporarily removes history buckets to avoid duplicating full history
        in each stage, keeping only the current round's conversation context.

        Called by: ExploreBlock and ExploreBlockV2 in their _update_history_and_cleanup() method

        Args:
            stage_name: The name of the stage to save (default: "explore")
                       Used as stage identifier in trajectory file
        """
        if not hasattr(self.context, "trajectory") or self.context.trajectory is None:
            return

        try:
            # At this point, context_manager still contains:
            # - SYSTEM bucket (system prompt)
            # - QUERY bucket (user question)
            # - SCRATCHPAD bucket (tool calls + tool results + assistant messages)
            skillkit = self.get_skillkit()
            tools_schema = None

            # Get tools schema based on skillkit type
            if skillkit and not skillkit.isEmpty():
                if hasattr(skillkit, "getSkillsSchema"):
                    tools_schema = skillkit.getSkillsSchema()
                elif hasattr(skillkit, "getSchemas"):
                    tools_schema = skillkit.getSchemas()

            # Use current recorded stages count + 1 as stage index
            stage_index = len(self.context.trajectory.stages) + 1

            self.context.trajectory.finalize_stage(
                stage_name=stage_name,
                stage_index=stage_index,
                context_manager=self.context.context_manager,
                tools=tools_schema,
                user_id=self.context.user_id or "",
                model=getattr(self, "model", None),
            )

            logger.debug(f"Trajectory saved for '{stage_name}' before cleanup")
        except Exception as e:
            logger.warning(
                f"Failed to save trajectory in _save_trajectory_before_cleanup: {e}"
            )

    def _collect_persisted_messages_from_source(
        self,
        source_messages: Messages,
        persisted_turn_messages: list[dict],
        existing_contents: set[str],
        include_tool_chain: bool,
    ) -> None:
        """Delegate history persistence to a dedicated engine."""
        history_engine = getattr(self, "_history_persistence_engine", None)
        if history_engine is None:
            history_engine = _HistoryPersistenceEngine()
            self._history_persistence_engine = history_engine

        history_engine.collect_persisted_messages_from_source(
            source_messages=source_messages,
            persisted_turn_messages=persisted_turn_messages,
            existing_contents=existing_contents,
            include_tool_chain=include_tool_chain,
        )

    def _extract_persisted_turn_messages(self, history_list: list[dict]) -> list[dict]:
        """Extract persisted messages for current turn."""
        persisted_turn_messages: list[dict] = []
        cm = self.context.context_manager

        existing_contents = {
            item.get("content")
            for item in history_list
            if isinstance(item, dict) and isinstance(item.get("content"), str)
        }

        scratch_bucket = (
            cm.state.buckets.get(BuildInBucket.SCRATCHPAD.value)
            if cm and hasattr(cm, "state")
            else None
        )
        scratch_content = (
            getattr(scratch_bucket, "content", None) if scratch_bucket else None
        )

        if isinstance(scratch_content, Messages):
            self._collect_persisted_messages_from_source(
                source_messages=scratch_content,
                persisted_turn_messages=persisted_turn_messages,
                existing_contents=existing_contents,
                include_tool_chain=True,
            )
        elif cm:
            merged = cm.to_dph_messages()
            if isinstance(merged, Messages):
                self._collect_persisted_messages_from_source(
                    source_messages=merged,
                    persisted_turn_messages=persisted_turn_messages,
                    existing_contents=existing_contents,
                    include_tool_chain=False,
                )

        return persisted_turn_messages

    def _resolve_turn_user_content(self):
        """Resolve current turn user content from block content or QUERY bucket."""
        user_content = self.content
        if not user_content and self.context.context_manager:
            bucket = self.context.context_manager.state.buckets.get(
                BuildInBucket.QUERY.value
            )
            if bucket:
                user_content = bucket._get_content_text()
        return user_content

    def _get_history_list(self) -> list[dict]:
        """Get history as a mutable list, normalizing legacy return types."""
        history_raw = self.context.get_history_messages(normalize=False)
        if history_raw is None:
            return []
        if isinstance(history_raw, Messages):
            return history_raw.get_messages_as_dict()
        if isinstance(history_raw, list):
            return history_raw

        logger.warning(
            f"Unexpected history type: {type(history_raw)}, initializing as empty list"
        )
        return []

    def _get_pending_turn(self) -> Optional[Dict[str, Any]]:
        """Get pending turn metadata if present and valid."""
        pending_turn = self.context.get_var_value(KEY_PENDING_TURN)
        return pending_turn if isinstance(pending_turn, dict) else None

    def _clear_pending_turn(self) -> None:
        """Clear pending turn metadata from context."""
        if KEY_PENDING_TURN in self.context.get_all_variables():
            self.context.delete_variable(KEY_PENDING_TURN)

    @staticmethod
    def _build_turn_fingerprint(user_content: Any) -> str:
        """Build a stable fingerprint for idempotent pending-turn creation."""
        if isinstance(user_content, str):
            normalized = user_content.strip()
        else:
            try:
                normalized = json.dumps(user_content, ensure_ascii=False, sort_keys=True)
            except Exception:
                normalized = str(user_content)
        return f"user:{normalized}"

    def _mark_pending_turn(self, preserve_context: bool = False) -> None:
        """Mark the current turn as pending so interrupt paths can be resumed safely.

        Args:
            preserve_context: When True (resume from interrupt), keep the existing
                pending turn so the original interrupted question is persisted in
                history.  When False (new turn), overwrite any stale pending turn.
        """
        user_content = self._resolve_turn_user_content()
        if not user_content:
            return

        fingerprint = self._build_turn_fingerprint(user_content)
        pending_turn = self._get_pending_turn()
        if pending_turn:
            if pending_turn.get("fingerprint") == fingerprint:
                return  # idempotent — same turn, nothing to do
            if preserve_context:
                # Resuming from interrupt: the existing pending turn carries
                # the original user question that should eventually be committed
                # to history.  Keep it as-is.
                logger.debug("Pending turn fingerprint mismatch during resume; keeping existing pending metadata.")
                return
            # New turn with different content: overwrite the stale entry so
            # _update_history_and_cleanup pairs the correct question with its answer.
            logger.debug("Pending turn fingerprint mismatch; overwriting stale pending metadata.")

        self.context.set_variable(
            KEY_PENDING_TURN,
            {
                "turn_id": datetime.now().isoformat(),
                "user_content": user_content,
                "fingerprint": fingerprint,
            },
        )
        logger.debug("Marked pending turn for current explore round.")

    def _update_history_and_cleanup(self):
        """
        Update history variable with current conversation turn and save trajectory.

        This method performs critical post-execution cleanup for explore-type blocks:
        1. Extracts user question from current turn (from self.content or QUERY bucket)
        2. Extracts assistant answer from recorder
        3. Appends both to the 'history' variable as a new conversation turn
        4. Saves trajectory to file (BEFORE bucket cleanup to preserve tool calls)

        Note: Bucket cleanup (SCRATCHPAD, QUERY, SYSTEM) is NOT done here.
        It's handled by Context.reset_for_block() at the START of next block execution.
        This ensures trajectory can capture complete tool call information.

        Called by: ExploreBlock and ExploreBlockV2 after their main execution completes

        Side effects:
        - Updates 'history' variable in context
        - Writes trajectory to file via _save_trajectory()
        """
        if not self.recorder:
            return

        logger.debug("Executing _update_history_and_cleanup...")

        user_content = self._resolve_turn_user_content()
        answer_content = self.recorder.get_answer()
        pending_turn = self._get_pending_turn()
        pending_user_content = pending_turn.get("user_content") if pending_turn else None
        history_user_content = pending_user_content or user_content

        logger.debug(
            f"Cleanup: user_content found: {bool(user_content)}, answer_content found: {bool(answer_content)}"
        )

        # Record complete turn only when both user content and answer are present.
        if history_user_content and answer_content:
            history_list = self._get_history_list()
            try:
                persisted_turn_messages = self._extract_persisted_turn_messages(
                    history_list
                )
            except Exception as e:
                logger.warning(f"Failed to extract scratchpad messages: {e}")
                persisted_turn_messages = []

            # Add User Message with timestamp
            history_list.append(
                {
                    "role": MessageRole.USER.value,
                    "content": history_user_content,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Append persisted turn messages in their original temporal order.
            history_list.extend(persisted_turn_messages)

            # Add Assistant Message with timestamp
            history_list.append(
                {
                    "role": MessageRole.ASSISTANT.value,
                    "content": answer_content,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            self.context.set_variable(KEY_HISTORY, history_list)
            self._clear_pending_turn()
            logger.debug("Cleanup: History variable updated.")
        elif pending_turn and not answer_content:
            logger.debug("Cleanup: keeping pending turn because answer is missing.")

        # Save trajectory BEFORE cleaning up buckets (so tool calls are preserved)
        self._save_trajectory(stage_name="explore")

    def _load_dynamic_tools(self, result) -> int:
        """
        Load dynamic tools into current skillkit (unified implementation for all explore modes)

        Args:
            result: Response result containing _dynamic_tools (dict or string)

        Returns:
            int: Number of successfully loaded tools
        """
        from dolphin.core.skill.skillset import Skillset
        import json

        # Parse result if it's a string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except:
                self.context.error(f"Failed to parse dynamic tool response: {result}")
                return 0

        if not isinstance(result, dict):
            self.context.error(f"Invalid dynamic tool response type: {type(result)}")
            return 0
        _dynamic_tools = result.get("_dynamic_tools", [])
        provider_name = result.get("provider", "unknown")
        headers = result.get("headers", {})  # 提取 headers

        if not _dynamic_tools:
            self.context.debug("No dynamic tools to load")
            return 0

        if headers:
            self.context.info(
                f"Loading {len(_dynamic_tools)} dynamic tools from {provider_name} with headers: {headers}..."
            )
        else:
            self.context.info(
                f"Loading {len(_dynamic_tools)} dynamic tools from {provider_name}..."
            )

        # Get current skillkit
        current_skillkit = self.context.skillkit

        # If current skillkit is not a Skillset, create a new Skillset and merge
        if not isinstance(current_skillkit, Skillset):
            self.context.debug(
                f"Current skillkit is {type(current_skillkit).__name__}, converting to Skillset"
            )
            new_skillset = Skillset()
            # Add existing tools
            for skill in current_skillkit.getSkills():
                new_skillset.addSkill(skill)
            current_skillkit = new_skillset
            self.context.set_skills(current_skillkit)

        # Add new tools
        loaded_count = 0
        for i, tool_def in enumerate(_dynamic_tools):
            try:
                tool_name = tool_def.get("name", "unknown")
                tool_instance = None

                # 判断工具类型并创建实例
                if "tool_instance" in tool_def:
                    # 类型 1: 预实例化工具（本地函数包装或其他）
                    tool_instance = tool_def["tool_instance"]
                    self.context.debug(f"Loading pre-instantiated tool: {tool_name}")

                elif "api_call_strategy" in tool_def:
                    # 类型 2: API 工具 - 自动创建 DynamicAPISkillFunction
                    from dolphin.core.skill.skill_function import (
                        DynamicAPISkillFunction,
                    )

                    api_url = tool_def.get("api_url")
                    description = tool_def.get("description", "")
                    parameters = tool_def.get("parameters", {})
                    original_schema = tool_def.get("original_schema", {})
                    fixed_params = tool_def.get("fixed_params", {})
                    api_call_strategy = tool_def.get("api_call_strategy")

                    self.context.debug(
                        f"Creating DynamicAPISkillFunction for: {tool_name}, "
                        f"api_url={api_url}, api_call_strategy={api_call_strategy}, "
                        f"fixed_params={fixed_params}, headers={headers}"
                    )
                    
                    # Bind tool execution policy into the app strategy slot so the tool implementation can branch if needed.
                    if api_call_strategy:
                        result_process_strategies = [
                            {"strategy": str(api_call_strategy), "category": "app"},
                            {"strategy": "default", "category": "llm"},
                        ]
                    else:
                        result_process_strategies = None

                    tool_instance = DynamicAPISkillFunction(
                        name=tool_name,
                        description=description,
                        parameters=parameters,
                        api_url=api_url,
                        original_schema=original_schema,
                        fixed_params=fixed_params,
                        headers=headers,
                        result_process_strategies=result_process_strategies,
                        owner_skillkit=current_skillkit,
                    )

                else:
                    self.context.error(
                        f"Dynamic tool '{tool_name}' must provide either 'tool_instance' or 'api_call_strategy'. "
                        f"For pre-wrapped tools, provide 'tool_instance'. "
                        f"For API tools, provide 'api_call_strategy', 'api_url', 'original_schema', and optionally 'fixed_params'."
                    )
                    continue

                # Standard approach: Apply interrupt_config if provided in tool_def
                if "interrupt_config" in tool_def:
                    interrupt_config = tool_def.get("interrupt_config")
                    if interrupt_config and isinstance(interrupt_config, dict):
                        tool_instance.interrupt_config = interrupt_config
                        self.context.debug(
                            f"[_load_dynamic_tools] Applied interrupt_config to {tool_name}"
                        )

                # Hook: Allow upper layer (SDK) to post-process tool instance
                # This allows SDK to apply temporary policies (e.g., auto-add interrupt_config)
                if hasattr(self.context, 'on_dynamic_tool_loaded'):
                    try:
                        self.context.on_dynamic_tool_loaded(tool_instance, tool_def)
                    except Exception as e:
                        self.context.error(f"Error in on_dynamic_tool_loaded hook: {e}")

                # Add tool instance to skillkit
                current_skillkit.addSkill(tool_instance)
                loaded_count += 1

                # CRITICAL FIX: Also update self.skills if it exists (for ExploreBlock to see new tools)
                if hasattr(self, "skills"):
                    if isinstance(self.skills, list):
                        if tool_name not in self.skills:
                            self.skills.append(tool_name)
                            self.context.debug(
                                f"[BasicCodeBlock] Added {tool_name} to self.skills"
                            )
                    else:
                        self.context.debug(
                            f"[_load_dynamic_tools] self.skills is not a list, cannot append"
                        )
                else:
                    self.context.debug(
                        f"[_load_dynamic_tools] self.skills does not exist on {type(self).__name__}"
                    )

                self.context.debug(f"[OK] Dynamically loaded tool: {tool_name}")

            except Exception as e:
                tool_name = (
                    tool_def.get("name", "unknown")
                    if isinstance(tool_def, dict)
                    else "unknown"
                )
                self.context.error(f"[ERROR] Failed to load dynamic tool {tool_name}: {e}")
                import traceback

                self.context.debug(f"Error traceback: {traceback.format_exc()}")

        self.context.info(
            f"Successfully loaded {loaded_count}/{len(_dynamic_tools)} dynamic tools"
        )

        # CRITICAL: Recalculate all_skills to include newly loaded tools
        # Context.get_skillkit() matches tools from all_skills, must recalculate
        if hasattr(self.context, "_calc_all_skills"):
            self.context._calc_all_skills()
            self.context.debug(
                f"[_load_dynamic_tools] all_skills updated, now has {len(list(self.context.all_skills.getSkillNames()))} tools"
            )
            self.context.debug(
                "[BasicCodeBlock] Recalculated all_skills after loading dynamic tools"
            )

        # Log current available tools (for debugging)
        if self.context.is_verbose():
            all_tools = list(current_skillkit.getSkillNames())
            self.context.debug(f"Current available tools: {all_tools}")

        return loaded_count
