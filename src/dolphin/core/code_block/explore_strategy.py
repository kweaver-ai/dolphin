"""Explore Mode Strategy Interface and Implementation

This module defines the ExploreStrategy abstract interface and provides two concrete implementations:
- PromptStrategy: Prompt mode, invoking tools in the prompt using the =># format
- ToolCallStrategy: Tool Call mode, utilizing the LLM's native tool_call capability

Design documents:
- Strategy design: docs/design/architecture/explore_block_merge.md
- Multiple tool calls: docs/design/core/multiple-tool-calls.md
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from dolphin.core.common.enums import StreamItem, Messages, MessageRole
from dolphin.core.common.constants import TOOL_CALL_ID_PREFIX
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.config.settings import BuildInBucket
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.code_block.skill_call_deduplicator import (
    SkillCallDeduplicator,
    DefaultSkillCallDeduplicator,
    NoOpSkillCallDeduplicator,
)


@dataclass
class ToolCall:
    """Unified data structure for tool calls

        Used to pass tool call information between different strategies.
    """
    id: str  # Tool call unique identifier
    name: str  # Tool/Skill Name
    arguments: Dict[str, Any]  # Tool call parameters
    raw_text: Optional[str] = None  # Original text (used only in Prompt mode)


class ExploreStrategy(ABC):
    """Exploration Mode Strategy Base Class

        Defines core methods that different exploration modes need to implement, and provides a general implementation.
    """

    def __init__(self):
        self._deduplicator = DefaultSkillCallDeduplicator()
        self._noop_deduplicator = NoOpSkillCallDeduplicator()
        self._deduplicator_enabled: bool = True

    # ============ Abstract Methods (must be implemented by subclasses) ============

    @abstractmethod
    def make_system_message(
        self,
        skillkit: Skillkit,
        system_prompt: str,
        tools_format: str = "medium"
    ) -> str:
        """Build system message containing tool descriptions"""
        pass

    @abstractmethod
    def get_llm_params(
        self,
        messages: Messages,
        model: str,
        skillkit: Skillkit,
        tool_choice: Optional[str] = None,
        no_cache: bool = False,
    ) -> Dict[str, Any]:
        """Build LLM call parameters"""
        pass

    @abstractmethod
    def detect_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> Optional[ToolCall]:
        """Detect tool calls from streaming responses """
        pass

    @abstractmethod
    def has_valid_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> bool:
        """Check for valid tool calls in streaming responses"""
        pass

    @abstractmethod
    def get_tool_call_content(
        self,
        stream_item: StreamItem,
        tool_call: ToolCall
    ) -> str:
        """Get the content part of the tool call message

                Prompt mode: return the content before the tool call marker
                Tool Call mode: return the complete answer
        """
        pass

    # ============ Generic Implementation (Reusable by Subclasses) ============

    def append_tool_call_message(
        self,
        context: Context,
        stream_item: StreamItem,
        tool_call: ToolCall,
    ):
        """Append additional tool call messages to context"""
        tool_call_openai_format = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": (
                        json.dumps(tool_call.arguments, ensure_ascii=False)
                        if tool_call.arguments
                        else "{}"
                    ),
                },
            }
        ]

        content = self.get_tool_call_content(stream_item, tool_call)

        scrapted_messages = Messages()
        scrapted_messages.add_tool_call_message(
            content=content, tool_calls=tool_call_openai_format
        )
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def append_tool_response_message(
        self,
        context: Context,
        tool_call_id: str,
        response: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add tool response message to context"""
        scrapted_messages = Messages()
        scrapted_messages.add_tool_response_message(
            content=response,
            tool_call_id=tool_call_id,
            metadata=metadata
        )
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    # ============ Multiple Tool Calls Support ============

    def detect_tool_calls(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> List[ToolCall]:
        """Detect multiple tool calls from streaming responses (new method).

        Default implementation wraps detect_tool_call() to return a single-item list.
        Subclasses that support native multi-tool-call (e.g., ToolCallStrategy)
        should override this method to properly extract multiple tool calls.

        Note: PromptStrategy uses this default implementation since it relies on
        the =># text format which doesn't support native parallel tool calls.

        Args:
            stream_item: The streaming response item from LLM
            context: The execution context

        Returns:
            List of ToolCall objects. Empty list if no tool calls detected.
        """
        single = self.detect_tool_call(stream_item, context)
        return [single] if single else []

    def append_tool_calls_message(
        self,
        context: Context,
        stream_item: StreamItem,
        tool_calls: List[ToolCall],
    ):
        """Append multiple tool calls message to context.
        
        Creates a single assistant message containing all tool calls in OpenAI format.
        This is required for proper multi-tool-call support where all tool calls
        must be in a single message.
        
        Args:
            context: The execution context
            stream_item: The streaming response item (for extracting content)
            tool_calls: List of ToolCall objects to include in the message
        """
        tool_calls_openai_format = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": (
                        json.dumps(tc.arguments, ensure_ascii=False)
                        if tc.arguments
                        else "{}"
                    ),
                },
            }
            for tc in tool_calls
        ]

        content = stream_item.answer or ""
        scratched_messages = Messages()
        scratched_messages.add_tool_call_message(
            content=content, tool_calls=tool_calls_openai_format
        )
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scratched_messages,
        )

    def set_deduplicator_enabled(self, enabled: bool):
        """Enable or disable the skill call deduplicator

        Args:
            enabled: Whether to enable the deduplicator; an empty implementation is used when False
        """
        self._deduplicator_enabled = bool(enabled)

    def get_deduplicator(self) -> SkillCallDeduplicator:
        """Get duplicate call detector"""
        if self._deduplicator_enabled:
            return self._deduplicator
        return self._noop_deduplicator

    def reset_deduplicator(self):
        """Reset the deduplicator state for retry scenarios."""
        self._deduplicator.clear()

    def get_tool_call_history(self) -> list:
        """Get the history of tool calls from the deduplicator.

        Returns:
            List of tool call dictionaries
        """
        return self._deduplicator.get_history()


