"""ExploreBlock Code Block Implementation

Supports two tool calling modes:
- prompt mode: call tools in the prompt using =># format
- tool_call mode (default): use LLM's native tool_call capability

Control which mode to use via the mode parameter:
- mode="prompt": use PromptStrategy
- mode="tool_call" (default): use ToolCallStrategy

Design document: docs/architecture/explore_block_merge.md
"""

from __future__ import annotations

import json
import traceback
from typing import Any, AsyncGenerator, Dict, Optional

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.context_engineer.config.settings import BuildInBucket
from dolphin.lib.skillkits.system_skillkit import SystemFunctions

from dolphin.core.common.enums import (
    CategoryBlock,
    MessageRole,
    Messages,
    TypeStage,
    StreamItem,
)
from dolphin.core.common.constants import (
    MAX_SKILL_CALL_TIMES,
    get_msg_duplicate_skill_call,
)
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import console, console_skill_response
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.context.var_output import SourceType
from dolphin.core.logging.logger import get_logger
from dolphin.lib.skillkits.cognitive_skillkit import CognitiveSkillkit
from dolphin.core.code_block.explore_strategy import (
    ExploreStrategy,
    PromptStrategy,
    ToolCallStrategy,
    ToolCall,
)
from dolphin.core.code_block.skill_call_deduplicator import (
    DefaultSkillCallDeduplicator,
)

logger = get_logger("code_block.explore_block")


