"""Base Agent Class Definition

Contains the BaseAgent abstract base class and AgentEventListener event listener
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Any, Dict, Optional, Callable
from asyncio import Event, Lock
import asyncio
from datetime import datetime

from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.logging.logger import get_logger

from dolphin.core.agent.agent_state import AgentState, AgentEvent, AgentStatus, PauseType
from dolphin.core.coroutine.step_result import StepResult
from dolphin.core.common.exceptions import AgentLifecycleException


class AgentEventListener:
    """Agent Event Listener"""

    def __init__(self):
        self.listeners: Dict[AgentEvent, list] = {}
        for event in AgentEvent:
            self.listeners[event] = []
        self._logger = get_logger("agent.event_listener")

    def add_listener(self, event: AgentEvent, callback: Callable):
        """Add event listener"""
        self.listeners[event].append(callback)

    def remove_listener(self, event: AgentEvent, callback: Callable):
        """Remove event listener"""
        if callback in self.listeners[event]:
            self.listeners[event].remove(callback)

    async def emit(self, event: AgentEvent, agent: "BaseAgent", data: Any = None):
        """Trigger event (take a snapshot of the listener list to avoid being modified during traversal)"""
        # Use snapshots to avoid affecting the current traversal due to adding or removing listeners in callbacks
        for callback in list(self.listeners[event]):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(agent, event, data)
                else:
                    callback(agent, event, data)
            except Exception as e:
                self._logger.error(f"Error in event listener for {event}: {e}")


class BaseAgent(ABC):
    """Agent abstract base class, defining lifecycle management interface"""

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        global_config: Optional[GlobalConfig] = None,
    ):
        # ========================================
        # 1. Basic Properties
        # ========================================
        self.name: str = name                                    # Agent name
        self.description: str = description or ""                # Agent description
        self.global_config: Optional[GlobalConfig] = global_config  # Global configuration
        self.status = AgentStatus(state=AgentState.CREATED)      # Agent status object
        self.event_listener = AgentEventListener()               # Event listener
        self._logger = get_logger("agent")                       # Logger instance

        # ========================================
        # 2. Synchronization Primitives
        # ========================================
        # Locks
        self._state_lock = Lock()           # State change lock, ensures atomic state transitions
        self._arun_active_lock = Lock()     # arun() reentrancy protection lock

        # Events - for coroutine communication and cooperative cancellation
        self._pause_event = Event()         # Pause signal: clear=paused, set=running
        self._pause_event.set()             # Default: not paused
        self._terminate_event = Event()     # Terminate signal: set=termination requested
        self._interrupt_event = Event()     # User interrupt signal: set=user requests interrupt (new input)

        # ========================================
        # 3. Coroutine Execution State
        # ========================================
        self._current_frame = None                      # Current execution frame (ExecutionFrame)
        self._resume_handle = None                      # Resume handle (ResumeHandle), for resuming from pause point
        self._pause_type: Optional[PauseType] = None    # Pause type: MANUAL/TOOL_INTERRUPT/USER_INTERRUPT
        self._arun_active = False                       # Whether arun() is active, prevents concurrent calls

        # ========================================
        # 4. User Interrupt Related
        # ========================================
        self._pending_user_input: Optional[str] = None  # Pending user input for resume after user interrupt

        # ========================================
        # 5. State Transition Mapping
        # ========================================
        # Defines valid state transition paths for the Agent finite state machine
        self._valid_transitions = {
            AgentState.CREATED: [
                AgentState.INITIALIZED,
                AgentState.TERMINATED,
                AgentState.ERROR,
            ],
            AgentState.INITIALIZED: [
                AgentState.RUNNING,
                AgentState.TERMINATED,
                AgentState.ERROR,
            ],
            AgentState.RUNNING: [
                AgentState.PAUSED,
                AgentState.COMPLETED,
                AgentState.ERROR,
                AgentState.TERMINATED,
            ],
            AgentState.PAUSED: [AgentState.RUNNING, AgentState.TERMINATED],
            AgentState.COMPLETED: [AgentState.TERMINATED, AgentState.INITIALIZED],
            AgentState.ERROR: [AgentState.TERMINATED, AgentState.INITIALIZED],
            AgentState.TERMINATED: [],  # Terminal state, no transitions allowed
        }

    @property
    def state(self) -> AgentState:
        """Get current status"""
        return self.status.state

    async def _change_state(
        self, new_state: AgentState, message: str = "", data: Any = None
    ):
        """State change

        Note: Avoid executing callbacks while holding the lock to prevent potential deadlocks.
        """
        # First calculate the state transition and event type, then trigger the event outside the lock
        async with self._state_lock:
            if new_state not in self._valid_transitions[self.state]:
                raise AgentLifecycleException(
                    "INVALID_STATE_TRANSITION",
                    f"Cannot transition from {self.state.value} to {new_state.value}",
                )

            old_state = self.state
            self.status.state = new_state
            self.status.message = message
            self.status.data = data
            self.status.timestamp = datetime.now()

            self._logger.debug(f"State changed: {old_state.value} -> {new_state.value}")

            # Select event type (RUNNING: distinguish START from RESUME)
            event_type = None
            if new_state == AgentState.INITIALIZED:
                event_type = AgentEvent.INIT
            elif new_state == AgentState.RUNNING:
                event_type = (
                    AgentEvent.RESUME
                    if old_state == AgentState.PAUSED
                    else AgentEvent.START
                )
            elif new_state == AgentState.PAUSED:
                event_type = AgentEvent.PAUSE
            elif new_state == AgentState.COMPLETED:
                event_type = AgentEvent.COMPLETE
            elif new_state == AgentState.TERMINATED:
                event_type = AgentEvent.TERMINATE
            elif new_state == AgentState.ERROR:
                event_type = AgentEvent.ERROR

            event_payload = {
                "old_state": old_state,
                "new_state": new_state,
                "message": message,
                "data": data,
            }

        # Lock external trigger events to avoid deadlock caused by re-acquiring the lock inside callbacks.
        if event_type is not None:
            await self.event_listener.emit(event_type, self, event_payload)

    async def initialize(self) -> bool:
        """Initialize Agent"""
        try:
            await self._on_initialize()
            await self._change_state(AgentState.INITIALIZED, "Agent initialized")
            return True
        except Exception as e:
            await self._change_state(
                AgentState.ERROR, f"Initialization failed: {str(e)}"
            )
            raise AgentLifecycleException("INIT_FAILED", str(e)) from e

    @abstractmethod
    async def _on_initialize(self):
        """Initialization logic implemented by subclasses"""
        pass

    def run(self, **kwargs) -> Any:
        """Run Agent synchronously

        Note: Do not call within an asynchronous context that already has an event loop.

        Args:
            agent (Agent): The agent to run.
            messages (List[Message]): The messages to process.
            tools (Optional[List[Tool]]): The tools to use.
            max_turns (int): The maximum number of turns to run.
            stream (bool): Whether to stream the response.
            tool_choice (Optional[str]): The tool choice to use.

        Returns:
            Message: The final message.
        """
        try:
            # If a running event loop currently exists, an exception will be raised to prompt the user to use the asynchronous interface instead.
            asyncio.get_running_loop()
            raise AgentLifecycleException(
                "SYNC_RUN_IN_ASYNC",
                "run() cannot be called from an async context; use 'async for ... in arun(...)' or 'await _run_sync(...)'",
            )
        except RuntimeError:
            # No running event loop, safe to use asyncio.run
            return asyncio.run(self._run_sync(**kwargs))

    async def _run_sync(self, **kwargs) -> Any:
        """Synchronous wrapper"""
        last_result = None
        async for result in self.arun(**kwargs):
            last_result = result
        return last_result

    async def arun(self, run_mode: bool = True, **kwargs) -> AsyncGenerator[Any, None]:
        """Run the Agent asynchronously (implemented using coroutine series methods)

                This method executes step-by-step using coroutine series methods, supporting:
                - Pause/resume
                - Automatic handling of ToolInterrupt
                - State synchronization

        Args:
            run_mode (bool):
                        True  (default) uses "fast mode", running all the way to a tool interrupt or completion in one go, saving snapshots only at these two points.
                False uses "step mode", executing step by step, advancing one block per step.
        """
        # 0. Reentrant protection: Prevent multiple concurrent arun() calls
        async with self._arun_active_lock:
            if self._arun_active:
                raise AgentLifecycleException(
                    "ALREADY_RUNNING",
                    "Cannot call arun() while agent is already running",
                )
            self._arun_active = True

        try:
            # 1. Check and initialize
            if self.state not in [
                AgentState.INITIALIZED,
                AgentState.PAUSED,
                AgentState.RUNNING,
            ]:
                if self.state == AgentState.CREATED:
                    await self.initialize()
                elif self.state == AgentState.COMPLETED:
                    # Allow re-running completed agents: clean up execution-related states before state transitions.
                    try:
                        if self._current_frame is not None:
                            await self._on_terminate_coroutine()
                    except Exception:
                        # Executing frame termination failure should not block rerunning
                        pass
                    # Clean up old execution contexts
                    self._current_frame = None
                    self._resume_handle = None
                    self._pause_type = None
                    await self._change_state(
                        AgentState.INITIALIZED, "Agent reinitialized for new run"
                    )
                else:
                    # ERROR or TERMINATED states do not allow execution
                    raise AgentLifecycleException(
                        "INVALID_STATE",
                        f"Agent cannot run from state {self.state.value}",
                    )

            # 2. Restore/Continue Logic
            if self.state == AgentState.PAUSED and self._current_frame is not None:
                # For scenarios with separate pause handling for resume handles: tool interruption vs manual pause
                if self._resume_handle is not None:
                    if self._pause_type == PauseType.TOOL_INTERRUPT:
                        raise AgentLifecycleException(
                            "NEED_RESUME",
                            "Agent paused due to tool interrupt; call resume() with updates before arun()",
                        )
                    else:
                        # Manual pause or User Interrupt: auto-resume handler and continue (no external explicit resume required)
                        self._logger.debug(
                            f"Manual pause/interrupt detected in arun() (type={self._pause_type.value if self._pause_type else 'None'}); auto-resuming"
                        )
                        # Prepare updates if it was a user interrupt with pending input
                        updates = None
                        if self._pause_type == PauseType.USER_INTERRUPT and self._pending_user_input:
                            updates = {"__user_interrupt_input__": self._pending_user_input}
                            self._pending_user_input = None  # Consume it
                        
                        self._current_frame = await self._on_resume_coroutine(updates)
                        self._resume_handle = None
                        self._pause_type = None
                        self._pause_event.set()
                        await self._change_state(
                            AgentState.RUNNING, "Agent auto-resumed from manual pause"
                        )
                        await self._on_resume()
                else:
                    # When paused but no resume handle has been generated (very early pause), it can be continued directly.
                    self._pause_event.set()
                    await self._change_state(
                        AgentState.RUNNING, "Agent resumed from pause"
                    )
            elif self.state == AgentState.RUNNING and self._current_frame is not None:
                # Already running, ensure not paused
                self._pause_event.set()
            elif self.state == AgentState.RUNNING and self._current_frame is None:
                # RUNNING but no executing frame: state unsynchronized, performing self-healing restart (START event will not be triggered again)
                self._logger.error(
                    "Agent in RUNNING state but no frame; restarting coroutine without state change"
                )
                self._terminate_event.clear()
                self._pause_event.set()
                self._current_frame = await self._on_start_coroutine(**kwargs)
            else:
                # 3. Start coroutine execution
                self._terminate_event.clear()
                self._interrupt_event.clear()
                self._pause_event.set()

                await self._change_state(AgentState.RUNNING, "Agent started execution")

                # Call the subclass-implemented start method
                self._current_frame = await self._on_start_coroutine(**kwargs)

            # 4. Execution

            if run_mode:
                # Fast mode: Run once until interrupt/completion
                # Prefer the subclass-implemented _on_run_coroutine, otherwise fall back to step-by-step advancement
                if hasattr(self, "_on_run_coroutine") and callable(
                    getattr(self, "_on_run_coroutine")
                ):
                    # Respect pause/terminate signals before entering execution
                    await self._pause_event.wait()
                    if self._terminate_event.is_set():
                        await self._on_terminate_coroutine()
                        return

                    # Use wrappers to improve responsiveness to terminate
                    run_result = await self._run_with_terminate_checks()
                    # A termination signal may be triggered during execution: perform a quick backoff once more here
                    if self._terminate_event.is_set():
                        await self._on_terminate_coroutine()
                        return
                else:
                    # Back off: Step forward using step mode until an interrupt or completion is encountered (increase protection upper limit to avoid accidental infinite loops)
                    run_result = None
                    step_count = 0
                    max_steps = 1000
                    while True:
                        step_count += 1
                        if step_count > max_steps:
                            self._logger.error(
                                f"Exceeded max steps ({max_steps}) in fallback run mode"
                            )
                            raise AgentLifecycleException(
                                "MAX_STEPS_EXCEEDED",
                                f"Agent exceeded {max_steps} steps without completion or interrupt",
                            )
                        await self._pause_event.wait()
                        if self._terminate_event.is_set():
                            await self._on_terminate_coroutine()
                            return
                        step_result = await self._on_step_coroutine()
                        # New API using StepResult
                        if step_result.is_interrupted or step_result.is_completed:
                            run_result = step_result
                            break

                # Unified Processing Results
                if run_result is None:
                    self._logger.warning(
                        "run_result is None, likely due to termination during execution"
                    )
                    # Termination has already been handled in _run_with_terminate_checks or the upper layer, return directly
                    return

                if run_result.is_interrupted:
                    self._resume_handle = run_result.resume_handle

                    # 统一使用 "interrupted" 状态，通过 interrupt_type 区分类型
                    if run_result.is_user_interrupted:
                        self._pause_type = PauseType.USER_INTERRUPT
                        await self._change_state(
                            AgentState.PAUSED, "Agent paused due to user interrupt"
                        )
                    else:
                        self._pause_type = PauseType.TOOL_INTERRUPT
                        await self._change_state(
                            AgentState.PAUSED, "Agent paused due to tool interrupt"
                        )
                    
                    # 统一输出格式：status 固定为 "interrupted"，通过 interrupt_type 区分
                    yield {
                        "status": "interrupted",
                        "handle": run_result.resume_handle,
                        "interrupt_type": run_result.resume_handle.interrupt_type if run_result.resume_handle else self._pause_type.value,
                    }
                    return

                elif run_result.is_completed:
                    await self._change_state(
                        AgentState.COMPLETED, "Agent completed execution"
                    )
                    yield run_result.result or {"status": "completed"}
                    return

                else:
                    # True exceptional cases: return value type does not match expectations
                    self._logger.error(
                        f"Unexpected run_result type: {type(run_result)}, value: {run_result}"
                    )
                    raise AgentLifecycleException(
                        "UNEXPECTED_STATE",
                        f"Unexpected run_result type: {type(run_result)}",
                    )

            else:
                # Stepping mode: Maintain original fine-grained progression and step-by-step output
                while True:
                    # Check whether pause is needed
                    await self._pause_event.wait()

                    # Check whether termination is needed
                    if self._terminate_event.is_set():
                        await self._on_terminate_coroutine()
                        break

                    # Execute one step
                    step_result = await self._on_step_coroutine()

                    # 5. Processing Step Results
                    if step_result.is_interrupted:
                        self._resume_handle = step_result.resume_handle

                        # 统一使用 "interrupted" 状态，通过 interrupt_type 区分类型
                        if step_result.is_user_interrupted:
                            self._pause_type = PauseType.USER_INTERRUPT
                            await self._change_state(
                                AgentState.PAUSED, "Agent paused due to user interrupt"
                            )
                        else:
                            # ToolInterrupt: Automatically pause and save resume handle
                            self._pause_type = PauseType.TOOL_INTERRUPT
                            await self._change_state(
                                AgentState.PAUSED, "Agent paused due to tool interrupt"
                            )
                        
                        # 统一输出格式
                        yield {
                            "status": "interrupted",
                            "handle": step_result.resume_handle,
                            "interrupt_type": step_result.resume_handle.interrupt_type if step_result.resume_handle else self._pause_type.value,
                        }
                        break

                    elif step_result.is_completed:
                        # Execution completed, including actual results
                        await self._change_state(
                            AgentState.COMPLETED, "Agent completed execution"
                        )
                        # Generate final result - return the actual execution result
                        yield step_result.result or {"status": "completed"}
                        break

                    else:
                        # Continue execution, producing intermediate results
                        yield {"status": "running", "step_result": step_result}

        except Exception as e:
            # If the exception is UserInterrupt, it might have been raised during state transition or context check
            # We should not transition to ERROR if it's a controlled interrupt
            if isinstance(e, AgentLifecycleException) and e.code == "NEED_RESUME":
                raise

            # If agent is already terminated, do not wipe state with ERROR
            if self.state == AgentState.TERMINATED:
                self._logger.debug(f"Exception during termination (ignored): {e}")
                raise

            # If agent is paused (e.g. interrupt happened), do not transition to ERROR
            if self.state == AgentState.PAUSED:
                 self._logger.debug(f"Exception while paused (ignored for ERROR state): {e}")
                 # Re-raise to let the caller handle it (e.g. runner loop catching UserInterrupt)
                 raise

            await self._change_state(AgentState.ERROR, f"Execution failed: {str(e)}")
            if isinstance(e, AgentLifecycleException):
                 raise
            raise AgentLifecycleException("EXECUTION_FAILED", str(e)) from e
        finally:
            # Clean up arun reentrancy flag
            async with self._arun_active_lock:
                self._arun_active = False

    async def _run_with_terminate_checks(self):
        """wrap _on_run_coroutine(): improve responsiveness to terminate in fast mode.

        注意：
        - 目前实践表明，额外创建任务并轮询 terminate_event 容易引入复杂竞态，
          尤其是在执行器已经正常完成时，可能导致外层感知不到完成信号。
        - 因此这里简化为：若未收到 terminate 信号，直接 await _on_run_coroutine()。
          仍保留对外部 CancelledError 的处理，以兼容 Ctrl+C 等外部中断。
        """
        from dolphin.core.logging.logger import console

        try:
            # 若在进入前就已收到 terminate 信号，直接返回 None 交由上层处理
            if self._terminate_event.is_set():
                return None

            run_coro = getattr(self, "_on_run_coroutine")
            return await run_coro()
        except asyncio.CancelledError:
            # External cancellation: return None for upper layer to handle as termination
            self._logger.debug("_run_with_terminate_checks cancelled externally")
            return None

    async def _on_execute(self, **kwargs) -> AsyncGenerator[Any, None]:
        """[Deprecated] Old execution interface.

                Please use coroutine interfaces: `arun()`/`step()`/`start_coroutine()`.
                This method is no longer called by BaseAgent, retained only for a few legacy call chains.
        """
        raise AgentLifecycleException(
            "DEPRECATED_API",
            "_on_execute() is deprecated; use coroutine APIs (arun/step/start_coroutine).",
        )

    async def pause(self) -> bool:
        """Pause Agent (based on coroutine)"""
        if self.state != AgentState.RUNNING:
            raise AgentLifecycleException(
                "INVALID_STATE", f"Cannot pause agent from state {self.state.value}"
            )

        try:
            # Pause coroutine execution
            if self._current_frame is not None:
                self._resume_handle = await self._on_pause_coroutine()
                self._pause_type = PauseType.MANUAL

            self._pause_event.clear()
            await self._change_state(AgentState.PAUSED, "Agent paused")
            await self._on_pause()
            return True
        except Exception as e:
            raise AgentLifecycleException("PAUSE_FAILED", str(e)) from e

    @abstractmethod
    async def _on_pause(self):
        """Pause logic implemented by subclasses"""
        pass

    async def resume(self, updates: Optional[Dict[str, Any]] = None) -> bool:
        """Resume Agent (based on coroutine)

        Args:
            updates: Variable updates to inject (used to resume from tool interruption)
        """
        if self.state != AgentState.PAUSED:
            raise AgentLifecycleException(
                "INVALID_STATE", f"Cannot resume agent from state {self.state.value}"
            )

        try:
            # Resume coroutine execution
            if self._resume_handle is not None:
                self._current_frame = await self._on_resume_coroutine(updates)
                self._resume_handle = None
                self._pause_type = None

            self._pause_event.set()
            await self._change_state(AgentState.RUNNING, "Agent resumed")
            await self._on_resume()
            return True
        except Exception as e:
            raise AgentLifecycleException("RESUME_FAILED", str(e)) from e

    @abstractmethod
    async def _on_resume(self):
        """Recovery logic implemented by subclasses"""
        pass

    async def terminate(self) -> bool:
        """Terminate Agent"""
        if self.state == AgentState.TERMINATED:
            return True

        try:
            # Set termination flag
            self._terminate_event.set()
            self._pause_event.set()  # Ensure that pausing will not cause blocking
            # Forcefully terminate coroutine execution frame (even outside an arun loop)
            try:
                await self._on_terminate_coroutine()
            except Exception:
                # Termination frame failure does not affect the overall termination process
                pass

            await self._change_state(AgentState.TERMINATED, "Agent terminated")
            await self._on_terminate()
            # Clean up the executing state to avoid external references holding expired references.
            self._current_frame = None
            self._resume_handle = None
            self._pause_type = None
            return True
        except Exception as e:
            raise AgentLifecycleException("TERMINATE_FAILED", str(e)) from e

    async def interrupt(self) -> bool:
        """User-initiated interrupt to provide new input.

        Unlike pause() which expects resumption from breakpoint, interrupt() signals
        that the user wants to provide new instructions and expects the agent to
        re-reason with the new context.

        Returns:
            True if interrupt was successfully initiated

        Note:
            This method now works in any state (not just RUNNING) to support
            interrupt signals arriving during state transitions. The interrupt
            event will be set regardless, allowing the next checkpoint to catch it.
        """
        if self.state != AgentState.RUNNING:
            self._logger.warning(
                f"Interrupt requested for agent {self.name} in {self.state.value} state "
                f"(expected RUNNING). Setting interrupt event anyway."
            )
        
        self._logger.info(f"User interrupt requested for agent {self.name}")
        self._interrupt_event.set()
        return True

    async def resume_with_input(self, user_input: Optional[str] = None) -> bool:
        """Resume execution after user interrupt, optionally with new input.

        This method is called after interrupt() to resume execution. If user_input
        is provided, it will be added to the context before resuming, triggering
        re-reasoning. If None, execution continues from the breakpoint.

        Args:
            user_input: New user instruction/message to add to context.
                       None means continue without new input.

        Returns:
            True if resume was successful

        Raises:
            AgentLifecycleException: If agent is not in PAUSED state or pause type
                                     is not 'user_interrupt'
        """
        if self.state != AgentState.PAUSED:
            raise AgentLifecycleException(
                "INVALID_STATE",
                f"Cannot resume agent in {self.state.value} state, must be PAUSED",
            )

        if self._pause_type != PauseType.USER_INTERRUPT:
            raise AgentLifecycleException(
                "INVALID_PAUSE_TYPE",
                f"resume_with_input() requires pause_type=USER_INTERRUPT, "
                f"got '{self._pause_type}'. Use resume() for tool interrupts.",
            )

        self._pending_user_input = user_input
        self._logger.info(
            f"Resume with input prepared, input={'provided' if user_input else 'none'}"
        )

        # Clear interrupt event to allow continued execution
        self._interrupt_event.clear()
        
        # NOTE: We do not change state to RUNNING here. 
        # arun() will detect PAUSED state and the presence of _pending_user_input 
        # to correctly resume the coroutine frame with updates.
        
        await self._on_resume()
        return True

    def get_interrupt_event(self) -> Event:
        """Get the interrupt event for injection into context.

        This allows the Context layer to check for interrupts during execution.

        Returns:
            The asyncio.Event used for interrupt signaling
        """
        return self._interrupt_event

    def clear_interrupt(self) -> None:
        """Clear the user interrupt state."""
        self._interrupt_event.clear()
        if hasattr(self, "executor") and self.executor and self.executor.context:
            self.executor.context.clear_interrupt()
        self._logger.debug(f"Interrupt state cleared for agent {self.name}")
    async def reset_for_retry(self) -> bool:
        """Reset the Agent state to retry, avoiding ALREADY_RUNNING errors.

                This method clears the execution state without changing the agent's basic configuration,
                allowing the agent to restart execution without concurrent call errors.
        """
        try:
            # If the agent is running, terminate it first.
            if self.state == AgentState.RUNNING:
                await self.terminate()

            # If the agent is in an error or terminated state, clean up the state and reinitialize.
            if self.state in [AgentState.ERROR, AgentState.TERMINATED]:
                # Clean up all execution-related states
                self._current_frame = None
                self._resume_handle = None
                self._pause_type = None

                # Reset arun activity flag
                async with self._arun_active_lock:
                    self._arun_active = False

                # Reset event status
                self._terminate_event.clear()
                self._pause_event.set()

                # Reset to initialization state
                await self._change_state(
                    AgentState.INITIALIZED,
                    "Agent reset for retry"
                )

            return True
        except Exception as e:
            # If the reset fails, at least attempt to reset the arun activity flag
            try:
                async with self._arun_active_lock:
                    self._arun_active = False
            except:
                pass
            raise AgentLifecycleException("RESET_FAILED", str(e)) from e

    @abstractmethod
    async def _on_terminate(self):
        """Termination logic implemented by subclasses"""
        pass

    # === Coroutine Series Abstract Methods ===
    @abstractmethod
    async def _on_start_coroutine(self, **kwargs):
        """Subclass implementation: Start coroutine execution

        Returns:
            ExecutionFrame: Execution frame object
        """
        pass

    @abstractmethod
    async def _on_step_coroutine(self) -> StepResult:
        """Subclass implementation: Execute one step

        Returns:
            StepResult: Step execution result
        """
        pass

    @abstractmethod
    async def _on_pause_coroutine(self):
        """Subclass implementation: pause coroutine

        Returns:
            ResumeHandle: resume handle
        """
        pass

    @abstractmethod
    async def _on_resume_coroutine(self, updates: Optional[Dict[str, Any]] = None):
        """Subclass implementation: resume coroutine

        Args:
            updates: variable updates to inject

        Returns:
            ExecutionFrame: the resumed execution frame
        """
        pass

    @abstractmethod
    async def _on_terminate_coroutine(self):
        """Subclass implementation: Terminating coroutines"""
        pass

    def get_status(self) -> AgentStatus:
        """Get Agent status"""
        return self.status

    def get_name(self) -> str:
        return self.name

    # Backward-compatible legacy API aliases
    def getName(self) -> str:
        return self.get_name()

    def get_description(self) -> str:
        """Get Agent Description"""
        return self.description

    def set_description(self, description: str):
        """Set Agent Description"""
        self.description = description

    def add_event_listener(self, event: AgentEvent, callback: Callable):
        """Add event listener"""
        self.event_listener.add_listener(event, callback)

    def remove_event_listener(self, event: AgentEvent, callback: Callable):
        """Remove event listener"""
        self.event_listener.remove_listener(event, callback)

    def is_running(self) -> bool:
        """Check if running"""
        return self.state == AgentState.RUNNING

    def is_paused(self) -> bool:
        """Check if paused"""
        return self.state == AgentState.PAUSED

    def is_completed(self) -> bool:
        """Check if completed"""
        return self.state == AgentState.COMPLETED

    def is_terminated(self) -> bool:
        """Check if terminated"""
        return self.state == AgentState.TERMINATED

    def get_resume_handle(self):
        """Get recovery handle (for resuming after tool interruption)"""
        return self._resume_handle

    def get_current_frame(self):
        """Get the current executing frame"""
        return self._current_frame

    async def step(self):
        """Execute one step (single-step execution)

                This is a convenient method for single-step execution in coroutine mode.
                The first call will automatically start the coroutine, and subsequent calls will advance the execution.

        Returns:
            bool or ResumeHandle or dict:
                    - ResumeHandle: encountered tool interruption
            - dict: execution result (containing completed and result)
            - bool: True indicates completion, False indicates continuation
        """
        # Concurrency protection: prevents calling step() while arun() is running.
        if self._arun_active:
            raise AgentLifecycleException(
                "CONCURRENT_EXECUTION", "Cannot call step() while arun() is active"
            )

        # If not yet initialized, initialize first
        if self.state == AgentState.CREATED:
            await self.initialize()

        # If it is in a paused state, handle the resume semantics
        if self.state == AgentState.PAUSED:
            if self._resume_handle is not None:
                if self._pause_type == PauseType.TOOL_INTERRUPT:
                    raise AgentLifecycleException(
                        "NEED_RESUME",
                        "Agent paused due to tool interrupt; call resume() with updates before step()",
                    )
                else:
                    # Manual pause: auto-resume handler and continue (no external explicit resume required)
                    self._logger.debug("Manual pause detected in step(); auto-resuming")
                    self._current_frame = await self._on_resume_coroutine(None)
                    self._resume_handle = None
                    self._pause_type = None
                    self._pause_event.set()
                    await self._change_state(
                        AgentState.RUNNING,
                        "Agent auto-resumed from manual pause via step()",
                    )
                    await self._on_resume()
            else:
                # Only when no resume handle is generated during suspension (early suspension) is it allowed to continue execution directly via step()
                self._pause_event.set()
                await self._change_state(AgentState.RUNNING, "Agent resumed via step()")

        # If the coroutine has not been started yet, start it first.
        if self._current_frame is None and self.state == AgentState.INITIALIZED:
            self._current_frame = await self._on_start_coroutine()
            await self._change_state(AgentState.RUNNING, "Agent started via step()")

        # If the agent has completed but needs to be re-executed, clean up the state and restart.
        if self.state == AgentState.COMPLETED:
            # First terminate the current coroutine and clean up the state
            try:
                if self._current_frame is not None:
                    await self._on_terminate_coroutine()
            except Exception:
                # Termination failure does not affect restart
                pass
            # Clean up the execution context
            self._current_frame = None
            self._resume_handle = None
            self._pause_type = None
            # Transition the state back to INITIALIZED and restart it.
            await self._change_state(
                AgentState.INITIALIZED, "Agent reinitialized for new run"
            )
            # Restart coroutine
            self._current_frame = await self._on_start_coroutine()
            await self._change_state(AgentState.RUNNING, "Agent restarted via step()")

        # If in RUNNING state but no executing frame, it indicates a state mismatch — log error and self-healing restart
        if self.state == AgentState.RUNNING and self._current_frame is None:
            self._logger.error(
                "Agent in RUNNING state but no frame; restarting coroutine via step()"
            )
            self._terminate_event.clear()
            self._pause_event.set()
            self._current_frame = await self._on_start_coroutine()

        # Execute one step and synchronize states
        if self.state == AgentState.RUNNING:
            step_result = await self._on_step_coroutine()

            # Process step results and synchronize status
            if step_result.is_interrupted:
                # Tool interruption: record handle and switch to pause
                self._resume_handle = step_result.resume_handle
                self._pause_type = PauseType.TOOL_INTERRUPT
                await self._change_state(
                    AgentState.PAUSED, "Agent paused due to tool interrupt"
                )
                return step_result

            if step_result.is_completed:
                await self._change_state(
                    AgentState.COMPLETED, "Agent completed execution"
                )
                return step_result

            # Not completed, continue running
            return step_result

        # Other illegal states (such as ERROR/TERMINATED) do not allow step-by-step execution
        raise AgentLifecycleException(
            "INVALID_STATE", f"Cannot step agent from state {self.state.value}"
        )

    def __str__(self) -> str:
        if self.description:
            return f"BaseAgent(name={self.name}, description='{self.description}', state={self.state.value})"
        return f"BaseAgent(name={self.name}, state={self.state.value})"
