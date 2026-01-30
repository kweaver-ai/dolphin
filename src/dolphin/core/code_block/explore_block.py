"""ExploreBlock Code Block Implementation

Supports two tool calling modes:
- prompt mode: call tools in the prompt using =># format
- tool_call mode (default): use LLM's native tool_call capability

Control which mode to use via the mode parameter:
- mode="prompt": use PromptStrategy
- mode="tool_call" (default): use ToolCallStrategy

Design document: docs/design/architecture/explore_block_merge.md
"""

from __future__ import annotations

from dolphin.core.task_registry import PlanExecMode

import asyncio
import json
import traceback
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from dolphin.core.code_block.basic_code_block import BasicCodeBlock

# Hook imports
from dolphin.core.hook import (
    HookConfig,
    OnStopContext,
    HookResult,
    HookDispatcher,
    HookValidationError,
    parse_hook_config,
)
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
    MAX_PLAN_SILENT_ROUNDS,
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
from dolphin.core.skill.skill_matcher import SkillMatcher
from dolphin.core import flags

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

        # State Variables
        self.times = 0
        self.should_stop_exploration = False
        self.no_tool_call_count = 0  # Count consecutive rounds without tool calls
        self.pending_content = None  # Store content without tool_call for merging
        
        # Session-level tool call batch counter for stable ID generation
        # Incremented each time LLM returns tool calls (per batch, not per tool)
        self.session_tool_call_counter = 0

        # Plan mode: guard against excessive "silent" rounds where the agent does not make
        # meaningful progress on the active plan (e.g., repeatedly calling unrelated tools).
        self.plan_silent_max_rounds: int = MAX_PLAN_SILENT_ROUNDS
        self._plan_silent_rounds: int = 0
        self._plan_last_signature: Optional[tuple] = None
        self._last_tool_name: Optional[str] = None
        self._current_round_tools: List[str] = []  # Track all tools called in current round

        # Hook-based verify attributes
        self.on_stop: Optional[HookConfig] = None
        self.current_attempt: int = 0
        self.hook_history: List[Dict[str, Any]] = []
        self._last_hook_result: Optional[HookResult] = None

    def _create_strategy(self) -> ExploreStrategy:
        """Create the corresponding strategy instance according to mode."""
        if self.mode == "prompt":
            return PromptStrategy()
        else:  # tool_call
            return ToolCallStrategy(tools_format=self.tools_format)

    def parse_block_content(self, content: str, category=None, replace_variables=True):
        """Override the parent class method to update mode and strategy after parsing DPH syntax.

                According to the design document docs/design/architecture/explore_block_merge.md:
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

        # Handle exec_mode for plan orchestration
        exec_mode_param = self.params.get("exec_mode")
        if exec_mode_param:
            # PlanExecMode.from_str handles validation and mapping (seq/para/etc.)
            self.params["exec_mode"] = PlanExecMode.from_str(str(exec_mode_param))

        # Optional: override plan silent rounds limit via DPH params.
        silent_max = self.params.get("plan_silent_max_rounds")
        if silent_max is not None:
            try:
                silent_max_int = int(silent_max)
                if silent_max_int < 0:
                    raise ValueError("plan_silent_max_rounds must be >= 0")
                self.plan_silent_max_rounds = silent_max_int
            except Exception as e:
                raise ValueError(f"Invalid plan_silent_max_rounds: {silent_max}") from e

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

        # Parse on_stop hook configuration from params
        self._parse_hook_config()

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
            # Inject context to skillkits that support it
            self._inject_context_to_skillkits()

        # Save the current mode configuration to context for inheritance in multi-turn conversations.
        if getattr(self, "mode", None):
            self.context.set_last_explore_mode(self.mode)

        # Build initial message
        self._make_init_messages()

        async for ret in self._execute_main():
            yield ret

        # Update history and cleanup buckets after execution
        self._update_history_and_cleanup()

    def _parse_hook_config(self) -> None:
        """Parse on_stop hook configuration from params."""
        on_stop_value = self.params.get("on_stop", None)
        if on_stop_value is not None:
            try:
                self.on_stop = parse_hook_config(on_stop_value)
                logger.debug(f"Parsed on_stop config: {self.on_stop}")
            except HookValidationError as e:
                logger.error(f"Invalid on_stop configuration: {e}")
                raise

    async def _execute_main(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Unified execution entry point (standard execution + on_stop retry verification)."""
        if not self.on_stop:
            async for ret in self._stream_exploration_with_assignment():
                yield ret
            return

        max_attempts = self.on_stop.max_retries + 1
        last_output: Optional[Dict[str, Any]] = None
        last_hook_result: Optional[HookResult] = None

        for attempt_idx in range(max_attempts):
            self.current_attempt = attempt_idx + 1

            if attempt_idx > 0:
                self._reset_for_retry()

            logger.info(
                f"Hook verify attempt {self.current_attempt}/{max_attempts}"
            )

            async for ret in self._stream_exploration_with_assignment():
                last_output = ret
                yield ret

            last_hook_result = await self._trigger_on_stop_hook(last_output or {})
            self._last_hook_result = last_hook_result
            self._record_hook_attempt(self.current_attempt, last_output or {}, last_hook_result)

            if last_hook_result.passed:
                logger.info(
                    f"Hook verify passed with score: {last_hook_result.score}"
                )
                yield self._build_hook_enriched_result(
                    last_output or {},
                    last_hook_result,
                    verified=True,
                )
                return

            if (not last_hook_result.retry) or (attempt_idx >= max_attempts - 1):
                logger.info(
                    f"Hook verify stopped: retry={last_hook_result.retry}, "
                    f"attempt={attempt_idx+1}/{max_attempts}"
                )
                break

            if last_hook_result.feedback:
                self._inject_feedback(
                    last_hook_result.feedback,
                    last_hook_result.score,
                    attempt_idx + 1,
                )
                logger.debug(
                    "Injected feedback for retry: "
                    f"{last_hook_result.feedback[:100]}..."
                )

        assert last_hook_result is not None
        logger.info(
            f"Hook verify failed after {self.current_attempt} attempts, "
            f"final score: {last_hook_result.score}"
        )
        yield self._build_hook_enriched_result(
            last_output or {},
            last_hook_result,
            verified=False,
        )

    def _reset_for_retry(self) -> None:
        """Reset exploration state before retry (preserving message history)."""
        self.should_stop_exploration = False
        self.times = 0
        self.no_tool_call_count = 0
        self.strategy.reset_deduplicator()

    async def _stream_exploration_with_assignment(
        self,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute exploration with streaming yield, maintaining assign_type output logic."""
        has_add = False if self.assign_type == ">>" else None

        while True:
            self.context.check_user_interrupt()

            async for ret in self._explore_once(no_cache=True):
                has_add = self._write_output_var(ret, has_add)
                yield ret

            if not await self._should_continue_explore():
                break

    def _write_output_var(
        self,
        ret: Dict[str, Any],
        has_add: Optional[bool],
    ) -> Optional[bool]:
        """Write to output_var based on assign_type and return updated has_add flag."""
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
            self.context.set_var_output(self.output_var, ret, SourceType.EXPLORE)
        return has_add

    async def _trigger_on_stop_hook(self, output: Dict[str, Any]) -> HookResult:
        """Trigger the on_stop hook and return result.

        This method builds the OnStopContext from the exploration output and
        dispatches it to the configured hook handler (expression or agent).

        Note: Agent-based verification (@verifier) is not yet supported in v1.
        Currently only expression-based handlers are functional. When agent
        support is added, the runtime parameter will be properly initialized.

        Args:
            output: The exploration output containing answer, think, etc.

        Returns:
            HookResult from hook execution, or a degraded result on timeout/error.
        """
        # Build hook context from output
        context = OnStopContext(
            attempt=self.current_attempt,
            stage="explore",
            answer=self._extract_answer(output),
            think=self._extract_think(output),
            steps=self.times,
            tool_calls=self._collect_tool_calls(),
        )

        # Dispatch hook with timeout protection
        dispatcher = HookDispatcher(
            config=self.on_stop,
            context=context,
            variable_pool=self.context.variable_pool,
            # TODO: Pass runtime when agent-based verification is implemented.
            # Agent verification requires runtime to load and execute .dph files.
            runtime=None,
        )

        # Apply timeout protection to prevent hook execution from blocking indefinitely
        # Use agent_timeout from HookConfig (default: 60s). Keep backward-compatible fallback.
        timeout_seconds = getattr(self.on_stop, "agent_timeout", 60)

        try:
            return await asyncio.wait_for(
                dispatcher.dispatch(),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Hook dispatch timeout after {timeout_seconds}s, "
                f"returning degraded result"
            )
            return HookResult(
                score=0.0,
                passed=False,
                feedback=None,
                retry=False,
                breakdown=None,
                error=f"Hook execution timeout after {timeout_seconds}s",
                error_type="timeout",
                execution_status="timeout",
            )

    def _extract_answer(self, output: Optional[Dict[str, Any]]) -> str:
        """Extract answer from output dict."""
        if not output:
            return ""
        if isinstance(output, dict):
            return output.get("answer", "") or output.get("block_answer", "")
        if isinstance(output, list) and len(output) > 0:
            last = output[-1]
            if isinstance(last, dict):
                return last.get("answer", "") or last.get("block_answer", "")
        return str(output) if output else ""

    def _extract_think(self, output: Optional[Dict[str, Any]]) -> str:
        """Extract thinking process from output dict."""
        if not output:
            return ""
        if isinstance(output, dict):
            return output.get("think", "")
        if isinstance(output, list) and len(output) > 0:
            last = output[-1]
            if isinstance(last, dict):
                return last.get("think", "")
        return ""

    def _collect_tool_calls(self) -> List[Dict[str, Any]]:
        """Collect tool calls made during exploration."""
        return self.strategy.get_tool_call_history()

    def _record_hook_attempt(
        self,
        attempt: int,
        output: Dict[str, Any],
        hook_result: HookResult
    ) -> None:
        """Record hook attempt to history for trajectory tracking."""
        record = {
            "attempt": attempt,
            "timestamp": datetime.now().isoformat(),
            "score": hook_result.score,
            "passed": hook_result.passed,
            "feedback": hook_result.feedback,
            "retry": hook_result.retry,
        }
        if hook_result.breakdown:
            record["breakdown"] = hook_result.breakdown
        if hook_result.error:
            record["error"] = hook_result.error
            record["error_type"] = hook_result.error_type

        self.hook_history.append(record)

    def _inject_feedback(self, feedback: str, score: float, attempt: int) -> None:
        """Inject feedback as user message to scratchpad.

        Args:
            feedback: Feedback message from hook
            score: Current score
            attempt: Current attempt number
        """
        formatted = f"""[Verification Failed - Please Improve]
Score: {score:.2f} / Target: {self.on_stop.threshold:.2f}
Attempt: {attempt}

Feedback:
{feedback}

Please reconsider your approach and improve your answer based on the feedback above.
"""
        # Add feedback as user message to scratchpad
        feedback_messages = Messages()
        feedback_messages.add_message(formatted, MessageRole.USER)
        self.context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            feedback_messages,
        )

    def _build_hook_enriched_result(
        self,
        output: Dict[str, Any],
        hook_result: HookResult,
        verified: bool
    ) -> Dict[str, Any]:
        """Build result enriched with hook information.

        Args:
            output: Original exploration output
            hook_result: Last hook result
            verified: Whether verification passed

        Returns:
            Enriched result dict
        """
        result = output.copy() if isinstance(output, dict) else {"answer": output}

        # Add hook-related fields
        result["score"] = hook_result.score
        result["passed"] = verified
        result["attempts"] = self.current_attempt
        result["hook_history"] = self.hook_history.copy()

        if hook_result.feedback:
            result["feedback"] = hook_result.feedback

        if hook_result.error:
            result["verification_error"] = hook_result.error
            result["verification_status"] = hook_result.execution_status
        else:
            result["verification_status"] = "success"

        return result

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
            f"explore[{self.output_var}] messages[{self.context.get_messages().str_summary()}] "
            f"length[{self.context.get_messages().length()}]"
        )

        # Reset tool tracking at the start of each round to prevent stale state
        # This ensures used_plan_tool detection is accurate in plan silent rounds guard
        self._last_tool_name = None
        self._current_round_tools = []  # Clear tools from previous round

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
        has_intervention = intervention_tmp_key in self.context.get_all_variables().keys()
        has_tool = "tool" in self.context.get_all_variables().keys()
        return has_intervention and has_tool

    async def _handle_resumed_tool_call(self):
        """Tools for handling interrupt recovery calls """
        intervention_tmp_key = "intervention_explore_block_vars"

        # Get the content of saved temporary variables
        intervention_vars = self.context.get_var_value(intervention_tmp_key)
        self.context.delete_variable(intervention_tmp_key)

        # Restore complete message context to context_manager buckets
        saved_messages = intervention_vars.get("prompt")
        if saved_messages is not None:
            from dolphin.core.common.enums import MessageRole
            
            # *** FIX: Filter out messages that are already in other buckets ***
            # To avoid duplication, only restore messages generated during the conversation:
            # - SYSTEM messages are already in SYSTEM bucket (from initial execute)
            # - USER messages are already in QUERY/HISTORY buckets (initial query and history)
            # - We only need to restore ASSISTANT and TOOL messages (conversation progress)
            filtered_messages = [
                msg for msg in saved_messages 
                if msg.get("role") in [MessageRole.ASSISTANT.value, MessageRole.TOOL.value]
            ]
            
            msgs = Messages()
            msgs.extend_plain_messages(filtered_messages)
            # Use set_messages_batch to restore to context_manager buckets
            # This ensures messages are available when to_dph_messages() is called
            self.context.set_messages_batch(msgs, bucket=BuildInBucket.SCRATCHPAD.value)

        input_dict = self.context.get_var_value("tool")
        function_name = input_dict["tool_name"]
        raw_tool_args = input_dict["tool_args"]
        function_params_json = {arg["key"]: arg["value"] for arg in raw_tool_args}
        
        # Get saved stage_id for resume
        saved_stage_id = intervention_vars.get("stage_id")
        
        # *** FIX: Update the last tool_call message with modified parameters ***
        # This ensures LLM sees the actual parameters used, not the original ones
        messages = self.context.get_messages()
        if messages and len(messages.get_messages()) > 0:
            last_message = messages.get_messages()[-1]
            # Check if last message is an assistant message with tool_calls
            if (hasattr(last_message, 'role') and last_message.role == "assistant" and 
                hasattr(last_message, 'tool_calls') and last_message.tool_calls):
                # Find the matching tool_call
                for tool_call in last_message.tool_calls:
                    if hasattr(tool_call, 'function') and tool_call.function.name == function_name:
                        # Update the arguments with modified parameters
                        import json
                        tool_call.function.arguments = json.dumps(function_params_json, ensure_ascii=False)

        if self.recorder:
            self.recorder.update(
                stage=TypeStage.SKILL,
                source_type=SourceType.EXPLORE,
                skill_name=function_name,
                skill_type=self.context.get_skill_type(function_name),
                skill_args=function_params_json,
            )
        
        # *** Handle skip action ***
        skip_tool = self.context.get_var_value("__skip_tool__")
        skip_message = self.context.get_var_value("__skip_message__")
        
        # Clean up skip flags
        if skip_tool:
            self.context.delete_variable("__skip_tool__")
        if skip_message:
            self.context.delete_variable("__skip_message__")
        
        self.context.delete_variable("tool")

        return_answer = {}
        
        # If user chose to skip, don't execute the tool
        if skip_tool:
            # Generate friendly skip message
            params_str = ", ".join([f"{k}={v}" for k, v in function_params_json.items()])
            default_skip_msg = f"Tool '{function_name}' was skipped by user"
            if skip_message:
                skip_response = f"[SKIPPED] {skip_message}"
            else:
                skip_response = f"[SKIPPED] {default_skip_msg} (parameters: {params_str})"
            
            return_answer["answer"] = skip_response
            return_answer["think"] = skip_response
            return_answer["status"] = "completed"
            
            if self.recorder:
                self.recorder.update(
                    item={"answer": skip_response, "block_answer": skip_response},
                    stage=TypeStage.SKILL,
                    source_type=SourceType.EXPLORE,
                    skill_name=function_name,
                    skill_type=self.context.get_skill_type(function_name),
                    skill_args=function_params_json,
                )
            
            yield [return_answer]
            
            # Add tool response message with skip indicator
            tool_call_id = self._extract_tool_call_id()
            if not tool_call_id:
                tool_call_id = f"call_{function_name}_{self.times}"
            
            self.strategy.append_tool_response_message(
                self.context, tool_call_id, skip_response, metadata={"skipped": True}
            )
            return
        
        # Normal execution (not skipped)
        try:
            props = {"intervention": False, "saved_stage_id": saved_stage_id}
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
        """Handling New Tool Calls

        Supports both single and multiple tool calls based on the
        ENABLE_PARALLEL_TOOL_CALLS feature flag.
        """
        # Use current counter value; will only increment if tool calls detected
        current_counter = self.session_tool_call_counter

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
                session_counter=current_counter,  # Pass counter for stable ID generation
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

        # Detect tool calls based on feature flag
        if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
            tool_calls = self.strategy.detect_tool_calls(stream_item, self.context)
        else:
            single = self.strategy.detect_tool_call(stream_item, self.context)
            tool_calls = [single] if single else []
        
        if not tool_calls:
            # No tool call detected: terminate normally
            # Note: Plan mode continuation logic is handled in _should_continue_explore()
            # which checks has_active_plan() and may inject guidance messages if needed.

            # Normal termination
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

            # If plan mode is active, do NOT stop immediately.
            # Instead, keep exploration running so the agent can poll progress
            # (e.g., via _check_progress / _wait) until tasks reach terminal states.
            if hasattr(self.context, "has_active_plan") and await self.context.has_active_plan():
                self.should_stop_exploration = False
                self.context.debug("No tool call, but plan is active; continuing exploration")
                # Avoid tight looping while waiting for running tasks to make progress.
                # This small backoff gives subtasks time to update their status.
                await asyncio.sleep(0.2)
            else:
                self.should_stop_exploration = True
                self.context.debug("No tool call, stopping exploration")
            return

        # Reset no-tool-call count (because this round has tool call)
        self.no_tool_call_count = 0

        # Increment session counter only when tool calls are actually detected
        # This ensures stable ID generation without gaps
        self.session_tool_call_counter += 1

        # If there is pending content, merge with current tool_call
        if self.pending_content:
            self.context.debug(f"Detected pending content, will merge with tool_call")
            # Merge pending content with current tool_call content
            if stream_item.answer:
                stream_item.answer = self.pending_content + "\n" + stream_item.answer
            else:
                stream_item.answer = self.pending_content
            self.pending_content = None

        # Log detected tool calls (use info level for significant multi-tool events)
        if len(tool_calls) > 1:
            logger.info(
                f"explore[{self.output_var}] detected {len(tool_calls)} tool calls: "
                f"{[tc.name for tc in tool_calls]}"
            )

        # Add tool calls message and execute
        #
        # Execution path selection:
        # - Multiple tool calls (flag enabled + len > 1): Use new multi-tool-call path
        #   with append_tool_calls_message() and _execute_tool_calls_sequential()
        # - Single tool call (or flag disabled): Use existing single-tool-call path
        #   for maximum backward compatibility, even when flag is enabled but only
        #   one tool call is returned by LLM
        if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS) and len(tool_calls) > 1:
            # Multiple tool calls: use new methods
            self.strategy.append_tool_calls_message(
                self.context, stream_item, tool_calls
            )
            async for ret in self._execute_tool_calls_sequential(stream_item, tool_calls):
                yield ret
        else:
            # Single tool call (or flag disabled): use existing methods for backward compatibility
            tool_call = tool_calls[0]
            
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
        self._last_tool_name = tool_call.name
        # Track all tools in current round for accurate plan silent rounds detection
        self._current_round_tools.append(tool_call.name)

        intervention_tmp_key = "intervention_explore_block_vars"

        # Ensure tool response message will definitely be added
        tool_response_added = False
        answer_content = ""
        metadata = None

        try:
            # Save intervention vars (stage_id will be filled by skill_run after creating the stage)
            intervention_vars = {
                "prompt": self.context.get_messages().get_messages_as_dict(),
                "tool_name": tool_call.name,
                "cur_llm_stream_answer": stream_item.answer,
                "all_answer": stream_item.answer,
                "stage_id": None,  # Will be updated by skill_run() after stage creation
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
            tool_response_added = True

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

    async def _execute_tool_calls_sequential(
        self, 
        stream_item: StreamItem, 
        tool_calls: List[ToolCall]
    ):
        """Sequentially execute multiple tool calls (by index order).

        Note: "parallel" in OpenAI terminology means the model decides multiple tool
        calls in one turn, not that Dolphin executes them concurrently. This method
        executes tool calls one after another in index order.
        
        Error Handling Strategy (based on OpenAI best practices):
        - Non-critical failures: Continue with remaining tools, log errors
        - ToolInterrupt: Propagate immediately (critical user or system interrupt)
        - Malformed arguments: Skip the tool call with error response, continue others
        
        This approach provides graceful degradation while maintaining context integrity.
        Each tool's response (success or error) is added to context for LLM visibility.
        
        Args:
            stream_item: The streaming response item containing the tool calls
            tool_calls: List of ToolCall objects to execute
            
        Yields:
            Progress updates from each tool execution
        """
        # Track execution statistics for debugging
        total_calls = len(tool_calls)
        successful_calls = 0
        failed_calls = 0
        deduplicator = self.strategy.get_deduplicator()
        
        for i, tool_call in enumerate(tool_calls):
            logger.debug(f"Executing tool call {i+1}/{total_calls}: {tool_call.name}")

            # Skip tool calls with unparseable JSON arguments
            # (arguments is None when JSON parsing failed during streaming)
            if tool_call.arguments is None:
                failed_calls += 1
                self.context.error(
                    f"Tool call {tool_call.name} (id={tool_call.id}) skipped: "
                    f"JSON arguments failed to parse."
                )
                # Add error response to maintain context integrity
                # This allows LLM to see the failure and potentially retry
                self.strategy.append_tool_response_message(
                    self.context,
                    tool_call.id,
                    f"Error: Failed to parse JSON arguments for tool {tool_call.name}",
                    metadata={"error": True}
                )
                continue
            
            # Deduplicate to avoid repeated executions (side effects / cost).
            skill_call_for_dedup = (tool_call.name, tool_call.arguments)
            if deduplicator.is_duplicate(skill_call_for_dedup):
                failed_calls += 1
                self.context.warn(
                    f"Duplicate tool call skipped: {deduplicator.get_call_key(skill_call_for_dedup)}"
                )
                self.strategy.append_tool_response_message(
                    self.context,
                    tool_call.id,
                    f"Skipped duplicate tool call: {tool_call.name}",
                    metadata={"duplicate": True},
                )
                continue
            deduplicator.add(skill_call_for_dedup)

            # Execute the tool call
            try:
                async for ret in self._execute_tool_call(stream_item, tool_call):
                    yield ret
                successful_calls += 1
            except ToolInterrupt as e:
                # ToolInterrupt is critical - propagate immediately
                # (e.g., user cancellation, system limit reached)
                logger.info(
                    f"Tool execution interrupted at {i+1}/{total_calls}, "
                    f"completed: {successful_calls}, failed: {failed_calls}"
                )
                raise e
            except Exception as e:
                # Non-critical failure: log and continue with remaining tools
                # Response message is already added in _execute_tool_call's exception handler
                failed_calls += 1
                self.context.error(
                    f"Tool call {tool_call.name} failed: {e}, continuing with remaining tools"
                )
        
        # Log execution summary for debugging
        if failed_calls > 0:
            logger.warning(
                f"Multiple tool calls completed with errors: "
                f"{successful_calls}/{total_calls} successful, {failed_calls} failed"
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
        self.context.info(f"Tool interrupt in call {tool_name} tool")
        if "※tool" in self.context.get_all_variables().keys():
            self.context.delete_variable("※tool")

    def _handle_tool_execution_error(self, e: Exception, tool_name: str):
        """Handling tool execution errors"""
        error_trace = traceback.format_exc()
        self.context.error(
            f"error in call {tool_name} tool, error type: {type(e)}, error info: {str(e)}, error trace: {error_trace}"
        )

    async def _should_continue_explore(self) -> bool:
        """Check whether to continue the next exploration.

        Termination conditions (Early Return pattern):
        1. Maximum number of tool calls has been reached
        2. Plan mode has special continuation logic
        3. Number of repeated tool calls exceeds limit
        4. No tool call occurred once
        """
        # 1. Early return: max skill calls reached
        if self.times >= MAX_SKILL_CALL_TIMES:
            return False

        # 2. Plan mode has special logic - delegate to separate method
        if hasattr(self.context, "has_active_plan") and await self.context.has_active_plan():
            return await self._should_continue_explore_in_plan_mode()

        # 3. Early return: repeated calls exceeding limit
        if self._has_exceeded_duplicate_limit():
            return False

        # 4. Early return: no tool call
        if self.should_stop_exploration:
            return False

        return True

    async def _should_continue_explore_in_plan_mode(self) -> bool:
        """Check whether to continue exploration in plan mode.

        Plan mode has special continuation logic:
        - Must continue if tasks are active (unless max attempts reached)
        - Tracks progress via TaskRegistry signature
        - Guards against silent rounds (no progress for too long)
        - Prevents infinite loops when agent stops without progress

        Returns:
            True if exploration should continue, False otherwise
        """
        from dolphin.core.common.constants import PLAN_ORCHESTRATION_TOOLS

        # Check if current round used any plan orchestration tool
        used_plan_tool = self._used_plan_tool_this_round()

        # Check for actual task progress and get current signature
        registry = getattr(self.context, "task_registry", None)
        has_progress, current_signature = await self._check_plan_progress_with_signature(registry)

        # Early return: agent stopped without progress or plan tool usage
        if self.should_stop_exploration:
            if not has_progress and not used_plan_tool:
                logger.warning(
                    "Plan mode: Agent stopped without task progress or plan tool usage. "
                    "Terminating to prevent infinite loop."
                )
                return False

            if not has_progress and self._plan_silent_rounds >= 2:
                logger.warning(
                    f"Plan mode: Agent stopped with plan tool but no progress for "
                    f"{self._plan_silent_rounds} rounds. Terminating to prevent infinite loop."
                )
                return False

        # Update silent rounds tracking and check limit (also updates signature)
        self._update_plan_silent_rounds(current_signature, has_progress, used_plan_tool)

        # Early return: no progress and agent wants to stop
        if self.should_stop_exploration and not has_progress:
            logger.warning(
                "Plan mode: Stopping - no tool calls and no task progress. "
                "Prevents infinite loops from repeated responses."
            )
            return False

        return True

    def _used_plan_tool_this_round(self) -> bool:
        """Check if any plan orchestration tool was used in current round."""
        from dolphin.core.common.constants import PLAN_ORCHESTRATION_TOOLS

        if not self._current_round_tools:
            return False

        return any(
            tool_name in PLAN_ORCHESTRATION_TOOLS
            for tool_name in self._current_round_tools
        )

    async def _check_plan_progress_with_signature(self, registry) -> tuple[bool, tuple]:
        """Check if tasks have made progress since last round.

        Args:
            registry: TaskRegistry instance

        Returns:
            Tuple of (has_progress, current_signature)
        """
        if registry is None:
            return False, ()

        signature = await registry.get_progress_signature()
        has_progress = (
            self._plan_last_signature is None
            or signature != self._plan_last_signature
        )
        return has_progress, signature

    def _update_plan_silent_rounds(
        self, current_signature: tuple, has_progress: bool, used_plan_tool: bool
    ) -> None:
        """Update silent rounds counter and check threshold.

        Silent rounds are rounds where:
        - No task status progress AND
        - No plan orchestration tools used

        Args:
            current_signature: Current task progress signature
            has_progress: Whether progress was detected this round
            used_plan_tool: Whether plan orchestration tool was used

        Raises:
            ToolInterrupt: If silent rounds exceed threshold
        """
        if not self.plan_silent_max_rounds or self.plan_silent_max_rounds <= 0:
            return

        # Reset or increment silent rounds counter
        if has_progress or used_plan_tool:
            self._plan_silent_rounds = 0
        else:
            self._plan_silent_rounds += 1

        # Update last signature for next round comparison
        self._plan_last_signature = current_signature

        if self._plan_silent_rounds >= self.plan_silent_max_rounds:
            raise ToolInterrupt(
                "Plan mode terminated: no task status progress for too many rounds. "
                "Use _wait() or _check_progress() instead of repeatedly calling unrelated tools."
            )

    def _has_exceeded_duplicate_limit(self) -> bool:
        """Check if repeated tool calls have exceeded the limit.

        Returns:
            True if duplicate limit exceeded, False otherwise
        """
        deduplicator = self.strategy.get_deduplicator()
        if not hasattr(deduplicator, 'skillcalls') or not deduplicator.skillcalls:
            return False

        # Ignore polling-style tools
        ignored_tools = getattr(
            deduplicator, "_always_allow_duplicate_skills", set()
        ) or set()

        counts = []
        for call_key, count in deduplicator.skillcalls.items():
            tool_name = str(call_key).split(":", 1)[0]
            if tool_name in ignored_tools:
                continue
            counts.append(count)

        return counts and max(counts) >= DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT

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

            if not await self._should_continue_explore():
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
            # Inject context to skillkits that support it
            self._inject_context_to_skillkits()
    
    def _inject_context_to_skillkits(self):
        """Inject execution context to skillkits that need it (e.g., PlanSkillkit).

        This allows skillkits to access runtime context for operations like
        task registry management, variable forking, etc.
        """
        if not self.skills or not self.context:
            return

        skill_list = self._resolve_skill_list()
        if not skill_list:
            return

        self._inject_to_unique_skillkits(skill_list)

    def _resolve_skill_list(self) -> list:
        """Convert self.skills to a unified list of SkillFunction objects.

        Returns:
            List of SkillFunction objects, or empty list if conversion fails
        """
        # Case 1: Skillset object with getSkills() method
        if hasattr(self.skills, 'getSkills'):
            return self.skills.getSkills()

        # Case 2: String list (e.g., ["plan_skillkit.*", "search.*"])
        if isinstance(self.skills, list) and self.skills and isinstance(self.skills[0], str):
            return self._resolve_skill_patterns_to_functions()

        # Case 3: Already a list of SkillFunction objects
        return self.skills if isinstance(self.skills, list) else []

    def _resolve_skill_patterns_to_functions(self) -> list:
        """Resolve skill name patterns to SkillFunction objects.

        Returns:
            List of matched SkillFunction objects
        """
        current_skillkit = self.context.get_skillkit()
        if not current_skillkit:
            return []

        available_skills = current_skillkit.getSkills()
        owner_names = SkillMatcher.get_owner_skillkits(available_skills)

        # Match requested patterns against available skills
        matched_skills = []
        for pattern in self.skills:
            for skill in available_skills:
                if SkillMatcher.match_skill(skill, pattern, owner_names=owner_names):
                    matched_skills.append(skill)

        return matched_skills

    def _inject_to_unique_skillkits(self, skill_list: list):
        """Inject context to unique skillkit instances.

        Args:
            skill_list: List of SkillFunction objects

        Note:
            Uses skillkit instance ID to avoid duplicate injections
        """
        processed_skillkits = set()

        for skill in skill_list:
            skillkit = self._get_skillkit_from_skill(skill)
            if not skillkit:
                continue

            skillkit_id = id(skillkit)
            if skillkit_id in processed_skillkits:
                continue

            skillkit.setContext(self.context)
            processed_skillkits.add(skillkit_id)

    def _get_skillkit_from_skill(self, skill):
        """Extract skillkit from a skill object if it supports context injection.

        Args:
            skill: Skill object (typically SkillFunction)

        Returns:
            Skillkit instance if valid, None otherwise
        """
        if not hasattr(skill, 'owner_skillkit'):
            return None

        skillkit = skill.owner_skillkit
        if not skillkit or not hasattr(skillkit, 'setContext'):
            return None

        return skillkit

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

        # Auto-inject Plan orchestration guidance when plan_skillkit is used
        if self._has_plan_skillkit():
            plan_guidance = self._get_plan_guidance()
            if plan_guidance:
                system_message = system_message + "\n\n" + plan_guidance

        if len(system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                system_message,
                message_role=MessageRole.SYSTEM,
            )

    def _has_plan_skillkit(self) -> bool:
        """Check if plan_skillkit is included in the current skills."""
        if not hasattr(self, "skills") or not self.skills:
            return False

        # Check if skills list contains plan_skillkit pattern
        if isinstance(self.skills, list):
            for pattern in self.skills:
                if isinstance(pattern, str) and "plan_skillkit" in pattern:
                    return True

        return False

    def _get_plan_guidance(self) -> str:
        """Get auto-injected guidance for using plan orchestration tools.

        Returns:
            Multi-line guidance string for plan workflow
        """
        return """# Plan Orchestration Workflow

When using plan tools to break down complex tasks:

1. **Create Plan**: Use `_plan_tasks` to define subtasks with id, name, and prompt
2. **Monitor Progress**: Call `_check_progress` to track task status (provides next-step guidance)
3. **Retrieve Results**: When all tasks complete:
   - Use `_get_task_output()` to get all results at once (recommended)
   - Or use `_get_task_output(task_id)` for a specific task output
4. **Synthesize**: Combine all outputs into a comprehensive response for the user

Important: Your response is INCOMPLETE if you stop after tasks finish. You MUST retrieve outputs and provide a final synthesized answer."""

    def _apply_deduplicator_config(self, kwargs: dict):
        """Apply skill deduplicator configuration."""
        if "enable_skill_deduplicator" in kwargs:
            self.enable_skill_deduplicator = kwargs["enable_skill_deduplicator"]
        if hasattr(self, "enable_skill_deduplicator"):
            self.strategy.set_deduplicator_enabled(self.enable_skill_deduplicator)