class ExploreBlock(BasicCodeBlock):
    """Explore code block implementation

        Supports two modes:
        - mode="prompt": uses PromptStrategy
        - mode="tool_call" (default): uses ToolCallStrategy

        Args:
            context: context object
            debug_infos: debug information (optional)
            tools_format: tool description format, "short"/"medium"/"full"

        Note:
            The mode parameter can only be specified via DPH syntax /explore/(mode="..."),
            not passed from the constructor, to avoid priority ambiguity.
            The default is "tool_call" mode, and parse_block_content() will update it based on DPH parameters after parsing.
    """

    def __init__(
        self,
        context: Context,
        debug_infos: Optional[dict] = None,
        tools_format: str = "medium",
    ):
        super().__init__(context)

        self.llm_client = LLMClient(self.context)
        self.debug_infos = debug_infos
        self.tools_format = tools_format

        # Mode control: The default uses the tool_call mode, and after parsing DPH parameters via parse_block_content(), updates are made.
        self.mode = "tool_call"
        self.strategy = self._create_strategy()

        # By default, deduplication is controlled by the Block parameter (finally takes effect in execute/continue_exploration)
        self.enable_skill_deduplicator = getattr(
            self, "enable_skill_deduplicator", True
        )

        # State Variables
        self.times = 0
        self.should_stop_exploration = False
        self.no_tool_call_count = 0  # Count consecutive rounds without tool calls
        self.pending_content = None  # Store content without tool_call for merging

    def _create_strategy(self) -> ExploreStrategy:
        """Create the corresponding strategy instance according to mode."""
        if self.mode == "prompt":
            return PromptStrategy()
        else:  # tool_call
            return ToolCallStrategy(tools_format=self.tools_format)

    def parse_block_content(self, content: str, category=None, replace_variables=True):
        """Override the parent class method to update mode and strategy after parsing DPH syntax.

                According to the design document docs/architecture/explore_block_merge.md:
                - /explore/(mode="tool_call", ...) should use ToolCallStrategy
                - /explore/(mode="prompt", ...) should use PromptStrategy
                - Default mode is "tool_call"
        """
        # Call parent class parsing
        super().parse_block_content(content, category, replace_variables)

        # Get mode from parsed arguments
        parsed_mode = self.params.get("mode", None)

        if parsed_mode is not None:
            # Validate mode values
            if parsed_mode not in ["prompt", "tool_call"]:
                raise ValueError(
                    f"Invalid mode: {parsed_mode}, must be 'prompt' or 'tool_call'"
                )

            # If mode differs from the current one, update mode and strategy
            if parsed_mode != self.mode:
                self.mode = parsed_mode
                self.strategy = self._create_strategy()

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.EXPLORE,
        replace_variables=True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute exploration code block"""
        # Call the parent class's execute method
        async for _ in super().execute(content, category, replace_variables):
            pass

        assert self.recorder, "recorder is None"

        # Compatible with older versions, output the entire progress content
        self.recorder.set_output_dump_process(True)

        self.block_start_log("explore")

        # Enable or disable the skill invocation deduplicator based on parameter configuration (enabled by default, can be disabled via enable_skill_deduplicator)
        if hasattr(self, "enable_skill_deduplicator"):
            self.strategy.set_deduplicator_enabled(self.enable_skill_deduplicator)

        # Save the current system prompt configuration to context for inheritance in multi-turn conversations.
        if getattr(self, "system_prompt", None):
            self.context.set_last_system_prompt(self.system_prompt)

        # Save the current skills configuration to context, so it can be inherited during multi-turn conversations.
        if getattr(self, "skills", None):
            self.context.set_last_skills(self.skills)

        # Save the current mode configuration to context for inheritance in multi-turn conversations.
        if getattr(self, "mode", None):
            self.context.set_last_explore_mode(self.mode)

        # Build initial message
        self._make_init_messages()

        # Variable assignment marker
        has_add = False if self.assign_type == ">>" else None

        # Perform exploration using loops
        while True:
            # Checkpoint: Check user interrupt before each exploration cycle
            self.context.check_user_interrupt()

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
                yield ret

            # Check whether to continue to the next exploration
            if not self._should_continue_explore():
                break

        # Update history and cleanup buckets after execution
        self._update_history_and_cleanup()

    def _make_init_messages(self):
        """Build initialization message"""
        skillkit = self.get_skillkit()
        system_message = self.strategy.make_system_message(
            skillkit=skillkit,
            system_prompt=self.system_prompt,
            tools_format=self.tools_format,
        )

        # Add system message
        if len(system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                system_message,
                message_role=MessageRole.SYSTEM,
            )

        # Add user question
        if self.content and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.QUERY.value,
                self.content,
            )

        # Process historical messages
        history_messages = self._make_history_messages()
        if (
            self.history
            and history_messages is not None
            and not history_messages.empty()
            and self.context.context_manager
        ):
            self.context.set_history_bucket(history_messages)

    def _make_history_messages(self) -> Optional[Messages]:
        """Build history messages"""
        if isinstance(self.history, bool):
            use_history_flag = self.history
        else:
            use_history_flag = str(self.history).lower() == "true"

        if use_history_flag:
            history_messages = self.context.get_history_messages()
            return history_messages or Messages()
        return None

    async def _explore_once(self, no_cache: bool = False):
        """Perform one exploration"""
        self.context.debug(
            f"explore[{self.output_var}] messages[{self.context.get_messages().str_last()}] "
            f"length[{self.context.get_messages().length()}]"
        )

        # Check if there is a tool call for interruption recovery
        if self._has_pending_tool_call():
            async for ret in self._handle_resumed_tool_call():
                yield ret
        else:
            async for ret in self._handle_new_tool_call(no_cache):
                yield ret

    def _has_pending_tool_call(self) -> bool:
        """Check if there are pending tool calls (interrupt recovery)"""
        intervention_tmp_key = "intervention_explore_block_vars"
        return (
            intervention_tmp_key in self.context.get_all_variables().keys()
            and "tool" in self.context.get_all_variables().keys()
        )

    async def _handle_resumed_tool_call(self):
        """Tools for handling interrupt recovery calls """
        intervention_tmp_key = "intervention_explore_block_vars"

        # Get the content of saved temporary variables
        intervention_vars = self.context.get_var_value(intervention_tmp_key)
        self.context.delete_variable(intervention_tmp_key)

        # Restore complete message context
        saved_messages = intervention_vars.get("prompt")
        if saved_messages is not None:
            msgs = Messages()
            msgs.extend_plain_messages(saved_messages)
            self.context.set_messages(msgs)

        input_dict = self.context.get_var_value("tool")
        function_name = input_dict["tool_name"]
        raw_tool_args = input_dict["tool_args"]
        function_params_json = {arg["key"]: arg["value"] for arg in raw_tool_args}

        if self.recorder:
            self.recorder.update(
                stage=TypeStage.SKILL,
                source_type=SourceType.EXPLORE,
                skill_name=function_name,
                skill_type=self.context.get_skill_type(function_name),
                skill_args=function_params_json,
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
                    if self.recorder:
                        self.recorder.update(
                            item={"answer": resp, "block_answer": resp},
                            stage=TypeStage.SKILL,
                            source_type=SourceType.EXPLORE,
                            skill_name=function_name,
                            skill_type=self.context.get_skill_type(function_name),
                            skill_args=function_params_json,
                        )
                have_answer = True
                yield self.recorder.get_progress_answers() if self.recorder else None

            console_skill_response(
                skill_name=function_name,
                response=self.recorder.get_answer() if self.recorder else "",
                max_length=1024,
            )

            if not have_answer and self.recorder:
                self.recorder.update(
                    item=f"Calling {function_name} tool did not return proper results, need to call again.",
                    source_type=SourceType.EXPLORE,
                )
        except ToolInterrupt as e:
            if "tool" in self.context.get_all_variables().keys():
                self.context.delete_variable("tool")
            yield self.recorder.get_progress_answers() if self.recorder else None
            raise e
        except Exception as e:
            logger.error(f"Error calling tool, error type: {type(e)}")
            logger.error(f"Error details: {str(e)}")
            return_answer["think"] = (
                f"Error occurred when calling {function_name} tool, need to call again. Error message: {str(e)}"
            )
            return_answer["answer"] = (
                f"Error occurred when calling {function_name} tool, need to call again. Error message: {str(e)}"
            )

        return_answer["status"] = "completed"
        yield [return_answer]

        # Add tool response message
        tool_response, metadata = self._process_skill_result_with_hook(function_name)

        # Extract tool_call_id
        tool_call_id = self._extract_tool_call_id()
        if not tool_call_id:
            tool_call_id = f"call_{function_name}_{self.times}"

            self.strategy.append_tool_response_message(
                self.context, tool_call_id, str(tool_response), metadata
            )

    async def _handle_new_tool_call(self, no_cache: bool):
        """Handling New Tool Calls"""
        # Regenerate system message to include dynamically loaded tools
        current_skillkit = self.get_skillkit()
        updated_system_message = self.strategy.make_system_message(
            skillkit=current_skillkit,
            system_prompt=self.system_prompt,
            tools_format=self.tools_format,
        )

        # Update SYSTEM bucket
        if len(updated_system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                updated_system_message,
                message_role=MessageRole.SYSTEM,
            )

        # Get LLM message
        llm_messages = self.context.context_manager.to_dph_messages()

        # Always re-fetch skillkit to include dynamically loaded tools
        llm_params = self.strategy.get_llm_params(
            messages=llm_messages,
            model=self.model,
            skillkit=current_skillkit,  # Use current skillkit
            tool_choice=getattr(self, "tool_choice", None),  # Consistent with V2: use only when explicitly specified by user
            no_cache=no_cache,
        )
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
            # Initialize stream_item
            stream_item = StreamItem()
            async for stream_item in self.llm_chat_stream(
                llm_params=llm_params,
                recorder=self.recorder,
                content=self.content if self.content else "",
                early_stop_on_tool_call=True,
                on_stream_chunk=on_chunk,
            ):
                # Use strategy's has_valid_tool_call method, compatible with both prompt and tool_call modes
                if not self.strategy.has_valid_tool_call(stream_item, self.context):
                    yield self.recorder.get_progress_answers() if self.recorder else None
                else:
                    # In tool_call mode, wait for complete tool call (including arguments)
                    # In prompt mode, detect_tool_call will parse complete arguments
                    tool_call = self.strategy.detect_tool_call(stream_item, self.context)
                    if tool_call is not None:
                        # For tool_call mode, ensure arguments are completely received
                        if self.mode == "tool_call" and not stream_item.has_complete_tool_call():
                            # tool_name received but tool_args not complete yet, continue waiting
                            yield self.recorder.get_progress_answers() if self.recorder else None
                            continue
                        
                        logger.debug(
                            f"explore[{self.output_var}] find skill call [{tool_call.name}]"
                        )
                        break
        except Exception as e:
            # Handle UserInterrupt: save partial output to context before re-raising
            # This ensures the LLM's partial output is preserved in the scratchpad,
            # so when resuming, the LLM can see what it was outputting before interruption.
            from dolphin.core.common.exceptions import UserInterrupt
            if isinstance(e, UserInterrupt):
                if stream_item and stream_item.answer:
                    self._append_assistant_message(stream_item.answer)
                    logger.debug(f"UserInterrupt: saved partial output ({len(stream_item.answer)} chars) to context")
            raise
        finally:
            if renderer:
                renderer.stop()

        console("\n", verbose=self.context.is_verbose())

        if self.times >= MAX_SKILL_CALL_TIMES:
            self.context.warn(
                f"max skill call times reached {MAX_SKILL_CALL_TIMES} times, answer[{stream_item.to_dict()}]"
            )
        else:
            self.times += 1

        if self.recorder:
            self.recorder.update(
                item=stream_item,
                raw_output=stream_item.answer,
                is_completed=True,
                source_type=SourceType.EXPLORE,
            )
        yield self.recorder.get_progress_answers() if self.recorder else None

        # Use strategy's detect_tool_call method to detect tool calls, compatible with both prompt and tool_call modes
        tool_call = self.strategy.detect_tool_call(stream_item, self.context)
        
        if tool_call is None:
            # No tool call detected: stop immediately
            # If there is pending content, merge before adding
            if self.pending_content:
                # Merge pending content and current content
                combined_content = self.pending_content + "\n\n" + stream_item.answer
                self._append_assistant_message(combined_content)
                self.context.debug(f"Added after merging pending content, total length: {len(combined_content)}")
                self.pending_content = None
            else:
                # No pending content, add current answer directly
                self._append_assistant_message(stream_item.answer)
                self.context.debug(f"no valid skill call, answer[{stream_item.answer}]")

            # Stop exploration immediately
            self.should_stop_exploration = True
            self.context.debug("No tool call, stopping exploration")
            return

        # Reset no-tool-call count (because this round has tool call)
        self.no_tool_call_count = 0

        # If there is pending content, merge with current tool_call
        if self.pending_content:
            self.context.debug(f"Detected pending content, will merge with tool_call")
            # Merge pending content with current tool_call content
            if stream_item.answer:
                stream_item.answer = self.pending_content + "\n" + stream_item.answer
            else:
                stream_item.answer = self.pending_content
            self.pending_content = None

        # Deduplicator
        deduplicator = self.strategy.get_deduplicator()

        # Check for duplicate calls
        skill_call_for_dedup = (tool_call.name, tool_call.arguments)
        if not deduplicator.is_duplicate(skill_call_for_dedup):
            # Add tool call message
            self.strategy.append_tool_call_message(
                self.context, stream_item, tool_call
            )
            deduplicator.add(skill_call_for_dedup)

            async for ret in self._execute_tool_call(stream_item, tool_call):
                yield ret
        else:
            await self._handle_duplicate_tool_call(tool_call, stream_item)

    async def _execute_tool_call(self, stream_item: StreamItem, tool_call: ToolCall):
        """Execute tool call"""
        # Checkpoint: Check user interrupt before executing tool
        self.context.check_user_interrupt()

        intervention_tmp_key = "intervention_explore_block_vars"

        # Ensure tool response message will definitely be added
        tool_response_added = False
        answer_content = ""

        try:
            intervention_vars = {
                "prompt": self.context.get_messages().get_messages_as_dict(),
                "tool_name": tool_call.name,
                "cur_llm_stream_answer": stream_item.answer,
                "all_answer": stream_item.answer,
            }

            self.context.set_variable(intervention_tmp_key, intervention_vars)

            async for resp in self.skill_run(
                source_type=SourceType.EXPLORE,
                skill_name=tool_call.name,
                skill_params_json=tool_call.arguments or {},
            ):
                yield self.recorder.get_progress_answers() if self.recorder else None

            # Update deduplicator results
            deduplicator = self.strategy.get_deduplicator()
            deduplicator.add(
                (tool_call.name, tool_call.arguments),
                self.recorder.get_answer() if self.recorder else None,
            )

            # Add tool response message
            tool_response, metadata = self._process_skill_result_with_hook(tool_call.name)

            answer_content = (
                tool_response
                if tool_response is not None
                and not CognitiveSkillkit.is_cognitive_skill(tool_call.name)
                else ""
            )

            if len(answer_content) > self.context.get_max_answer_len():
                answer_content = answer_content[
                    : self.context.get_max_answer_len()
                ] + "(... too long, truncated to {})".format(
                    self.context.get_max_answer_len()
                )

            self.strategy.append_tool_response_message(
                self.context, tool_call.id, answer_content, metadata
            )

        except ToolInterrupt as e:
            self._handle_tool_interrupt(e, tool_call.name)
            # Add tool response even if interrupted (maintain context integrity)
            answer_content = f"Tool execution interrupted: {str(e)}"
            self.strategy.append_tool_response_message(
                self.context, tool_call.id, answer_content, metadata
            )
            tool_response_added = True
            raise e
        except Exception as e:
            self._handle_tool_execution_error(e, tool_call.name)
            # Add tool response even if error occurs (maintain context integrity)
            answer_content = f"Tool execution error: {str(e)}"
            self.strategy.append_tool_response_message(
                self.context, tool_call.id, answer_content
            )
            tool_response_added = True
        finally:
            # Ensure tool response message is always added (core fix)
            if not tool_response_added:
                self.strategy.append_tool_response_message(
                    self.context, tool_call.id, answer_content
                )

    async def _handle_duplicate_tool_call(self, tool_call: ToolCall, stream_item: StreamItem):
        """Handling Duplicate Tool Calls"""
        message = get_msg_duplicate_skill_call()
        self._append_assistant_message(message)

        if self.recorder:
            self.recorder.update(
                item={"answer": message, "think": ""},
                raw_output=stream_item.answer,
                source_type=SourceType.EXPLORE,
            )

        deduplicator = self.strategy.get_deduplicator()
        self.context.warn(
            f"Duplicate skill call detected: {deduplicator.get_call_key((tool_call.name, tool_call.arguments))}"
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
        1. Maximum number of tool calls has been reached
        2. Number of repeated tool calls exceeds limit
        3. No tool call occurred once
        """
        # 1. If the maximum number of calls has been reached, stop exploring
        if self.times >= MAX_SKILL_CALL_TIMES:
            return False

        # 2. Check for repeated calls exceeding the limit
        deduplicator = self.strategy.get_deduplicator()
        if hasattr(deduplicator, 'skillcalls') and deduplicator.skillcalls:
            recent_calls = list(deduplicator.skillcalls.values())
            if (
                recent_calls
                and max(recent_calls) >= DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT
            ):
                return False

        # 3. Stop exploring when there is no tool call.
        if self.should_stop_exploration:
            return False

        return True

    def _process_skill_result_with_hook(self, skill_name: str) -> tuple[str | None, dict]:
        """Handle skill results using skillkit_hook"""
        # Get skill object
        skill = self.context.get_skill(skill_name)
        if not skill:
            skill = SystemFunctions.getSkill(skill_name)

        # Get the last stage as reference
        last_stage = self.recorder.getProgress().get_last_stage()
        reference = last_stage.get_raw_output() if last_stage else None

        # Process results using skillkit_hook (handles dynamic tools automatically)
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

    def _append_assistant_message(self, content: str):
        """Add assistant message to context"""
        scrapted_messages = Messages()
        scrapted_messages.add_message(content, MessageRole.ASSISTANT)
        self.context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scrapted_messages,
        )

    def _extract_tool_call_id(self) -> str | None:
        """Extract tool call ID from message"""
        messages_with_calls = self.context.get_messages_with_tool_calls()
        if messages_with_calls:
            last_call_msg = messages_with_calls[-1]
            if last_call_msg.tool_calls:
                return last_call_msg.tool_calls[0].get("id")
        return None

    # ===================== continue_exploration method =====================

    async def continue_exploration(
        self,
        model: Optional[str] = None,
        use_history: bool = True,
        preserve_context: bool = False,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Continue exploring based on the existing context (multi-turn dialogue scenario)

        This method reuses the message history, variable pool, and other states from the current context,
        and executes a new exploration session to handle the user's subsequent input.

        Args:
            model: Name of the model; if None, use the model used in the previous session from context
            use_history: Whether to use historical messages, default is True
            preserve_context: If True, skip reset_for_block() to preserve scratchpad content.
                            Use this when resuming from UserInterrupt to keep the conversation context.
            **kwargs: Additional parameters

        Yields:
            Execution results
        """
        # continue_exploration bypasses BasicCodeBlock.execute(), so we must align with
        # normal block semantics by resetting transient buckets before assembling messages.
        # Otherwise, previous round SCRATCHPAD/SYSTEM/QUERY may leak and crowd out SYSTEM/HISTORY.
        # Exception: when preserve_context=True (e.g., resuming from UserInterrupt), skip reset
        if self.context and not preserve_context:
            self.context.reset_for_block()

        # 1. Resolve parameters
        self.history = use_history
        self.model = self._resolve_model(model)
        self.content = self._resolve_content(kwargs)
        self.output_var = kwargs.get("output_var", "result")
        self.assign_type = kwargs.get("assign_type", "->")

        # 2. Resolve inherited configurations
        self._resolve_skills(kwargs)
        self._resolve_mode(kwargs)
        self._resolve_system_prompt(kwargs)
        self._apply_deduplicator_config(kwargs)

        # 3. Reset exploration status
        self.times = 0
        self.should_stop_exploration = False
        self.no_tool_call_count = 0
        self.pending_content = None  # Reset pending content

        # 4. Setup buckets
        self._setup_system_bucket()
        if self.content and self.context.context_manager:
            if preserve_context:
                # When preserving context (e.g., resuming from UserInterrupt),
                # add user input to SCRATCHPAD to maintain correct temporal order.
                # The bucket order is: SYSTEM -> HISTORY -> QUERY -> SCRATCHPAD
                # If we add to QUERY, user's new input would appear BEFORE the
                # previous conversation in SCRATCHPAD, which is wrong.
                self.context.add_user_message(
                    self.content,
                    bucket=BuildInBucket.SCRATCHPAD.value
                )
            else:
                # Use add_user_message instead of add_bucket to properly handle
                # multimodal content (List[Dict]). add_user_message correctly wraps
                # content in a Messages object which supports multimodal content.
                self.context.add_user_message(
                    self.content,
                    bucket=BuildInBucket.QUERY.value
                )

        history_messages = self._make_history_messages()
        if (
            self.history
            and history_messages is not None
            and not history_messages.empty()
            and self.context.context_manager
        ):
            self.context.set_history_bucket(history_messages)

        # 5. Run exploration loop
        while True:
            async for ret in self._explore_once(no_cache=True):
                yield ret

            if not self._should_continue_explore():
                break

        # 6. Cleanup
        self._update_history_and_cleanup()

    # ===================== continue_exploration helpers =====================

    def _resolve_model(self, model: Optional[str]) -> str:
        """Resolve model name from parameter or context."""
        if model:
            return model
        return self.context.get_last_model_name() or ""

    def _resolve_content(self, kwargs: dict):
        """Resolve user content from kwargs or context.
        
        Returns:
            str for plain text, or List[Dict] for multimodal content
        """
        user_content = kwargs.get("content", "")
        
        # If content is already provided (either str or multimodal List[Dict]), return it
        if user_content:
            return user_content
        # Otherwise try to get from context bucket
        if self.context.context_manager:
            bucket = self.context.context_manager.state.buckets.get(
                BuildInBucket.QUERY.value
            )
            if bucket:
                user_content = bucket._get_content_text()
        return user_content

    def _resolve_skills(self, kwargs: dict):
        """Resolve skills configuration from kwargs or inherit from context."""
        if "skills" in kwargs:
            self.skills = kwargs["skills"]
        elif "tools" in kwargs:
            self.skills = kwargs["tools"]
        else:
            last_skills = self.context.get_last_skills()
            if last_skills is not None:
                self.skills = last_skills

        if getattr(self, "skills", None):
            self.context.set_last_skills(self.skills)

    def _resolve_mode(self, kwargs: dict):
        """Resolve exploration mode from kwargs or inherit from context."""
        if "mode" in kwargs:
            new_mode = kwargs["mode"]
            if new_mode in ["prompt", "tool_call"] and new_mode != self.mode:
                self.mode = new_mode
                self.strategy = self._create_strategy()
        else:
            last_mode = self.context.get_last_explore_mode()
            if last_mode is not None and last_mode != self.mode:
                self.mode = last_mode
                self.strategy = self._create_strategy()

        if getattr(self, "mode", None):
            self.context.set_last_explore_mode(self.mode)

    def _resolve_system_prompt(self, kwargs: dict):
        """Resolve system prompt from kwargs or inherit from context."""
        if "system_prompt" in kwargs:
            self.system_prompt = kwargs.get("system_prompt") or ""
        else:
            last_system_prompt = self.context.get_last_system_prompt()
            if (not getattr(self, "system_prompt", None)) and last_system_prompt:
                self.system_prompt = last_system_prompt

        if getattr(self, "system_prompt", None):
            self.context.set_last_system_prompt(self.system_prompt)

    def _setup_system_bucket(self):
        """Rebuild system bucket for multi-turn exploration (reset_for_block may have cleared it)."""
        skillkit = self.get_skillkit()
        system_message = self.strategy.make_system_message(
            skillkit=skillkit,
            system_prompt=getattr(self, "system_prompt", "") or "",
            tools_format=self.tools_format,
        )

        if len(system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                system_message,
                message_role=MessageRole.SYSTEM,
            )

    def _apply_deduplicator_config(self, kwargs: dict):
        """Apply skill deduplicator configuration."""
        if "enable_skill_deduplicator" in kwargs:
            self.enable_skill_deduplicator = kwargs["enable_skill_deduplicator"]
        if hasattr(self, "enable_skill_deduplicator"):
            self.strategy.set_deduplicator_enabled(self.enable_skill_deduplicator)
