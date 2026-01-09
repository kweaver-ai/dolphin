from __future__ import annotations
import json
import traceback
from typing import Optional, AsyncGenerator, Dict, Any
from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.enums import (
    CategoryBlock,
    MessageRole,
    Messages,
    PlainMessages,
    TypeStage,
    StreamItem,
)
from dolphin.core.common.constants import (
    MAX_SKILL_CALL_TIMES,
    get_msg_duplicate_skill_call,
)
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.config.settings import BuildInBucket
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.logging.logger import console, console_skill_response, get_logger
from dolphin.lib.skillkits.cognitive_skillkit import CognitiveSkillkit
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.common.types import SourceType
from dolphin.lib.skillkits.system_skillkit import SystemFunctions

logger = get_logger("code_block.explore_block_v2")


class DeduplicatorSkillCall:
    MAX_DUPLICATE_COUNT = 5

    def __init__(self):
        # Optimize performance of duplicate checking using sets
        self.skillcalls = {}
        self.call_results = {}
        # Cache the string representation of skill calls to avoid redundant serialization.
        self._call_key_cache = {}

    def clear(self):
        """Clear all cached data"""
        self.skillcalls.clear()
        self.call_results.clear()
        self._call_key_cache.clear()

    def _get_call_key(self, skill_call):
        """Get the standardized string representation of a skill call (with caching)"""
        # Use id() as the cache key, because skill_call is usually a hashable object
        cache_key = id(skill_call)
        if cache_key in self._call_key_cache:
            return self._call_key_cache[cache_key]

        call_key = json.dumps(skill_call, sort_keys=True, ensure_ascii=False)
        self._call_key_cache[cache_key] = call_key
        return call_key

    def add(self, skill_call, result=None):
        """Add skill invocation record"""
        call_key = self._get_call_key(skill_call)
        self.skillcalls[call_key] = self.skillcalls.get(call_key, 0) + 1
        if result is not None:
            self.call_results[call_key] = result

    def is_duplicate(self, skill_call):
        """Check if it's a repeated call"""
        call_key = self._get_call_key(skill_call)

        # For certain tools, allow re-invocation if the result of the previous call is invalid.
        if self._should_allow_retry(skill_call, call_key):
            return False

        return self.skillcalls.get(call_key, 0) >= self.MAX_DUPLICATE_COUNT

    def _should_allow_retry(self, skill_call, call_key):
        """Determine whether to allow retrying a skill invocation"""
        skill_name = skill_call.get("name", "")

        # A call without arguments is always allowed to be retried
        if not skill_call.get("arguments"):
            return True

        # Allow retries if previous results are invalid for tools such as browser_snapshot
        if "snapshot" in skill_name.lower():
            previous_result = self.call_results.get(call_key)
            if previous_result is not None:
                result_str = str(previous_result).strip().lower()
                # If the previous result is too short or contains error messages, retries are allowed.
                return (
                    len(result_str) < 50
                    or "about:blank" in result_str
                    or "error" in result_str
                    or "empty" in result_str
                )

        return False