class PromptStrategy(ExploreStrategy):
    """Prompt Pattern Strategy Implementation

        Tool Calling Method: Call tools in the prompt using the =>#tool_name: {json} format
    """

    TOKEN_TOOL_CALL = "=>#"

    def __init__(self):
        super().__init__()

    def append_tool_call_message(
        self,
        context: Context,
        stream_item: StreamItem,
        tool_call: ToolCall,
    ):
        """Add additional tool call messages to the context (using plain text format in Prompt mode)

                In Prompt mode, LLM uses =># format to invoke tools, not OpenAI native tool_call.
                Therefore, the messages should remain in plain text format without containing a tool_calls array.
        """
        # Use full =># format text as the assistant message content
        content = stream_item.answer or ""

        scrapted_messages = Messages()
        scrapted_messages.add_message(content, role=MessageRole.ASSISTANT)
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def append_tool_response_message(
        self,
        context: Context,
        tool_call_id: str,
        response: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add tool response message to context (used in Prompt mode with user message format)

                In Prompt mode, LLM does not understand OpenAI's tool role message format.
                Tool responses should be added in user message format so that the LLM can understand and continue the conversation.
        """
        # Format tool response as user message
        formatted_response = f"[工具返回结果]: {response}"

        scrapted_messages = Messages()
        scrapted_messages.add_message(formatted_response, role=MessageRole.USER, metadata=metadata)
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def make_system_message(
        self,
        skillkit: Skillkit,
        system_prompt: str,
        tools_format: str = "medium"
    ) -> str:
        """Build system message for Prompt mode.

        Includes:
        - Goals and tool schemas
        - Metadata prompt from skillkits (e.g., ResourceSkillkit Level 1)
        - User-provided system prompt
        """
        role_format = """
## Goals：
- 你需要分析用户的问题，决定由自己回答问题还是使用工具来处理问题。tools中的工具就是你可以使用的全部工具。

## tools:
{tools}

### tools use Constraints：
- 你必须清晰的理解问题和熟练使用工具，优先使用工具回答。
- 当需要调用工具的时候，你需要使用"=>#tool_name: {{key:value}}"的格式来调用工具,其中参数为严格的json格式，例如"=>#someskill: {"key1": "value1", "key2": "value2"}"。

{metadata_prompt}
{system_prompt}
"""
        if skillkit is not None and not skillkit.isEmpty():
            # Use getFormattedToolsDescription instead of getSchemas for better readability
            role = role_format.replace(r"{tools}", skillkit.getFormattedToolsDescription(tools_format))
        else:
            role_format = """{metadata_prompt}
{system_prompt}"""
            role = role_format

        # Inject metadata prompt from skillkits via skill.owner_skillkit
        metadata_prompt = Skillkit.collect_metadata_from_skills(skillkit)
        role = role.replace(r"{metadata_prompt}", metadata_prompt)

        # Replace user system prompt
        if len(system_prompt.strip()) == 0:
            role = role.replace(r"{system_prompt}", "")
        else:
            role = role.replace(
                r"{system_prompt}", "## User Demands:\n" + system_prompt.strip()
            )
        return role

    def get_llm_params(
        self,
        messages: Messages,
        model: str,
        skillkit: Skillkit,
        tool_choice: Optional[str] = None,
        no_cache: bool = False,
    ) -> Dict[str, Any]:
        """Prompt mode does not pass the tools parameter"""
        return {
            "messages": messages,
            "model": model,
            "no_cache": no_cache,
        }

    def detect_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> Optional[ToolCall]:
        """Detect tool calls from responses in Prompt mode"""
        answer = stream_item.answer
        if not answer or self.TOKEN_TOOL_CALL not in answer:
            return None

        skill_name = self._first_likely_skill(answer)
        if not skill_name:
            return None

        skillkit = context.get_skillkit()
        if skillkit is None or skill_name not in skillkit.getSkillNames():
            return None

        skill_call = self._complete_skill_call(answer)
        if skill_call is None:
            return None

        skill_name, arguments = skill_call
        tool_call_id = f"{TOOL_CALL_ID_PREFIX}{skill_name}_{id(stream_item) % 10000}"

        return ToolCall(
            id=tool_call_id,
            name=skill_name,
            arguments=arguments,
            raw_text=self._first_likely_skill_call(answer)
        )

    def has_valid_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> bool:
        """Check if there is a valid tool call in the Prompt mode response"""
        answer = stream_item.answer
        if not answer or self.TOKEN_TOOL_CALL not in answer:
            return False

        skill_name = self._first_likely_skill(answer)
        if not skill_name:
            return False

        skillkit = context.get_skillkit()
        return skillkit is not None and skill_name in skillkit.getSkillNames()

    def get_tool_call_content(
        self,
        stream_item: StreamItem,
        tool_call: ToolCall
    ) -> str:
        """Get the content before tool invocation"""
        answer = stream_item.answer or ""
        if self.TOKEN_TOOL_CALL in answer:
            return answer.split(self.TOKEN_TOOL_CALL)[0]
        return answer

    # ============ Helper Methods ============

    def _first_likely_skill(self, buffer: str) -> Optional[str]:
        """Extract the first possible skill name from the buffer"""
        if self.TOKEN_TOOL_CALL not in buffer:
            return None
        return buffer.split(self.TOKEN_TOOL_CALL)[-1].split(":")[0].strip()

    def _first_likely_skill_call(self, buffer: str) -> str:
        """Get the first complete skill invocation text"""
        return self.TOKEN_TOOL_CALL + buffer.split(self.TOKEN_TOOL_CALL)[-1]

    def _complete_skill_call(self, buffer: str) -> Optional[tuple]:
        """Extract complete skill calls from buffer"""
        from dolphin.core.parser.parser import params_extract

        token = self.TOKEN_TOOL_CALL
        first_token_pos = buffer.find(token)
        if first_token_pos == -1:
            return None

        start_pos = first_token_pos + len(token)
        colon_pos = buffer.find(":", start_pos)
        if colon_pos == -1:
            return None

        skill_name = buffer[start_pos:colon_pos].strip()
        params_start = colon_pos + 1

        while params_start < len(buffer) and buffer[params_start].isspace():
            params_start += 1

        if params_start >= len(buffer):
            return None

        if buffer[params_start] == "{":
            bracket_count = 0
            params_end = params_start
            in_string = False
            escape_next = False

            for i in range(params_start, len(buffer)):
                char = buffer[i]

                if escape_next:
                    escape_next = False
                    continue

                if char == "\\":
                    escape_next = True
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == "{":
                        bracket_count += 1
                    elif char == "}":
                        bracket_count -= 1
                        if bracket_count == 0:
                            params_end = i + 1
                            break

            if bracket_count == 0:
                params_content = buffer[params_start:params_end]
                parsed_params = params_extract(params_content)
                return (skill_name, parsed_params)

        return None


class ToolCallStrategy(ExploreStrategy):
    """Tool Call Mode Strategy Implementation

        Tool Calling Method: Use the LLM's native tool_call capability
    """

    def __init__(self, tools_format: str = "medium"):
        super().__init__()
        self.tools_format = tools_format

    def make_system_message(
        self,
        skillkit: Skillkit,
        system_prompt: str,
        tools_format: str = "medium"
    ) -> str:
        """Build system message for Tool Call mode.

        Includes:
        - Goals and tool descriptions
        - Metadata prompt from skillkits (e.g., ResourceSkillkit Level 1)
        - User-provided system prompt
        """
        role_format = """
## Goals：
- 你需要：先仔细思考和分析用户的问题，然后决定由自己回答问题还是使用工具来处理问题，务必在调用工具前仔细思考。tools中的工具就是你可以使用的全部工具。

## Available Tools:
{tools}

### Tools Usage Guidelines：
- 仔细阅读每个工具的描述和参数要求
- 根据问题的具体需求选择最合适的工具
- 在调用工具前确保参数完整和正确
- 如果不确定工具用法，可以先尝试简单的调用来了解

{metadata_prompt}
{system_prompt}
        """

        # Replace tools description
        if skillkit is not None and not skillkit.isEmpty():
            tools_description = skillkit.getFormattedToolsDescription(tools_format)
            role_format = role_format.replace(r"{tools}", tools_description)
        else:
            role_format = role_format.replace(
                r"{tools}", "用户没有配置工具，你只能自己回答问题！"
            )

        # Inject metadata prompt from skillkits via skill.owner_skillkit
        metadata_prompt = Skillkit.collect_metadata_from_skills(skillkit)
        role_format = role_format.replace(r"{metadata_prompt}", metadata_prompt)

        # Replace user system prompt
        if not system_prompt or len(system_prompt.strip()) == 0:
            role_format = role_format.replace(r"{system_prompt}", "")
        else:
            role_format = role_format.replace(r"{system_prompt}", system_prompt)

        return role_format

    def get_llm_params(
        self,
        messages: Messages,
        model: str,
        skillkit: Skillkit,
        tool_choice: Optional[str] = None,
        no_cache: bool = False,
    ) -> Dict[str, Any]:
        """Includes the tools parameter and an optional tool_choice"""
        tools = skillkit.getSkillsSchema() if skillkit and not skillkit.isEmpty() else []
        
        # Debug: print tools schema
        print(f"\n[DEBUG] ToolCallStrategy.get_llm_params:")
        print(f"  Skillkit empty: {skillkit.isEmpty() if skillkit else 'None'}")
        print(f"  Tools count: {len(tools)}")
        if tools:
            print(f"  Tools schema: {tools}")
            # Check each tool for interrupt_config
            for i, tool_schema in enumerate(tools):
                tool_name = tool_schema.get('function', {}).get('name', 'unknown')
                print(f"    Tool[{i}]: {tool_name}")
                # Try to get the actual skill object
                if skillkit:
                    try:
                        skill = skillkit.getSkill(tool_name)
                        print(f"      Skill type: {type(skill).__name__}")
                        print(f"      Has interrupt_config: {hasattr(skill, 'interrupt_config')}")
                        if hasattr(skill, 'interrupt_config'):
                            print(f"      interrupt_config: {skill.interrupt_config}")
                    except Exception as e:
                        print(f"      Error getting skill: {e}")
        
        llm_params = {
            "messages": messages,
            "model": model,
            "no_cache": no_cache,
            "tools": tools,
        }

        if tool_choice:
            llm_params["tool_choice"] = tool_choice

        return llm_params

    def detect_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> Optional[ToolCall]:
        """Detect tool calls from Tool Call mode responses"""
        # Use has_tool_call() instead of has_complete_tool_call() to stay consistent with has_valid_tool_call()
        # This way tool calls can be detected even if tool_args are not fully received yet (args use empty dict)
        if not stream_item.has_tool_call():
            return None

        tool_call_id = stream_item.tool_call_id or f"{TOOL_CALL_ID_PREFIX}{stream_item.tool_name}_{id(stream_item) % 10000}"

        return ToolCall(
            id=tool_call_id,
            name=stream_item.tool_name,
            arguments=stream_item.tool_args or {},
            raw_text=None
        )

    def has_valid_tool_call(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> bool:
        """Check for valid tool calls in Tool Call mode responses"""
        return stream_item.has_tool_call()

    def get_tool_call_content(
        self,
        stream_item: StreamItem,
        tool_call: ToolCall
    ) -> str:
        """Return the complete answer"""
        return stream_item.answer or ""

    def detect_tool_calls(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> List[ToolCall]:
        """Detect multiple tool calls from Tool Call mode responses.
        
        Overrides base class to properly handle multiple tool calls
        from the StreamItem.tool_calls list.
        
        Note: Only returns tool calls where arguments have been successfully parsed.
        Logs warnings for tool calls with unparseable arguments when stream is complete.
        
        Args:
            stream_item: The streaming response item from LLM
            context: The execution context
            
        Returns:
            List of ToolCall objects with valid arguments.
        """
        tool_call_infos = stream_item.get_tool_calls()
        if not tool_call_infos:
            return []
        
        result = []
        for info in tool_call_infos:
            # Only include tool calls that are complete (arguments successfully parsed)
            # The is_complete field is set during parse_from_chunk when JSON parsing succeeds
            if info.is_complete and info.arguments is not None:
                result.append(ToolCall(
                    id=info.id,
                    name=info.name,
                    arguments=info.arguments,
                    raw_text=None
                ))
            elif stream_item.finish_reason is not None and not info.is_complete:
                # Stream has ended but arguments failed to parse - log warning
                context.warn(
                    f"Tool call {info.name} (id={info.id}) skipped: "
                    f"Stream ended but JSON arguments incomplete or invalid. "
                    f"Raw arguments: '{info.raw_arguments[:200]}...'" 
                    if len(info.raw_arguments) > 200 else
                    f"Tool call {info.name} (id={info.id}) skipped: "
                    f"Stream ended but JSON arguments incomplete or invalid. "
                    f"Raw arguments: '{info.raw_arguments}'"
                )
        
        return result
