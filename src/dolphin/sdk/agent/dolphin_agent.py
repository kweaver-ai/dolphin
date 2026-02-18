"""Dolphin Language Agent - A concrete implementation based on BaseAgent"""

import os
import re
import inspect
from dolphin.core.context_engineer.config.settings import BuildInBucket
import aiofiles
import logging
from typing import AsyncGenerator, Any, Dict, Optional
import asyncio

from dolphin.core.context.context import Context
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.common.object_type import ObjectTypeFactory
from dolphin.core.parser.parser import Parser

from dolphin.core.agent.base_agent import BaseAgent
from dolphin.core.agent.agent_state import AgentState, PauseType
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.coroutine.step_result import StepResult
import dolphin.core.executor.dolphin_executor as dolphin_language
from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.common.exceptions import DolphinAgentException, UserInterrupt
from dolphin.sdk.agent.dolphin_agent_snapshot import DolphinAgentSnapshot


class DolphinAgent(BaseAgent):
    """DPH file execution Agent implementation based on BaseAgent
        Supports full lifecycle management and state control
    """

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        skillkit: Optional[Skillkit] = None,
        variables: Optional[Dict[str, Any]] = None,
        global_skills=None,
        file_path: Optional[str] = None,
        content: Optional[str] = None,
        global_config: Optional[GlobalConfig] = None,
        global_config_path: str = "",
        global_types: ObjectTypeFactory = ObjectTypeFactory(),
        verbose: bool = False,
        is_cli: bool = False,
        log_level: int = logging.INFO,
        output_variables: Optional[list] = None,
    ):
        """Initialize Dolphin Agent

        Args:
            name: Agent name, automatically generated if not provided
            description: Agent description
            skillkit: Skillkit instance
            variables: Initial variables
            file_path: DPH file path (optional, mutually exclusive with content)
            content: DPH content as a string (optional, mutually exclusive with file_path)
            global_config: Global configuration
            global_config_path: Path to the global configuration file
            global_skills: Global skills
            global_types: Global type definitions
            verbose: Whether to enable verbose output mode (detailed logging)
            is_cli: Whether running in CLI mode (controls Rich/terminal beautification)
            log_level: Log level, such as logging.DEBUG, logging.INFO, etc.
            output_variables: List of variable names to return, corresponding to VariablePool variable names.
                            If specified, only these variables are returned; if empty list or None, all variables are returned
        """
        # Parameter Validation
        if file_path is None and content is None:
            raise DolphinAgentException(
                "INVALID_ARGUMENT", "必须提供 file_path 或 content 参数"
            )
        if file_path is not None and content is not None:
            raise DolphinAgentException(
                "INVALID_ARGUMENT", "不能同时提供 file_path 和 content 参数"
            )

        # Set name according to content source
        if file_path is not None:
            # File Mode
            self.content_source = "file"
            agent_name = name or os.path.splitext(os.path.basename(file_path))[0]

            # Verify file existence
            if not os.path.exists(file_path):
                raise DolphinAgentException(
                    "FILE_NOT_FOUND", f"DPH file not found: {file_path}"
                )
        else:
            # Content Mode
            self.content_source = "content"
            agent_name = name or "content_agent"

        super().__init__(
            name=agent_name, description=description, global_config=global_config
        )

        self.content = content
        self.skillkit = skillkit
        self.variables = variables
        self.file_path = file_path
        
        # Enable auto-interrupt for dynamically loaded tools
        # This is a temporary hack/policy at SDK layer, not in core
        self._enable_dynamic_tool_auto_interrupt = True
        self.global_config = global_config
        self.global_config_path = global_config_path
        self.global_skills = global_skills
        self.global_types = global_types
        self.verbose = verbose  # Store the verbose parameter
        self.is_cli = is_cli    # Store CLI mode flag
        self.log_level = log_level  # Storage log level parameter
        self.executor: Optional[DolphinExecutor] = None

        self.execution_context = None
        # Normalize output variable parameters to avoid sharing issues caused by mutable default arguments
        self.output_variables = output_variables or []  # Store output variable list
        self.header_info = {}  # Store parsed header information
        self.snapshot = DolphinAgentSnapshot(self)

        # Initialize components (completed in the _initialize method)

        # Set log level
        from dolphin.core.logging.logger import set_log_level

        set_log_level(self.log_level)

    async def achat(self, message = None, **kwargs) -> AsyncGenerator[Any, None]:
        """Interactive dialogue mode execution, used to continue multi-turn dialogues after the Agent is initialized and running.

        .. deprecated:: 2.1
            Use :meth:`continue_chat` instead. The achat method returns raw progress data
            without wrapping, which is inconsistent with arun. The new continue_chat method
            provides a consistent API by wrapping results in _progress list.

        Args:
            message: The message input by the user. Can be:
                     - str: Plain text message
                     - List[Dict]: Multimodal content (e.g., [{"type": "text", "text": "..."}, {"type": "image_url", ...}])
                     - None: Assume the message has been added to the Context.
            **kwargs: Other parameters

        Yields:
            Execution results
        """
        import warnings
        warnings.warn(
            "achat() is deprecated and will be removed in v3.0. "
            "Use continue_chat() instead for consistent API with arun().",
            DeprecationWarning,
            stacklevel=2
        )

        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        # Pass message through kwargs to continue_exploration
        # Note: Do NOT call reset_for_block() here - continue_exploration will handle it
        # and we need to pass content via kwargs, not bucket (which would be cleared)
        if message:
            kwargs["content"] = message

        # Handled by the continue_exploration method of the executor
        # continue_exploration will automatically get the previously used model (if available) from context
        # This can reduce the coupling between DolphinAgent and internal implementation classes.
        async for result in self.executor.continue_exploration(
            **kwargs
        ):
            yield result

    async def continue_chat(
        self,
        message: str = None,
        stream_variables: bool = True,
        stream_mode: str = "full",
        **kwargs
    ) -> AsyncGenerator[Any, None]:
        """Continue multi-turn dialogue with consistent API format as arun().

        This is the recommended method for multi-turn conversations, replacing achat().
        Returns results wrapped in _progress list for consistency with arun().

        Args:
            message: The message input by the user. Can be:
                     - str: Plain text message
                     - List[Dict]: Multimodal content
                     - None: Assume the message has been added to the Context
            stream_variables: Whether to enable streaming variable output (default: True)
            stream_mode: Streaming mode:
                        - "full": Return full accumulated text (default)
                        - "delta": Return only incremental text changes
            **kwargs: Other parameters

        Yields:
            Results in the same format as arun():
            {
                '_status': 'running' | 'completed' | 'interrupted',
                '_progress': [
                    {
                        'stage': 'llm' | 'tool_call' | ...,
                        'status': 'running' | 'completed' | 'failed',
                        'answer': str,  # Full text (stream_mode='full') or delta (stream_mode='delta')
                        'delta': str,   # Only present when stream_mode='delta'
                        ...
                    }
                ],
                '_interrupt': {...}  # Only present when _status='interrupted'
            }

        Raises:
            DolphinAgentException: If EXPLORE_BLOCK_V2 flag is not disabled or agent not initialized

        Example:
            # First run
            async for result in agent.arun(query="Hello"):
                process(result)

            # Continue conversation
            async for result in agent.continue_chat(message="Continue..."):
                process(result)  # Same format as arun!
        """
        # Fail-fast check: EXPLORE_BLOCK_V2 must be disabled
        from dolphin.core import flags
        if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
            raise DolphinAgentException(
                "INVALID_FLAG_STATE",
                "continue_chat() requires EXPLORE_BLOCK_V2 flag to be disabled. "
                "Set flags.set_flag(flags.EXPLORE_BLOCK_V2, False) before using continue_chat()."
            )

        # Lazy initialization if needed
        if self.executor is None:
            await self.initialize()

        # State-aware pause semantics:
        # - Tool interrupts must be resumed via resume() first.
        # - User interrupts default to preserve context and continue as a new turn.
        if self.state == AgentState.PAUSED:
            if self._pause_type == PauseType.TOOL_INTERRUPT:
                raise DolphinAgentException(
                    "NEED_RESUME",
                    "Agent paused due to tool interrupt; call resume() before continue_chat().",
                )

            if self._pause_type == PauseType.USER_INTERRUPT:
                kwargs.setdefault("preserve_context", True)
                if message is None and self._pending_user_input:
                    message = self._pending_user_input
                # Clear the interrupt event so the next execution cycle does
                # not immediately re-trigger the interrupt guard.
                if hasattr(self, "clear_interrupt"):
                    self.clear_interrupt()

            # continue_chat serves as resume action for non-tool pause.
            self._pending_user_input = None
            self._resume_handle = None
            self._pause_type = None
            await self._change_state(AgentState.RUNNING, "Agent resumed via continue_chat()")
        elif self.state in (AgentState.COMPLETED, AgentState.INITIALIZED):
            # After arun() completes the agent is COMPLETED; after init it is
            # INITIALIZED.  Transition through INITIALIZED→RUNNING so that
            # interrupt handling (mark_user_interrupted) can legally reach PAUSED.
            # Validate parameters before state transition to avoid stuck RUNNING state.
            if stream_mode not in ("full", "delta"):
                raise DolphinAgentException(
                    "INVALID_PARAMETER",
                    f"stream_mode must be 'full' or 'delta', got '{stream_mode}'"
                )
            if self.state == AgentState.COMPLETED:
                await self._change_state(AgentState.INITIALIZED, "Reinitializing for continue_chat()")
            await self._change_state(AgentState.RUNNING, "Agent running via continue_chat()")

        # Pass message through kwargs
        if message:
            kwargs["content"] = message

        # Validate stream_mode (for PAUSED and other states that transitioned above)
        if stream_mode not in ("full", "delta"):
            raise DolphinAgentException(
                "INVALID_PARAMETER",
                f"stream_mode must be 'full' or 'delta', got '{stream_mode}'"
            )

        # Track last answer for delta calculation
        last_answer = {}

        # Direct passthrough pattern (like achat), with optional wrapping
        # This ensures streaming works correctly by yielding each result immediately
        try:
            async for result in self.executor.continue_exploration(**kwargs):
                # Interrupt: wrap in consistent format with _status="interrupted"
                if isinstance(result, dict) and result.get("status") == "interrupted":
                    interrupt_type = result.get("interrupt_type")
                    self._resume_handle = result.get("handle")
                    if interrupt_type in ("tool_confirmation", "tool_interrupt"):
                        self._pause_type = PauseType.TOOL_INTERRUPT
                        if self.state != AgentState.PAUSED:
                            await self._change_state(
                                AgentState.PAUSED, "Agent paused due to tool interrupt in continue_chat()"
                            )
                    elif interrupt_type == "user_interrupt":
                        await self.mark_user_interrupted(
                            "Agent paused due to user interrupt in continue_chat()"
                        )
                        # Clear interrupt event to avoid immediate re-trigger on next turn.
                        self.clear_interrupt()
                    else:
                        self._logger.warning("Unknown interrupt_type=%s, treating as generic pause", interrupt_type)
                        self._pause_type = None
                        if self.state != AgentState.PAUSED:
                            await self._change_state(
                                AgentState.PAUSED, "Agent interrupted in continue_chat()"
                            )
                    yield {
                        "_status": "interrupted",
                        "_progress": [],
                        "_interrupt": result  # Preserve original interrupt info
                    }
                    return

                # Streaming mode: get context variables (contains _progress)
                ctx = self.executor.context if self.executor else None
                if ctx is not None and stream_variables:
                    if self.output_variables is not None and len(self.output_variables) > 0:
                        data = ctx.get_variables_values(self.output_variables)
                    else:
                        data = ctx.get_all_variables_values()

                    # Apply delta mode if requested
                    if stream_mode == "delta" and "_progress" in data:
                        data = self._apply_delta_mode(data, last_answer)

                    # data already contains _status and _progress from context
                    yield data
                else:
                    # Non-streaming or no context: wrap raw result
                    yield {
                        "_status": "running",
                        "_progress": [result] if isinstance(result, dict) else []
                    }
        except UserInterrupt:
            self._resume_handle = None
            await self.mark_user_interrupted("Agent paused due to user interrupt in continue_chat()")
            # Clear interrupt event to avoid immediate re-trigger on next turn.
            self.clear_interrupt()
            yield {
                "_status": "interrupted",
                "_progress": [],
                "_interrupt": {
                    "status": "interrupted",
                    "interrupt_type": "user_interrupt",
                },
            }
            return

        # Final state: mark as completed
        try:
            ctx = self.executor.context if self.executor else None
            if ctx is not None:
                if self.output_variables is not None and len(self.output_variables) > 0:
                    final_data = ctx.get_variables_values(self.output_variables)
                else:
                    final_data = ctx.get_all_variables_values()

                # Explicitly mark completion status
                final_data["_status"] = "completed"

                # Apply delta mode to final data
                if stream_mode == "delta" and "_progress" in final_data:
                    final_data = self._apply_delta_mode(final_data, last_answer)

                yield final_data
        except (AttributeError, KeyError) as e:
            # Expected errors when context/variables are not fully initialized
            self._logger.debug(f"Could not get final variables in continue_chat: {e}")

    def _apply_delta_mode(self, data: dict, last_answer: dict) -> dict:
        """Apply delta mode to progress data by calculating incremental changes.

        Args:
            data: Current data with _progress list
            last_answer: Dictionary tracking last answer text per stage

        Returns:
            Modified data with delta field added to each progress item
        """
        if "_progress" not in data or not isinstance(data["_progress"], list):
            return data

        for prog in data["_progress"]:
            if not isinstance(prog, dict):
                continue

            stage = prog.get("stage", "")
            stage_id = prog.get("id", stage)  # Use ID if available
            current_answer = prog.get("answer") or ""

            # Calculate delta
            last_text = last_answer.get(stage_id, "")
            if not last_text:
                # First time: full text is delta
                delta = current_answer
            elif current_answer.startswith(last_text):
                # Normal case: extract new portion
                delta = current_answer[len(last_text):]
            else:
                # Text changed unexpectedly: reset
                delta = current_answer

            # Update tracking and add delta field
            last_answer[stage_id] = current_answer
            prog["delta"] = delta

        return data

    async def _on_initialize(self):
        """Initialize Agent component"""
        try:
            # Get content according to the source
            if self.content_source == "file" and self.file_path is not None:
                # File mode: Asynchronously read file contents to avoid blocking the event loop
                async with aiofiles.open(self.file_path, "r", encoding="utf-8") as f:
                    self.content = await f.read()
            # Content mode: Content has been set in the constructor

            # Parse and remove the header information block (such as @DESC ... @DESC)
            self._parse_header_info()

            # Create Executor
            self.executor = dolphin_language.DolphinExecutor(
                global_configpath=self.global_config_path,
                global_config=self.global_config,
                global_skills=self.global_skills,
                global_types=self.global_types,
                verbose=self.verbose,
                is_cli=self.is_cli,
            )

            await self.executor.executor_init(
                {
                    "skillkit": self.skillkit,
                    "variables": self.variables,
                }
            )

            # Register hook for dynamic tool loading (SDK-layer policy)
            # This is a temporary hack: auto-add interrupt_config to dynamic tools
            if self._enable_dynamic_tool_auto_interrupt:
                self._register_dynamic_tool_hooks()

            # Validate DPH syntax
            self._validate_syntax()

            self._logger.debug(f"Dolphin Agent '{self.name}' initialized successfully")

        except Exception as e:
            raise DolphinAgentException(
                "INIT_FAILED", f"Failed to initialize agent: {str(e)}"
            )

    def _register_dynamic_tool_hooks(self):
        """Register hooks for dynamically loaded tools (SDK-layer temporary policy)
        
        This is a TEMPORARY HACK to auto-add interrupt_config to all dynamic tools.
        
        Architecture decision:
        - Placed at SDK layer (DolphinAgent) instead of core layer (BasicCodeBlock)
        - Reduces invasiveness and keeps core clean
        - Future: Remove this method when upper business layer provides interrupt_config
        
        Working mechanism:
        - Core layer: Standard approach - applies interrupt_config if present in tool_def
        - SDK layer: Temporary policy - auto-adds interrupt_config to tool_instance
        """
        def on_dynamic_tool_loaded(tool_instance, tool_def):
            """Hook called after each dynamic tool is loaded and interrupt_config applied
            
            Args:
                tool_instance: The created tool instance (already has interrupt_config if tool_def had it)
                tool_def: The tool definition dict from _dynamic_tools
            """
            # Only add if tool doesn't already have interrupt_config
            # (i.e., not provided in tool_def)
            if not hasattr(tool_instance, 'interrupt_config'):
                tool_name = tool_def.get("name", "unknown")
                
                # TEMPORARY HACK: Auto-add interrupt_config
                # TODO: Remove this when upper layer provides interrupt_config in tool_def
                auto_interrupt_config = {
                    "requires_confirmation": True,
                    "confirmation_message": (
                        f"即将调用「{tool_name}」工具，是否确认执行？"
                    )
                }
                tool_instance.interrupt_config = auto_interrupt_config
                
                self._logger.debug(
                    f"[DolphinAgent] Auto-added interrupt protection to dynamic tool: {tool_name}"
                )
        
        # Register the hook on executor's context
        if self.executor and self.executor.context:
            self.executor.context.on_dynamic_tool_loaded = on_dynamic_tool_loaded
            self._logger.debug("[DolphinAgent] Registered dynamic tool hook (temporary policy)")
    
    def _parse_header_info(self):
        """Parse the header information block of DPH files, supporting the general @XX ... @XX format.
               同时从content中移除这些header块，避免干扰后续解析

        Examples:
            @DESC
            This is the agent description
            @DESC

                    @VERSION
            1.0.0
            @VERSION
        """
        if self.content is None:
            return

        self.header_info = {}

        # Use regular expressions to match information blocks in the format @XX ... @XX
        # Pattern: @-prefixed tags (allowing only uppercase letters, numbers, and underscores), non-greedy match until the closing tag of the same type
        pattern = r"@([A-Z][A-Z_0-9]+)\s*(.*?)\s*@\1"

        matches = re.findall(pattern, self.content, re.DOTALL)

        for tag_name, content in matches:
            # Clean up extra blank lines in the content
            clean_content = re.sub(r"\n\s*\n", "\n", content.strip())
            self.header_info[tag_name] = clean_content

        # Remove all matching header blocks from self.content
        self.content = re.sub(pattern, "", self.content, flags=re.DOTALL)

        # Clean up extra blank lines that may be generated after removing the header
        self.content = re.sub(r"\n\s*\n\s*\n", "\n\n", self.content).strip()

        # If DESC is parsed and description is not provided during construction, use the parsed DESC
        if "DESC" in self.header_info and not self.description:
            self.description = self.header_info["DESC"]

    def _validate_syntax(self):
        """Validate DPH file syntax"""
        if self.content is None:
            raise DolphinAgentException("INVALID_CONTENT", "DPH content is empty")

        is_valid, error_message = Parser.validate_syntax(self.content)
        if not is_valid:
            raise DolphinAgentException("SYNTAX_ERROR", error_message)

    async def _on_execute(self, **kwargs) -> AsyncGenerator[Any, None]:
        """Execute DPH file content

        Args:
            **kwargs: Additional parameters passed to the executor

        Yields:
            Execution results
        """
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        try:
            # Initialize executor parameters
            if kwargs:
                init_params = {"variables": kwargs}
                await self.executor.executor_init(init_params)

            # Set the current Agent
            self.executor.context.set_cur_agent(self)

            # Execute DPH content
            async for result in self.executor.run(
                content=self.content, output_variables=self.output_variables, **kwargs
            ):
                yield result

        except Exception as e:
            self._logger.error(f"Execution error: {e}")
            raise DolphinAgentException("EXECUTION_ERROR", str(e))

    async def _on_pause(self):
        """Pause Agent execution"""
        self._logger.debug(f"Agent '{self.name}' paused")
        # Here you can add cleanup logic when paused
        # For example: save the current execution state, release resources, etc.

    async def _on_resume(self):
        """Restore Agent Execution"""
        self._logger.debug(f"Agent '{self.name}' resumed")
        # Here you can add logic for recovery.
        # For example: restoring execution state, re-initializing resources, etc.

    async def _on_terminate(self):
        """Terminate Agent execution"""
        self._logger.debug(f"Agent '{self.name}' terminated")
        # Clean up resources
        if self.executor:
            try:
                self.executor.shutdown()
            except Exception as e:
                self._logger.warning(f"Error during executor shutdown: {e}")

    # === Coroutine Series Method Implementation ===
    async def _on_start_coroutine(self, **kwargs):
        """Start coroutine execution"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        try:
            # Initialize executor parameters
            if kwargs:
                init_params = {"variables": kwargs}
                await self.executor.executor_init(init_params)

            # Set the current Agent
            self.executor.context.set_cur_agent(self)

            # Start coroutine execution (compatible with MagicMock scenarios)
            start_result = self.executor.start_coroutine(content=self.content, **kwargs)
            frame = (
                await start_result
                if inspect.isawaitable(start_result)
                else start_result
            )

            # Inject interrupt event into executor context for user interrupt detection
            # This enables Context.check_user_interrupt() to work correctly
            if self.executor and self.executor.context:
                self.executor.context.set_interrupt_event(self._interrupt_event)
                self._logger.debug("Interrupt event injected into executor context")

            return frame

        except Exception as e:
            self._logger.error(f"Start coroutine error: {e}")
            raise DolphinAgentException("START_COROUTINE_FAILED", str(e)) from e

    async def _on_step_coroutine(self) -> StepResult:
        """Execute one step"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        if self._current_frame is None:
            raise DolphinAgentException("NO_FRAME", "No execution frame available")

        try:
            # Execute one step, return StepResult
            result = await self.executor.step_coroutine(self._current_frame.frame_id)

            # Return StepResult directly, the caller can use is_interrupted/is_completed/is_running to determine.
            return result

        except Exception as e:
            self._logger.error(f"Step coroutine error: {e}")
            raise DolphinAgentException("STEP_COROUTINE_FAILED", str(e)) from e

    async def _on_run_coroutine(self):
        """Continuously execute until the tool interrupts or completes (fast mode)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        if self._current_frame is None:
            raise DolphinAgentException("NO_FRAME", "No execution frame available")

        try:
            # If a progress callback exists (for streaming variable output), pass it to the executor.
            progress_cb = getattr(self, "_progress_callback", None)
            result = await self.executor.run_coroutine(
                self._current_frame.frame_id, progress_callback=progress_cb
            )

            # Return StepResult directly, the caller can use is_interrupted/is_completed to determine.
            return result

        except Exception as e:
            self._logger.error(f"Run coroutine error: {e}")
            raise DolphinAgentException("RUN_COROUTINE_FAILED", str(e)) from e

    async def arun(
        self,
        run_mode: bool = True,
        stream_variables: bool = True,
        stream_mode: str = "full",
        **kwargs,
    ) -> AsyncGenerator[Any, None]:
        """Run the Agent asynchronously.

                - The default behavior is consistent with BaseAgent.arun, producing a run status/completion/interrupt structure.
                - When stream_variables=True, execute in fast mode (run_mode=True) to avoid snapshot overhead at each step,
                  while streaming current context variables at each block's progress point (filtered as needed if output_variables is set).

                Important: When stream_variables=True, fast mode is enforced (equivalent to run_mode=True),
                the run_mode passed by the caller will be ignored and only effective in this branch.

        Args:
            run_mode: Whether to run in fast mode (default: True)
            stream_variables: Whether to enable streaming variable output (default: True)
            stream_mode: Streaming mode (default: "full"):
                        - "full": Return full accumulated text
                        - "delta": Return only incremental text changes (framework calculates automatically)
            **kwargs: Additional runtime variables

        Note: Tool interruption handling when stream_variables=True:
                1. During streaming variable views (dict), if a tool interruption occurs, an interruption information dictionary is produced:
                   {"status": "interrupted", "handle": ResumeHandle}
                2. The Agent state becomes PAUSED
                3. The caller must handle the tool interruption, then call agent.resume(updates) to resume execution
                4. After resuming, arun(stream_variables=True) can be called again to continue streaming
                5. On normal completion, the final variable snapshot is produced, which may be identical to the penultimate output (ensuring no final state is missed)

                Queue strategy:
                - Use a bounded queue (maxsize=32) + discard old, keep new to prevent memory bloat (balancing high-frequency updates and memory usage)
                - The caller always receives the latest variable state
                - If execution is too fast, some intermediate states may be skipped (only the latest is retained)

        Example:
            async for data in agent.arun(stream_variables=True):
                        if isinstance(data, dict) and data.get("status") == "interrupted":
                            # Handle tool interruption
                    handle = data["handle"]
                    updates = handle_tool_interrupt(handle)
                    await agent.resume(updates)
                    # Continue execution
                    async for data in agent.arun(stream_variables=True):
                                process_variable_data(data)
                else:
                            # Normal variable view data
                    process_variable_data(data)
        """
        if not stream_variables:
            # Keep the original arun semantics
            async for item in super().arun(run_mode=run_mode, **kwargs):
                yield item
            return

        # Validate stream_mode
        if stream_mode not in ("full", "delta"):
            raise DolphinAgentException(
                "INVALID_PARAMETER",
                f"stream_mode must be 'full' or 'delta', got '{stream_mode}'"
            )

        # Streaming variable pattern: capture execution progress via progress_callback, while using fast mode to avoid frequent snapshots
        if self.executor is None:
            # If not yet initialized, trigger initialization (lazy loading)
            await self.initialize()

        # Queue for callbacks (bounded, discard old, keep new, to avoid memory bloat)
        # maxsize=32 can buffer high-frequency data for 1-2 seconds, balancing memory usage and data integrity
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        # Used to pass tool interrupt information
        interrupt_info = None
        # Track last answer for delta calculation
        last_answer = {} if stream_mode == "delta" else None

        def _queue_put_latest(payload):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # Drop old items
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    # Ignore this update in extreme cases to avoid blocking
                    pass

        def _progress_cb(_resp):
            # Self-check: Only deliver when the current callback is still this closure, to avoid incorrect delivery caused by concurrent overwriting.
            if getattr(self, "_progress_callback", None) is not _progress_cb:
                return
            try:
                ctx = self.executor.context if self.executor else None
                if ctx is None:
                    return
                if self.output_variables is not None and len(self.output_variables) > 0:
                    data = ctx.get_variables_values(self.output_variables)
                else:
                    data = ctx.get_all_variables_values()

                # Apply delta mode if requested
                if stream_mode == "delta" and last_answer is not None:
                    data = self._apply_delta_mode(data, last_answer)

                _queue_put_latest(data)
            except Exception:
                # Callback exceptions must not affect main execution
                pass

        # Install callback
        setattr(self, "_progress_callback", _progress_cb)

        async def _drive_base_arun():
            nonlocal interrupt_info
            # Reuse base class state machine/event: Fast mode execution
            try:
                async for item in super(DolphinAgent, self).arun(
                    run_mode=True, **kwargs
                ):
                    # Check if it is an interruption (unified status, type in interrupt_type field)
                    if isinstance(item, dict) and item.get("status") == "interrupted":
                        interrupt_info = item
                        # Do not push to the queue, output uniformly by the outer layer (to avoid duplication)
                        return  # Stop execution and let the outer layer pass interrupt information
            finally:
                # Clean up callbacks to avoid leakage into subsequent runs
                if hasattr(self, "_progress_callback"):
                    delattr(self, "_progress_callback")

        # Start Execution
        runner = asyncio.create_task(_drive_base_arun())

        try:
            # Consume the progress queue until execution ends
            while True:
                try:
                    # 优先从队列Get数据，使用较短的超时避免runner完成后检测延迟过大
                    # Timeout values balance responsiveness and CPU efficiency: even if the item interval > 0.1s, it will still be fetched in the next loop iteration.
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield item
                except asyncio.TimeoutError:
                    # Check runner status only after timeout to avoid race conditions
                    if runner.done():
                        # Clear the remaining data in the queue, using exception handling instead of empty() checks
                        while True:
                            try:
                                yield queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        break
        finally:
            # Ensure backend tasks are completed
            if not runner.done():
                runner.cancel()
            try:
                # Always await, regardless of whether done or not, to re-raise any possible exceptions.
                await runner
            except asyncio.CancelledError:
                # Active cancellation is expected behavior
                pass
            except Exception:
                # Log and re-raise the exception to inform the caller that an error has occurred.
                self._logger.exception(
                    "Background execution failed in stream_variables mode"
                )
                raise

        # At the end:
        if interrupt_info is not None:
            # If there is tool interruption information, ensure the caller definitely obtains it again (even with queue consumption race conditions)
            yield interrupt_info
        else:
            # Complete normally by capturing one final frame of variable snapshots to avoid missing the last state.
            try:
                ctx = self.executor.context if self.executor else None
                if ctx is not None:
                    if (
                        self.output_variables is not None
                        and len(self.output_variables) > 0
                    ):
                        final_data = ctx.get_variables_values(self.output_variables)
                    else:
                        final_data = ctx.get_all_variables_values()

                    # Apply delta mode to final data
                    if stream_mode == "delta" and last_answer is not None:
                        final_data = self._apply_delta_mode(final_data, last_answer)

                    yield final_data
            except (AttributeError, KeyError) as e:
                # Expected errors when context/variables are not fully initialized
                self._logger.debug(f"Could not get final variables in arun: {e}")

    async def _on_pause_coroutine(self):
        """Pause coroutine"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        if self._current_frame is None:
            raise DolphinAgentException("NO_FRAME", "No execution frame available")

        try:
            handle = await self.executor.pause_coroutine(self._current_frame.frame_id)
            return handle

        except Exception as e:
            self._logger.error(f"Pause coroutine error: {e}")
            raise DolphinAgentException("PAUSE_COROUTINE_FAILED", str(e))

    async def _on_resume_coroutine(self, updates: Optional[Dict[str, Any]] = None):
        """Resume coroutine"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        if self._resume_handle is None:
            raise DolphinAgentException(
                "NO_RESUME_HANDLE", "No resume handle available"
            )

        try:
            frame = await self.executor.resume_coroutine(self._resume_handle, updates)
            return frame

        except Exception as e:
            self._logger.error(f"Resume coroutine error: {e}")
            raise DolphinAgentException("RESUME_COROUTINE_FAILED", str(e))

    async def _on_terminate_coroutine(self):
        """Terminate coroutine"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        if self._current_frame is None:
            # No frame executed, return directly
            return

        try:
            await self.executor.terminate_coroutine(self._current_frame.frame_id)

        except Exception as e:
            self._logger.error(f"Terminate coroutine error: {e}")
            raise DolphinAgentException("TERMINATE_COROUTINE_FAILED", str(e))

    def get_content_source(self) -> str:
        """Get content source type"""
        return getattr(self, "content_source", "unknown")

    def get_file_path(self) -> Optional[str]:
        """Get DPH file path"""
        return self.file_path

    def get_execution_trace(self, title=None):
        """Get Execution Trace"""
        if self.executor:
            return self.executor.get_execution_trace(title)
        else:
            return "Execution trace not available: Agent not initialized"

    # Backward compatibility: retain old method names
    def get_profile(self, title=None):
        """[Deprecated] Please use get_execution_trace() instead"""
        import warnings
        warnings.warn("get_profile() 已废弃，请使用 get_execution_trace()", DeprecationWarning, stacklevel=2)
        return self.get_execution_trace(title)

    def get_content(self) -> Optional[str]:
        """Get Agent content"""
        return self.content

    def get_header_info(self) -> Dict[str, str]:
        """Get all parsed header information

        Returns:
            A dictionary containing all header information, for example {'DESC': '...', 'VERSION': '...'}
        """
        return self.header_info.copy()

    def get_desc(self) -> str:
        """Get Agent description (from @DESC header or constructor parameters)

        Returns:
            Agent description string
        """
        return self.description or self.header_info.get("DESC", "")

    async def append_incremental_message(self, payload: dict):
        """Append an incremental message to the current coroutine (using prefix cache)

        Args:
            payload: Status or event information, such as {"event_type": "...", "content": "...", "metadata": {...}}
        """
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        await self.executor.append_incremental_message(payload)

    async def append_round_message(self, round_info: dict):
        """Compatible with old names: Please use append_incremental_message instead."""
        await self.append_incremental_message(round_info)

    def set_context(self, context: Context):
        """Set the Agent's context"""
        if self.executor:
            self.executor.set_context(context)

    def sync_variables(self, context: Context):
        """Synchronize variables to the specified context"""
        if self.executor:
            # Synchronize the variables of the current execution context to the target context
            context.sync_variables(self.executor.context)

    def get_context(self) -> Optional[Context]:
        """Get the execution context of the Agent"""
        if self.executor is None:
            return None
        return self.executor.context

    def set_user_id(self, user_id: str):
        """Set user ID"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.set_user_id(user_id)

    def set_session_id(self, session_id: str):
        """Set session ID"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.set_session_id(session_id)

    def add_user_message(self, content: str, bucket: str = None):
        """Add user message"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.add_user_message(content, bucket=bucket)

    def get_messages(self):
        """Get message list"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_messages()

    def get_skillkit(self, skillNames: Optional[list] = None):
        """Get Skill Package"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_skillkit(skillNames)

    def get_config(self):
        """Get configuration"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_config()

    def save_trajectory(self, agent_name: str = None, force_save: bool = False, trajectory_path: str = None):
        """Save execution trace"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.save_trajectory(
            agent_name=agent_name or self.name,
            force_save=force_save,
            trajectory_path=trajectory_path
        )

    def get_snapshot_analysis(self, title=None, format='markdown', options=None):
        """Get snapshot analysis"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_snapshot_analysis(title=title, format=format, options=options)

    def get_all_variables(self):
        """Get all variables"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_all_variables()

    def get_var_value(self, name, default_value=None):
        """Get variable value"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.get_var_value(name, default_value)

    def add_bucket(self, bucket_name: str, content, priority: float = 1.0, allocated_tokens: Optional[int] = None, message_role=None):
        """Add context buckets"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.add_bucket(
            bucket_name=bucket_name,
            content=content,
            priority=priority,
            allocated_tokens=allocated_tokens,
            message_role=message_role
        )

    def set_trajectorypath(self, trajectorypath: str):
        """Set trajectory path"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.trajectorypath = trajectorypath

    def set_agent_name(self, agent_name: str):
        """Set agent name (in context)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.agent_name = agent_name

    def set_cur_agent(self, agent):
        """Set the current agent (in context)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.set_cur_agent(agent)

    def set_skills(self, skillkit):
        """Set Skill Pack"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        self.executor.context.set_skills(skillkit)

    def get_skillkit_raw(self):
        """Get the original skillkit object (for scenarios where direct access to skillkit is required)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.skillkit

    def get_context_messages_dict(self):
        """Get the messages dictionary of context (for debugging)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.messages

    def get_context_manager(self):
        """Get context_manager (for debugging)"""
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return self.executor.context.context_manager

    async def start_coroutine(self, **kwargs):
        """Public method: explicitly start coroutine execution

                Used in scenarios where manual control over coroutine startup is required
        """
        # Keep consistent with the state machine of BaseAgent
        if self.state == AgentState.CREATED:
            await self.initialize()

        # If the previous one has been completed, clean up and return to INITIALIZED
        if self.state == AgentState.COMPLETED:
            try:
                if self._current_frame is not None:
                    await self._on_terminate_coroutine()
            except Exception:
                pass
            self._current_frame = None
            self._resume_handle = None
            self._pause_type = None
            await self._change_state(
                AgentState.INITIALIZED, "Agent reinitialized for new run"
            )

        # Explicit start is only allowed in the INITIALIZED state; explicit start in RUNNING/PAUSED states would create ambiguity, hence rejected.
        if self.state != AgentState.INITIALIZED:
            raise DolphinAgentException(
                "INVALID_STATE",
                f"start_coroutine() not allowed from state {self.state.value}",
            )

        # Clean up control signals and switch to RUNNING
        self._terminate_event.clear()
        self._pause_event.set()
        await self._change_state(
            AgentState.RUNNING, "Agent started via start_coroutine()"
        )

        # Start Execution Frame
        self._current_frame = await self._on_start_coroutine(**kwargs)
        return self._current_frame

    async def resume_coroutine(self, handle, updates=None):
        """Resume coroutine execution (resume from tool interruption)

        Args:
            handle: ResumeHandle resume handle
            updates: variable updates to inject

        Returns:
            ExecutionFrame: the execution frame after resumption
        """
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        # Explicit resume API is only allowed when in PAUSED state
        if self.state != AgentState.PAUSED:
            raise DolphinAgentException(
                "INVALID_STATE",
                f"resume_coroutine() not allowed from state {self.state.value}",
            )

        frame = await self.executor.resume_coroutine(handle, updates)
        self._current_frame = frame
        self._resume_handle = None

        # Keep the same behavior as BaseAgent.resume(): resume the pause, switch to RUNNING, and trigger on_resume
        self._pause_event.set()
        await self._change_state(
            AgentState.RUNNING, "Agent resumed via resume_coroutine()"
        )
        await self._on_resume()
        return frame

    def get_intervention_data(self) -> dict:
        """Get interrupt data (such as tool call parameters)

        Returns:
            dict: Interrupt-related data
        """
        if self.executor is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")

        return self.executor.get_intervention_data()

    def get_execution_info(self) -> Dict[str, Any]:
        """Get execution information"""
        info = {
            "name": self.name,
            "description": self.description,
            "state": self.state.value,
            "execution_mode": "coroutine",  # Explicitly identified as coroutine mode
            "content_source": self.get_content_source(),
        }

        if self._current_frame is not None:
            info["frame_id"] = self._current_frame.frame_id
            info["frame_status"] = self._current_frame.status.value
            info["block_pointer"] = self._current_frame.block_pointer

        if self._resume_handle is not None:
            info["has_resume_handle"] = True

        return info

    def __str__(self) -> str:
        if self.get_content_source() == "file":
            return f"DolphinAgent(name={self.name}, file={self.file_path}, state={self.state.value})"
        else:
            if self.content is None:
                return f"DolphinAgent(name={self.name}, state={self.state.value})"

            content_preview = (
                self.content[:50] + "..." if len(self.content) > 50 else self.content
            )
            return f"DolphinAgent(name={self.name}, content_source={self.get_content_source()}, content_preview='{content_preview}', state={self.state.value})"