class ExploreBlockV2(BasicCodeBlock):
    def __init__(
        self,
        context: Context,
        debug_infos: Optional[dict] = None,
        tools_format: str = "medium",
    ):
        super().__init__(context)

        self.llm_client = LLMClient(self.context)
        self.debug_infos = debug_infos
        self.times = 0
        self.deduplicator_skillcall = DeduplicatorSkillCall()
        # Tools description format: "concise", "medium", or "detailed"
        self.tools_format = tools_format
        # Mark whether exploration should be stopped (set to True when there is no tool call)
        self.should_stop_exploration = False
        # Whether to enable skill call deduplication (consistent with the semantics of ExploreBlock, enabled by default)
        self.enable_skill_deduplicator = getattr(
            self, "enable_skill_deduplicator", True
        )

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.EXPLORE,
        replace_variables=True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # Call the parent class's execute method
        async for _ in super().execute(content, category, replace_variables):
            pass

        # Compatible with older versions, output the entire progress content
        self.recorder.set_output_dump_process(True) if self.recorder else None

        self.block_start_log("explore")

        # reset messages first, then build init messages to preserve system and history
        self._make_init_messages()

        # Consume the async generator to execute the logic
        async for ret in self._execute_generator():
            yield ret

        # Update history and cleanup buckets after execution
        # Uses the base class implementation in BasicCodeBlock
        self._update_history_and_cleanup()

    async def _execute_generator(self):
        """
        Actual implementation that yields results
        """
        # Simplify has_add variable initialization
        has_add = False if self.assign_type == ">>" else None

        # Use loops instead of recursion to avoid stack overflow
        while True:
            async for ret in self._explore_once(no_cache=True):
                if self.assign_type == ">>":
                    if has_add:
                        self.context.update_var_output(
                            self.output_var, ret, SourceType.EXPLORE
                        )
                    else:
                        self.context.append_var_output(
                            self.output_var, ret, SourceType.EXPLORE
                        )
                        has_add = True
                elif self.assign_type == "->":
                    self.context.set_var_output(
                        self.output_var, ret, SourceType.EXPLORE
                    )
                # If assign_type is another value, do nothing
                yield ret

            # Check whether to continue the next exploration
            if not self._should_continue_explore():
                break

    def _make_system_message(self):
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

        skillkit = self.get_skillkit()
        if skillkit is not None and not skillkit.isEmpty():
            # Use the configured tools format (concise/medium/detailed)
            tools_description = skillkit.getFormattedToolsDescription(self.tools_format)
            role_format = role_format.replace(r"{tools}", tools_description)
        else:
            role_format = role_format.replace(
                r"{tools}", "用户没有配置工具，你只能自己回答问题！"
            )

        # Inject metadata prompt from skillkits via skill.owner_skillkit
        from dolphin.core.skill.skillkit import Skillkit
        metadata_prompt = Skillkit.collect_metadata_from_skills(skillkit)
        role_format = role_format.replace(r"{metadata_prompt}", metadata_prompt)

        # Replace user system prompt
        if not self.system_prompt or len(self.system_prompt.strip()) == 0:
            role_format = role_format.replace(r"{system_prompt}", "")
        else:
            role_format = role_format.replace(r"{system_prompt}", self.system_prompt)

        return role_format


    def _make_history_messages(self):
        if isinstance(self.history, bool):
            use_history_flag = self.history
        else:
            use_history_flag = self.history.lower() == "true"

        if use_history_flag:
            history_messages = self.context.get_history_messages()
            return history_messages or Messages()
        return None

    def _make_init_messages(self):
        """Build initialization message"""
        system_message = self._make_system_message()
        history_messages = self._make_history_messages()
        self._add_messages_to_context_manager(system_message, history_messages)

    def _add_messages_to_context_manager(
        self, system_message: str, history_messages: Messages
    ):
        if len(system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                system_message,
                message_role=MessageRole.SYSTEM,
            )

        if self.content and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.QUERY.value,
                self.content,
            )

        if (
            self.history
            and history_messages is not None
            and not history_messages.empty()
            and self.context.context_manager
        ):
            self.context.set_history_bucket(history_messages)

    async def _explore_once(self, no_cache: bool = False):
        """Perform one exploration to avoid recursive calls"""

        self.context.debug(
            f"explore[{self.output_var}] messages[{self.context.get_messages().str_last()}] length[{self.context.get_messages().length()}]"
        )

        # Check if there is a tool call for interrupt recovery
        if self._has_pending_tool_call():
            async for ret in self._handle_resumed_tool_call():
                yield ret
        else:
            async for ret in self._handle_new_tool_call(no_cache):
                yield ret

    def _has_pending_tool_call(self) -> bool:
        """Check if there are pending tool calls"""
        intervention_tmp_key = "intervention_explore_block_vars"
        return (
            intervention_tmp_key in self.context.get_all_variables().keys()
            and "tool" in self.context.get_all_variables().keys()
        )

    async def _handle_resumed_tool_call(self):
        """Tool calls for handling interrupt recovery"""
        intervention_tmp_key = "intervention_explore_block_vars"

        # Get the content of saved temporary variables
        intervention_vars = self.context.get_var_value(intervention_tmp_key)
        self.context.delete_variable(intervention_tmp_key)

        # restore the complete message context before tool execution
        saved_messages = intervention_vars.get("prompt")
        if saved_messages is not None:
            msgs = Messages()
            msgs.extend_plain_messages(saved_messages)
            self.context.set_messages(msgs)

        input_dict = self.context.get_var_value("tool")
        function_name = input_dict["tool_name"]
        raw_tool_args = input_dict["tool_args"]
        function_params_json = {arg["key"]: arg["value"] for arg in raw_tool_args}

        (
            self.recorder.update(
                stage=TypeStage.SKILL,
                source_type=SourceType.EXPLORE,
                skill_name=function_name,
                skill_type=self.context.get_skill_type(function_name),
                skill_args=function_params_json,
            )
            if self.recorder
            else None
        )
        self.context.delete_variable("tool")

        return_answer = {}
        try:
            props = {"intervention": False}
            have_answer = False

            async for resp in self.skill_run(
                skill_name=function_name,
                source_type=SourceType.EXPLORE,
                skill_params_json=function_params_json,
                props=props,
            ):
                if (
                    isinstance(resp, dict)
                    and "answer" in resp
                    and isinstance(resp["answer"], dict)
                    and "answer" in resp["answer"]
                ):
                    return_answer["answer"] = resp.get("answer", "").get("answer", "")
                    return_answer["think"] = resp.get("answer", "").get("think", "")
                    if "block_answer" in resp:
                        return_answer["block_answer"] = resp.get("block_answer", "")
                else:
                    (
                        self.recorder.update(
                            item={"answer": resp, "block_answer": resp},
                            stage=TypeStage.SKILL,
                            source_type=SourceType.EXPLORE,
                            skill_name=function_name,
                            skill_type=self.context.get_skill_type(function_name),
                            skill_args=function_params_json,
                        )
                        if self.recorder
                        else None
                    )
                have_answer = True
                yield self.recorder.get_progress_answers() if self.recorder else None
            console_skill_response(
                skill_name=function_name,
                response=self.recorder.get_answer() if self.recorder else "",
                max_length=1024,
            )

            if not have_answer:
                (
                    self.recorder.update(
                        item=f"调用{function_name}工具时未正确返回结果，需要重新调用。",
                        source_type=SourceType.EXPLORE,
                    )
                    if self.recorder
                    else None
                )
        except ToolInterrupt as e:
            if "tool" in self.context.get_all_variables().keys():
                self.context.delete_variable("tool")
            yield self.recorder.get_progress_answers() if self.recorder else None
            raise e
        except Exception as e:
            logger.error(f"调用工具存在错误，错误类型: {type(e)}")
            logger.error(f"错误详细信息: {str(e)}")
            return_answer["think"] = (
                f"调用{function_name}工具时发生错误，需要重新调用。错误信息: {str(e)}"
            )
            return_answer["answer"] = (
                f"调用{function_name}工具时发生错误，需要重新调用。错误信息: {str(e)}"
            )

        return_answer["status"] = "completed"
        yield [return_answer]

        # append tool response message to maintain consistent message flow
        tool_response, metadata = self._process_skill_result_with_hook(function_name)

        if tool_response:
            # Extract tool_call_id from the restored messages
            tool_call_id = self._extract_tool_call_id()
            if not tool_call_id:
                tool_call_id = f"call_{function_name}_{self.times}"

            self._append_tool_message(tool_call_id, str(tool_response), metadata)

    async def _handle_new_tool_call(self, no_cache: bool):
        """Handling new tool calls"""
        # Get LLM message
        llm_messages = self.context.context_manager.to_dph_messages()

        llm_params = {
            "messages": llm_messages,
            "model": self.model,
            "no_cache": no_cache,
            "tools": self.get_skillkit().getSkillsSchema(),
        }
        # propagate tool_choice if provided in params/block
        if getattr(self, "tool_choice", None):
            llm_params["tool_choice"] = self.tool_choice

        # Create stream renderer for live markdown (CLI layer)
        renderer = None
        on_chunk = None
        if self.context.is_cli_mode():
            try:
                from dolphin.cli.ui.stream_renderer import LiveStreamRenderer
                renderer = LiveStreamRenderer(verbose=self.context.is_verbose())
                renderer.start()
                on_chunk = renderer.on_chunk
            except ImportError:
                pass

        try:
            # Initialize the stream_item variable to avoid undefined error
            stream_item = StreamItem()
            async for stream_item in self.llm_chat_stream(
                llm_params=llm_params,
                recorder=self.recorder,
                content=self.content if self.content else "",
                early_stop_on_tool_call=True,
                on_stream_chunk=on_chunk,
            ):
                if not stream_item.has_tool_call():
                    yield self.recorder.get_progress_answers() if self.recorder else None
                elif stream_item.has_complete_tool_call():
                    logger.debug(
                        f"explore[{self.output_var}] find skill call [{stream_item.tool_name}]"
                    )
                    break
        finally:
            if renderer:
                renderer.stop()

        # Removed extra newline - renderer.stop() already handles this

        if self.times >= MAX_SKILL_CALL_TIMES:
            self.context.warn(
                f"max skill call times reached {MAX_SKILL_CALL_TIMES} times, answer[{stream_item.to_dict()}]"
            )
        else:
            self.times += 1

        (
            self.recorder.update(
                item=stream_item,
                raw_output=stream_item.answer,
                is_completed=True,
                source_type=SourceType.EXPLORE,
            )
            if self.recorder
            else None
        )
        yield self.recorder.get_progress_answers() if self.recorder else None

        if not stream_item.has_tool_call():
            self._append_assistant_message(stream_item.answer)
            self.context.debug(f"no valid skill call, answer[{stream_item.answer}]")

            # Stop exploring as soon as there is one instance without tool invocation
            self.should_stop_exploration = True
            self.context.debug("没有工具调用，停止探索")

            return

        # Add assistant message containing tool calls
        tool_call_id = f"call_{stream_item.tool_name}_{self.times}"
        tool_call_openai_format = [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": stream_item.tool_name,
                    "arguments": (
                        json.dumps(stream_item.tool_args, ensure_ascii=False)
                        if stream_item.tool_args
                        else "{}"
                    ),
                },
            }
        ]

        tool_call = stream_item.get_tool_call()
        # When enable_skill_deduplicator is False, disable the deduplication logic and always treat as non-duplicate calls.
        if (not getattr(self, "enable_skill_deduplicator", True)) or (
            not self.deduplicator_skillcall.is_duplicate(tool_call)
        ):
            self._append_tool_call_message(
                stream_item, tool_call_openai_format
            )
            self.deduplicator_skillcall.add(tool_call)

            async for ret in self._execute_tool_call(stream_item, tool_call_id):
                yield ret
        else:
            await self._handle_duplicate_tool_call(tool_call, stream_item)

    async def _execute_tool_call(self, stream_item, tool_call_id: str):
        """Execute tool call"""
        intervention_tmp_key = "intervention_explore_block_vars"

        try:
            intervention_vars = {
                "prompt": self.context.get_messages().get_messages_as_dict(),
                "tool_name": stream_item.tool_name,
                "cur_llm_stream_answer": stream_item.answer,
                "all_answer": stream_item.answer,
            }

            self.context.set_variable(intervention_tmp_key, intervention_vars)

            async for resp in self.skill_run(
                source_type=SourceType.EXPLORE,
                skill_name=stream_item.tool_name,
                skill_params_json=(
                    stream_item.tool_args if stream_item.tool_args else {}
                ),
            ):
                yield self.recorder.get_progress_answers() if self.recorder else None

            self.deduplicator_skillcall.add(
                stream_item.get_tool_call(),
                self.recorder.get_answer() if self.recorder else None,
            )

            # Add tool response message
            tool_response, metadata = self._process_skill_result_with_hook(stream_item.tool_name)

            answer_content: str = (
                tool_response
                if tool_response is not None
                and not CognitiveSkillkit.is_cognitive_skill(stream_item.tool_name)
                else ""
            )

            if len(answer_content) > self.context.get_max_answer_len():
                answer_content = answer_content[
                    : self.context.get_max_answer_len()
                ] + "(... too long, truncated to {})".format(
                    self.context.get_max_answer_len()
                )

            self._append_tool_message(tool_call_id, answer_content, metadata)

        except ToolInterrupt as e:
            self._handle_tool_interrupt(e, stream_item.tool_name)
            raise e
        except Exception as e:
            self._handle_tool_execution_error(e, stream_item.tool_name)
            # Add tool response message even if error occurs (maintain context integrity)
            error_content = f"Tool execution error: {str(e)}"
            self._append_tool_message(tool_call_id, error_content, None)

    async def _handle_duplicate_tool_call(self, tool_call, stream_item):
        """Handling Duplicate Tool Calls"""
        message = get_msg_duplicate_skill_call()
        self._append_assistant_message(message)

        (
            self.recorder.update(
                item={"answer": message, "think": ""},
                raw_output=stream_item.answer,
                source_type=SourceType.EXPLORE,
            )
            if self.recorder
            else None
        )
        self.context.warn(
            f"Duplicate skill call detected: {self.deduplicator_skillcall._get_call_key(tool_call)}"
        )

    def _handle_tool_interrupt(self, e: Exception, tool_name: str):
        """Handling Tool Interruptions"""
        self.context.info(f"tool interrupt in call {tool_name} tool")
        if "※tool" in self.context.get_all_variables().keys():
            self.context.delete_variable("※tool")

    def _handle_tool_execution_error(self, e: Exception, tool_name: str):
        """Handling tool execution errors"""
        error_trace = traceback.format_exc()
        self.context.error(
            f"error in call {tool_name} tool, error type: {type(e)}, error info: {str(e)}, error trace: {error_trace}"
        )

    def _should_continue_explore(self) -> bool:
        """Check whether to continue the next exploration.

                Termination conditions:
                1. Maximum number of tool calls reached
                2. Duplicate tool call detected
                3. No tool call occurred once

        Returns:
            bool: True if exploration should continue, False otherwise
        """
        # 1. If the maximum number of calls has been reached, stop exploring
        if self.times >= MAX_SKILL_CALL_TIMES:
            return False

        # 2. Check for duplicate calls (effective only when skill deduplicator is enabled)
        if getattr(self, "enable_skill_deduplicator", True):
            if self.deduplicator_skillcall.skillcalls:
                recent_calls = list(self.deduplicator_skillcall.skillcalls.values())
                if (
                    recent_calls
                    and max(recent_calls)
                    >= DeduplicatorSkillCall.MAX_DUPLICATE_COUNT
                ):
                    return False

        # 3. Stop exploring when there is no tool call.
        if self.should_stop_exploration:
            return False

        return True

    def _process_skill_result_with_hook(self, skill_name: str) -> tuple[str | None, dict]:
        """Handle skill results using skillkit_hook

        Args:
            skill_name: Name of the skill

        Returns:
            tuple[str | None, dict]: (Processed result, metadata)
        """
        # Get skill object
        skill = self.context.get_skill(skill_name)
        if not skill:
            skill = SystemFunctions.getSkill(skill_name)

        # Get the last stage as reference
        last_stage = self.recorder.getProgress().get_last_stage()
        reference = last_stage.get_raw_output() if last_stage else None
        # Handle results using skillkit_hook (handles dynamic tools automatically)
        if reference and self.skillkit_hook and self.context.has_skillkit_hook():
            # Use new hook to get context-optimized content
            content, metadata = self.skillkit_hook.on_before_send_to_context(
                reference_id=reference.reference_id,
                skill=skill,
                skillkit_name=type(skill.owner_skillkit).__name__ if skill.owner_skillkit else "",
                resource_skill_path=getattr(skill, 'resource_skill_path', None),
            )
            return content, metadata
        
        return self.recorder.getProgress().get_step_answers(), {}

    def _append_tool_message(
        self,
        tool_call_id: str,
        answer_content: str,
        metadata: Optional[dict] = None,
    ):
        """Add tool messages to context uniformly"""
        scrapted_messages = Messages()
        scrapted_messages.add_tool_response_message(
            content=answer_content,
            tool_call_id=tool_call_id,
            metadata=metadata,
        )
        self.context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def _append_tool_call_message(
        self,
        stream_item,
        tool_call_openai_format: list,
    ):
        """Add tool call messages to context uniformly"""
        scrapted_messages = Messages()
        scrapted_messages.add_tool_call_message(
            content=stream_item.answer, tool_calls=tool_call_openai_format
        )
        self.context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def _append_assistant_message(self, content: str):
        """Add assistant message to context uniformly"""
        scrapted_messages = Messages()
        scrapted_messages.add_message(content, MessageRole.ASSISTANT)
        self.context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def _extract_tool_call_id(self) -> str | None:
        """Extract tool call ID from the message"""
        messages_with_calls = self.context.get_messages_with_tool_calls()
        if messages_with_calls:
            last_call_msg = messages_with_calls[-1]
            if last_call_msg.tool_calls:
                return last_call_msg.tool_calls[0].get("id")
        return None
