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

from dolphin.core.common.enums import (
    CategoryBlock,
    MessageRole,
    Messages,
    TypeStage,
    StreamItem,
)
from dolphin.core.common.constants import (
    MAX_TOOL_CALL_TIMES,
    MAX_PLAN_SILENT_ROUNDS,
    MAX_PLAN_POLLING_ROUNDS,
    get_msg_duplicate_tool_call,
)
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import console, console_tool_response
from dolphin.core.common.exceptions import UserInterrupt
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.context.var_output import SourceType
from dolphin.core.logging.logger import get_logger
from dolphin.lib.toolkits.cognitive_toolkit import CognitiveToolkit
from dolphin.core.code_block.explore_strategy import (
    ExploreStrategy,
    PromptStrategy,
    ToolCallStrategy,
    ToolCall,
)
from dolphin.core.code_block.tool_call_deduplicator import (
    DefaultToolCallDeduplicator,
)
from dolphin.core.tool.tool_matcher import ToolMatcher
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
        
        # Safety guard: track exploration iterations to prevent infinite loops
        self._iteration_count = 0
        self._max_iterations = MAX_TOOL_CALL_TIMES
        
        # Session-level tool call batch counter for stable ID generation
        # Incremented each time LLM returns tool calls (per batch, not per tool)
        self.session_tool_call_counter = 0

        # Plan mode: guard against excessive "silent" rounds where the agent does not make
        # meaningful progress on the active plan (e.g., repeatedly calling unrelated tools).
        self.plan_silent_max_rounds: int = MAX_PLAN_SILENT_ROUNDS
        self._plan_silent_rounds: int = 0
        self.plan_polling_max_rounds: int = MAX_PLAN_POLLING_ROUNDS
        self._plan_polling_rounds: int = 0
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

        # NOTE: plan_silent_max_rounds / plan_polling_max_rounds are intentionally
        # NOT parsed from self.params here. They use global constants
        # (MAX_PLAN_SILENT_ROUNDS / MAX_PLAN_POLLING_ROUNDS) set in __init__.
        # A previous version (commit b626047) supported per-block override via
        # DPH params, but that was removed during refactoring. If per-block
        # override is needed again, add parsing logic here.


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

        # Enable or disable the skill invocation deduplicator based on parameter configuration (enabled by default, can be disabled via enable_tool_deduplicator)
        if hasattr(self, "enable_tool_deduplicator"):
            self.strategy.set_deduplicator_enabled(self.enable_tool_deduplicator)

        # Save the current system prompt configuration to context for inheritance in multi-turn conversations.
        if getattr(self, "system_prompt", None):
            self.context.set_last_system_prompt(self.system_prompt)

        # Save the current tools configuration to context, so it can be inherited during multi-turn conversations.
        if getattr(self, "tools", None):
            self.context.set_last_tools(self.tools)
            # Inject context to toolkits that support it
            self._inject_context_to_toolkits()

        # Save the current mode configuration to context for inheritance in multi-turn conversations.
        if getattr(self, "mode", None):
            self.context.set_last_explore_mode(self.mode)

        # Build initial message
        self._make_init_messages()
        self._compress_initialized_buckets()
        self._mark_pending_turn()

        _exec_error: Optional[BaseException] = None
        try:
            async for ret in self._execute_main():
                yield ret
        except BaseException as e:
            _exec_error = e
            raise
        finally:
            # UserInterrupt is a recoverable interruption — the caller will
            # resume with preserve_context=True, so we must keep the pending
            # turn intact for the resumed round to commit.
            if not isinstance(_exec_error, UserInterrupt):
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
        """Reset exploration state including iteration counter for safety guards before retry (preserving message history)."""
        self.should_stop_exploration = False
        self.times = 0
        self.no_tool_call_count = 0
        self._iteration_count = 0
        self.strategy.reset_deduplicator()

    async def _stream_exploration_with_assignment(
        self,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute exploration with streaming yield, maintaining assign_type output logic."""
        has_add = False if self.assign_type == ">>" else None

        while self._iteration_count < self._max_iterations:
            self._iteration_count += 1
            self.context.check_user_interrupt()

            async for ret in self._explore_once(no_cache=True):
                has_add = self._write_output_var(ret, has_add)
                yield ret

            if not await self._should_continue_explore():
                break
        else:
            # Loop completed without hitting break - we hit max iterations
            logger.warning(
                f"Exploration exceeded maximum iterations ({self._max_iterations}). "
                f"Forcing termination to prevent infinite loop."
            )
            raise RuntimeError(
                f"Exploration exceeded maximum iterations limit ({self._max_iterations}). "
                f"The agent may be stuck in an infinite loop or unable to complete the task."
            )

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
        toolkit = self.get_toolkit()
        system_message = self.strategy.make_system_message(
            skillkit=toolkit,
            system_prompt=self.system_prompt,
            tools_format=self.tools_format,
            context=self.context,
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
            history_messages = self.context.get_history_messages(projected=True)
            return history_messages or Messages()
        return None

    def _compress_initialized_buckets(self, preserve_context: bool = False) -> None:
        """Compress long-lived buckets after initialization when needed."""
        if not self.context.context_manager:
            return

        if not self.context.context_manager.needs_compression():
            return

        buckets_to_compress = [BuildInBucket.HISTORY.value]
        if not preserve_context:
            buckets_to_compress.append(BuildInBucket.SCRATCHPAD.value)
        self.context.context_manager.compress_buckets(buckets_to_compress)

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
                tool_name=function_name,
                tool_type=self.context.get_tool_type(function_name),
                tool_args=function_params_json,
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
            return_answer["status"] = "skipped"
            
            if self.recorder:
                self.recorder.update(
                    item={"answer": skip_response, "block_answer": skip_response},
                    stage=TypeStage.SKILL,
                    source_type=SourceType.EXPLORE,
                    tool_name=function_name,
                    tool_type=self.context.get_tool_type(function_name),
                    tool_args=function_params_json,
                    is_completed=True,
                    is_skipped=True,
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

            async for resp in self.tool_run(
                tool_name=function_name,
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
                            tool_name=function_name,
                            tool_type=self.context.get_tool_type(function_name),
                            tool_args=function_params_json,
                        )
                have_answer = True
                yield self.recorder.get_progress_answers() if self.recorder else None

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
        tool_response, metadata = self._process_tool_result_with_hook(function_name)

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
        current_toolkit = self.get_toolkit()
        updated_system_message = self.strategy.make_system_message(
            skillkit=current_toolkit,
            system_prompt=self.system_prompt,
            tools_format=self.tools_format,
            context=self.context,
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
            skillkit=current_toolkit,  # Use current skillkit
            tool_choice=getattr(self, "tool_choice", None),  # Consistent with V2: use only when explicitly specified by user
            no_cache=no_cache,
        )
        # CLI rendering is handled by the CLI layer via output events.
        on_chunk = None

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
            # Save partial output for all streaming failures before re-raising.
            # This keeps context continuity for both user interrupts and transient
            # transport failures (e.g. peer closed connection).
            if stream_item and stream_item.answer:
                self._append_assistant_message(stream_item.answer)
                logger.debug(
                    f"Streaming failed ({type(e).__name__}): saved partial output "
                    f"({len(stream_item.answer)} chars) to context"
                )
            raise

        if not self.context.is_cli_mode():
            console("\n", verbose=self.context.is_verbose())

        if self.times >= MAX_TOOL_CALL_TIMES:
            self.context.warn(
                f"max tool call times reached {MAX_TOOL_CALL_TIMES} times, answer[{stream_item.to_dict()}]"
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
                self.context.debug(f"no valid tool call, answer[{stream_item.answer}]")

            # Always signal stop when no tool call is found.
            # The decision to continue despite this flag is made by
            # _should_continue_explore_in_plan_mode(), which checks for
            # task progress, plan tool usage, and silent round limits.
            self.should_stop_exploration = True
            if hasattr(self.context, "has_active_plan") and await self.context.has_active_plan():
                self.context.debug("No tool call with active plan; will check plan continuation logic")
                # Avoid tight looping while waiting for running tasks to make progress.
                await asyncio.sleep(0.2)
            else:
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
            tool_call_for_dedup = (tool_call.name, tool_call.arguments)
            if not deduplicator.is_duplicate(tool_call_for_dedup):
                # Add tool call message
                self.strategy.append_tool_call_message(
                    self.context, stream_item, tool_call
                )
                deduplicator.add(tool_call_for_dedup)

                async for ret in self._execute_tool_call(stream_item, tool_call):
                    yield ret
            else:
                await self._handle_duplicate_tool_call(tool_call, stream_item)

    async def _execute_tool_call(self, stream_item: StreamItem, tool_call: ToolCall):
        """Execute tool call"""
        self._last_tool_name = tool_call.name
        # Track all tools in current round for accurate plan silent rounds detection
        self._current_round_tools.append(tool_call.name)

        intervention_tmp_key = "intervention_explore_block_vars"

        # Ensure tool response message will definitely be added
        tool_response_added = False
        answer_content = ""
        metadata = None

        try:
            # Checkpoint: Check user interrupt before executing tool
            # (inside try so finally can add tool response if interrupted)
            self.context.check_user_interrupt()

            # Save intervention vars (stage_id will be filled by tool_run after creating the stage)
            intervention_vars = {
                "prompt": self.context.get_messages().get_messages_as_dict(),
                "tool_name": tool_call.name,
                "cur_llm_stream_answer": stream_item.answer,
                "all_answer": stream_item.answer,
                "stage_id": None,  # Will be updated by tool_run() after stage creation
            }

            self.context.set_variable(intervention_tmp_key, intervention_vars)

            async for resp in self.tool_run(
                source_type=SourceType.EXPLORE,
                tool_name=tool_call.name,
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
            tool_response, metadata = self._process_tool_result_with_hook(tool_call.name)

            answer_content = (
                tool_response
                if tool_response is not None
                and not CognitiveToolkit.is_cognitive_tool(tool_call.name)
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
            raise
        except UserInterrupt as e:
            # Add tool response before re-raising to prevent orphan tool_calls
            answer_content = f"Tool execution interrupted by user: {str(e)}"
            self.strategy.append_tool_response_message(
                self.context, tool_call.id, answer_content
            )
            tool_response_added = True
            raise
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
            tool_call_for_dedup = (tool_call.name, tool_call.arguments)
            if deduplicator.is_duplicate(tool_call_for_dedup):
                failed_calls += 1
                self.context.warn(
                    f"Duplicate tool call skipped: {deduplicator.get_call_key(tool_call_for_dedup)}"
                )
                self.strategy.append_tool_response_message(
                    self.context,
                    tool_call.id,
                    f"Skipped duplicate tool call: {tool_call.name}",
                    metadata={"duplicate": True},
                )
                continue
            deduplicator.add(tool_call_for_dedup)

            # Execute the tool call
            try:
                async for ret in self._execute_tool_call(stream_item, tool_call):
                    yield ret
                successful_calls += 1
            except (ToolInterrupt, UserInterrupt) as e:
                # Critical interrupt - add placeholder responses for remaining
                # unexecuted tools to prevent orphan tool_calls, then re-raise.
                reason = "user interrupted" if isinstance(e, UserInterrupt) else str(e)
                for remaining in tool_calls[i + 1:]:
                    self.strategy.append_tool_response_message(
                        self.context,
                        remaining.id,
                        f"Tool {remaining.name} not executed: {reason} "
                        f"(during {tool_call.name} [{i+1}/{total_calls}])",
                    )
                if isinstance(e, ToolInterrupt):
                    logger.info(
                        f"Tool execution interrupted at {i+1}/{total_calls}, "
                        f"completed: {successful_calls}, failed: {failed_calls}"
                    )
                raise
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
        message = get_msg_duplicate_tool_call()
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
        if self.times >= MAX_TOOL_CALL_TIMES:
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

        # Check whether tasks are still active (PENDING / RUNNING).
        # When active tasks exist we must NOT terminate early — the agent
        # needs further rounds to poll (_check_progress / _wait) until
        # those tasks reach a terminal state.  Termination in that case is
        # handled solely by the silent-rounds / polling-rounds guards in
        # _update_plan_silent_rounds().
        has_active_tasks = await self.context.has_active_plan()

        # Early return: agent stopped without progress or plan tool usage
        # Only terminate immediately when NO tasks are still active.
        if self.should_stop_exploration and not has_active_tasks:
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

        # Early return: no progress and agent wants to stop — again, only
        # when there are no active tasks left.
        if self.should_stop_exploration and not has_progress and not has_active_tasks:
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
        silent_enabled = self.plan_silent_max_rounds and self.plan_silent_max_rounds > 0
        polling_enabled = self.plan_polling_max_rounds and self.plan_polling_max_rounds > 0

        if not silent_enabled and not polling_enabled:
            return

        # Reset or increment counters.
        # - has_progress: real task state change → reset both counters
        # - used_plan_tool (no progress): agent is polling → reset silent, increment polling
        # - neither: agent is doing unrelated work → increment silent
        if has_progress:
            self._plan_silent_rounds = 0
            self._plan_polling_rounds = 0
        elif used_plan_tool:
            self._plan_silent_rounds = 0
            self._plan_polling_rounds += 1
        else:
            self._plan_silent_rounds += 1
            self._plan_polling_rounds = 0

        # Update last signature for next round comparison
        self._plan_last_signature = current_signature

        # Check polling limit: too many rounds of plan-tool usage without progress
        if polling_enabled and self._plan_polling_rounds >= self.plan_polling_max_rounds:
            raise ToolInterrupt(
                "Plan mode terminated: polling without progress for too many rounds. "
                "Tasks may be stuck or unable to complete."
            )

        if silent_enabled and self._plan_silent_rounds >= self.plan_silent_max_rounds:
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
        if not hasattr(deduplicator, 'toolcalls') or not deduplicator.toolcalls:
            return False

        # Ignore polling-style tools
        ignored_tools = getattr(
            deduplicator, "_always_allow_duplicate_tools", set()
        ) or set()

        counts = []
        for call_key, count in deduplicator.toolcalls.items():
            tool_name = str(call_key).split(":", 1)[0]
            if tool_name in ignored_tools:
                continue
            counts.append(count)

        return counts and max(counts) >= DefaultToolCallDeduplicator.MAX_DUPLICATE_COUNT

    def _process_tool_result_with_hook(self, tool_name: str) -> tuple[str | None, dict]:
        """Handle tool results using toolkit_hook"""
        # Get tool object
        tool = self.context.get_tool(tool_name)
        if not tool:
            from dolphin.lib.toolkits.system_toolkit import SystemFunctions
            tool = SystemFunctions.getTool(tool_name)

        # Get the last stage as reference
        last_stage = self.recorder.getProgress().get_last_stage()
        reference = last_stage.get_raw_output() if last_stage else None

        # Process results using toolkit_hook (handles dynamic tools automatically)
        if reference and self.toolkit_hook and self.context.has_toolkit_hook():
            # Use new hook to get context-optimized content
            content, metadata = self.toolkit_hook.on_before_send_to_context(
                reference_id=reference.reference_id,
                tool=tool,
                toolkit_name=type(tool.owner_toolkit).__name__ if tool and tool.owner_toolkit else "",
                resource_tool_path=getattr(tool, 'resource_tool_path', None) if tool else None,
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
        self._resolve_tools(kwargs)
        self._resolve_mode(kwargs)
        self._resolve_system_prompt(kwargs)
        self._apply_deduplicator_config(kwargs)

        # 3. Reset exploration status
        self.times = 0
        self.should_stop_exploration = False
        self.no_tool_call_count = 0
        self.pending_content = None  # Reset pending content
        self._iteration_count = 0

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

        self._mark_pending_turn(preserve_context=preserve_context)

        # Compress only long-lived buckets during initialization.
        # Preserve QUERY so long user inputs are not truncated before the first LLM call.
        # When preserve_context=True (interrupt resume), skip SCRATCHPAD: new user input was
        # just appended to its tail, and truncation would drop it before the LLM sees it.
        self._compress_initialized_buckets(preserve_context=preserve_context)

        # 5. Run exploration loop
        _exec_error: Optional[BaseException] = None
        try:
            while self._iteration_count < self._max_iterations:
                self._iteration_count += 1
                # Checkpoint: Check user interrupt before each exploration turn
                if self.context:
                    self.context.check_user_interrupt()

                async for ret in self._explore_once(no_cache=True):
                    yield ret

                if not await self._should_continue_explore():
                    break
            else:
                # Loop completed without hitting break - we hit max iterations
                logger.warning(
                    f"Exploration exceeded maximum iterations ({self._max_iterations}). "
                    f"Forcing termination to prevent infinite loop."
                )
                raise RuntimeError(
                    f"Exploration exceeded maximum iterations limit ({self._max_iterations}). "
                    f"The agent may be stuck in an infinite loop or unable to complete the task."
                )
        except BaseException as e:
            _exec_error = e
            raise
        finally:
            # 6. Cleanup — skip on UserInterrupt so the pending turn is
            # preserved for the resumed round (preserve_context=True).
            if not isinstance(_exec_error, UserInterrupt):
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

    def _resolve_tools(self, kwargs: dict):
        """Resolve tools configuration from kwargs or inherit from context."""
        if "tools" in kwargs:
            self.tools = kwargs["tools"]
        elif "skills" in kwargs:
            self.tools = kwargs["skills"]
        else:
            last_tools = self.context.get_last_tools()
            if last_tools is not None:
                self.tools = last_tools

        if getattr(self, "tools", None):
            self.context.set_last_tools(self.tools)
            # Inject context to toolkits that support it
            self._inject_context_to_toolkits()
    
    def _inject_context_to_toolkits(self):
        """Inject execution context to toolkits that need it (e.g., PlanToolkit)."""
        if not self.tools or not self.context:
            return

        # Resolve tools to a list of ToolFunction objects
        if hasattr(self.tools, 'getTools'):
            tool_list = self.tools.getTools()
        elif isinstance(self.tools, list) and self.tools and isinstance(self.tools[0], str):
            current_toolkit = self.context.get_toolkit()
            if not current_toolkit:
                return
            available_tools = current_toolkit.getTools()
            owner_names = ToolMatcher.get_owner_toolkits(available_tools)
            tool_list = [
                t for pattern in self.tools
                for t in available_tools
                if ToolMatcher.match_tool(t, pattern, owner_names=owner_names)
            ]
        elif isinstance(self.tools, list):
            tool_list = self.tools
        else:
            return

        # Inject context to each unique toolkit instance
        processed = set()
        for tool in tool_list:
            toolkit = getattr(tool, 'owner_toolkit', None)
            if not toolkit or not hasattr(toolkit, 'setContext'):
                continue
            if id(toolkit) not in processed:
                toolkit.setContext(self.context)
                processed.add(id(toolkit))

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
        toolkit = self.get_toolkit()
        system_message = self.strategy.make_system_message(
            skillkit=toolkit,
            system_prompt=getattr(self, "system_prompt", "") or "",
            tools_format=self.tools_format,
            context=self.context,
        )

        # Auto-inject Plan orchestration guidance when plan_toolkit is used
        if self._has_plan_toolkit():
            plan_guidance = self._get_plan_guidance()
            if plan_guidance:
                system_message = system_message + "\n\n" + plan_guidance

        if len(system_message.strip()) > 0 and self.context.context_manager:
            self.context.add_bucket(
                BuildInBucket.SYSTEM.value,
                system_message,
                message_role=MessageRole.SYSTEM,
            )

    def _has_plan_toolkit(self) -> bool:
        """Check if plan_toolkit is included in the current tools."""
        if not hasattr(self, "tools") or not self.tools:
            return False

        # Check if tools list contains plan_toolkit pattern
        if isinstance(self.tools, list):
            for pattern in self.tools:
                if isinstance(pattern, str) and "plan_toolkit" in pattern:
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
        if "enable_tool_deduplicator" in kwargs:
            self.enable_tool_deduplicator = kwargs["enable_tool_deduplicator"]
        if hasattr(self, "enable_tool_deduplicator"):
            self.strategy.set_deduplicator_enabled(self.enable_tool_deduplicator)
