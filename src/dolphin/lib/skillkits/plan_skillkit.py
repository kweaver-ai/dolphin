"""Plan Skillkit for Unified Plan Architecture.

This module provides task orchestration tools for plan mode.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from dolphin.core.context.context import Context
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.task_registry import Task, TaskRegistry, TaskStatus, PlanExecMode
from dolphin.core.logging.logger import get_logger

logger = get_logger("plan_skillkit")

_VAR_PLAN_OUTPUTS_AUTO_INJECTED_PREFIX = "_plan.outputs_auto_injected"


class PlanSkillkit(Skillkit):
    """Task orchestration tools (Plan).

    Principles:
    - Stateless: persistent state lives in Context.
    - Tool-first: each method is an independent tool.
    - Composable: the agent can combine tools as needed.
    """

    # Import from constants to avoid duplication
    # Tools that should be excluded from subtasks to prevent infinite recursion
    from dolphin.core.common.constants import PLAN_ORCHESTRATION_TOOLS
    EXCLUDED_SUBTASK_TOOLS = PLAN_ORCHESTRATION_TOOLS

    def __init__(self, context: Optional[Context] = None):
        """Initialize PlanSkillkit.

        Args:
            context: Execution context (can be None, will be set via setContext)
        """
        super().__init__()
        self._context = context
        # Note: running_tasks dict has been removed - all asyncio task handles
        # are now managed centrally in TaskRegistry.running_asyncio_tasks
        self.max_concurrency: int = 5
        self._parent_skills: Optional[List[str]] = None  # Cache parent Agent's skills config
        self._last_poll_status: Optional[str] = None
        self._last_poll_time: float = 0

    @property
    def context(self) -> Optional[Context]:
        """Compatibility alias for accessing the execution context."""
        return self._context
    
    def setContext(self, context: Context):
        """Set the execution context (called by ExploreBlock)."""
        self._context = context
    
    def getContext(self) -> Optional[Context]:
        """Get the current execution context."""
        return self._context

    def getName(self) -> str:
        return "plan_skillkit"
    
    def _get_runtime_context(self) -> Optional[Context]:
        """Get the runtime context from various sources.
        
        Returns:
            Context if available, None otherwise
        """
        # Try instance context first
        if self._context:
            return self._context
        
        # Context should be injected by ExploreBlock when skillkit is used
        return None

    async def _plan_tasks(
        self,
        tasks: List[Dict[str, Any]],
        exec_mode: str = "para",
        max_concurrency: Optional[int] = None,
        **kwargs
    ) -> str:
        """Plan and start subtasks.

        Args:
            tasks: A list of task dicts, e.g.:
                [
                    {"id": "task_1", "name": "Task Name", "prompt": "Task description"},
                    {"id": "task_2", "name": "Task Name", "prompt": "Task description"},
                ]
            exec_mode: "para" (parallel) or "seq" (sequential) (default: "para")
            max_concurrency: Max concurrent tasks for parallel mode (default: 5)
            **kwargs: Additional properties

        Returns:
            A short summary string.

        Behavior:
        1. If plan is not enabled, enable it lazily.
        2. If a plan already exists, treat as replan.
        3. Register tasks into TaskRegistry.
        4. Start tasks based on execution mode and dependencies.
        5. Emit a `plan_created` event (UI can subscribe).
        """
        # Ensure context is available
        # Note: context should be injected by ExploreBlock when skillkit is used
        context = self._get_runtime_context()
        if not context:
            raise RuntimeError("PlanSkillkit requires context. Please ensure it's properly initialized.")

        # Disallow nested planning inside subtask contexts.
        # Subtasks should not orchestrate further plans; they should focus on executing their own prompts.
        try:
            from dolphin.core.context.cow_context import COWContext

            if isinstance(context, COWContext):
                raise RuntimeError("Nested planning is not supported")
        except RuntimeError:
            # Re-raise our own RuntimeError
            raise
        except Exception:
            # Fail-open: if the runtime type check fails for any reason, proceed with normal behavior.
            pass
        
        # Set context for subsequent method calls
        self._context = context
        
        # Init or replan
        if not self._context.is_plan_enabled():
            await self._context.enable_plan()
            logger.debug("Plan enabled")
        else:
            await self._context.enable_plan()  # Replan: resets registry
            logger.debug("Replan detected")

        # Capture parent Agent's skills configuration for subtasks
        # This allows subtasks to inherit the same tool set (minus excluded tools)
        self._parent_skills = self._context.get_last_skills()
        logger.debug(
            f"[PlanSkillkit] Captured parent skills for subtasks: {self._parent_skills}"
        )

        # Validate task list
        errors = self._validate_tasks(tasks)
        if errors:
            return f"Validation failed: {'; '.join(errors)}"

        # Update settings
        if max_concurrency is not None:
            self.max_concurrency = max_concurrency
            
        # Priority: input exec_mode (from LLM) > block parameter > default PARALLEL 
        current_exec_mode = PlanExecMode.PARALLEL

        # 1. Check if LLM explicitly requested a mode (other than default)
        if exec_mode and exec_mode != "para":
            current_exec_mode = PlanExecMode.from_str(exec_mode)
        # 2. Check if block parameters configured a mode
        elif self._context:
            cur_block = getattr(self._context.runtime_graph, "cur_block", None) if hasattr(self._context, "runtime_graph") else None
            if cur_block and hasattr(cur_block, "params"):
                block_exec_mode = cur_block.params.get("exec_mode")
                if block_exec_mode:
                    # ExploreBlock already validated/converted this to PlanExecMode enum
                    current_exec_mode = block_exec_mode if isinstance(block_exec_mode, PlanExecMode) else PlanExecMode.from_str(str(block_exec_mode))

        logger.debug(f"[PlanSkillkit] Final exec_mode: {current_exec_mode}")

        # Register tasks
        registry = self._context.task_registry
        for task_dict in tasks:
            task = Task(
                id=task_dict["id"],
                name=task_dict["name"],
                prompt=task_dict["prompt"],
            )
            await registry.add_task(task)

        registry.exec_mode = current_exec_mode
        registry.max_concurrency = self.max_concurrency

        # Emit plan_created event
        all_tasks = await registry.get_all_tasks()
        self._context.write_output("plan_created", {
            "plan_id": self._context.get_plan_id(),
            "exec_mode": current_exec_mode.value,
            "max_concurrency": self.max_concurrency,
            "tasks": [
                {"id": t.id, "name": t.name, "status": t.status.value}
                for t in all_tasks
            ],
        })

        # Prepare summary
        task_summary = "\n".join([f"- **{t['id']}**: {t['name']}" for t in tasks])
        
        # Start tasks
        if current_exec_mode == PlanExecMode.PARALLEL:
            ready_tasks = await self._select_ready_tasks(limit=self.max_concurrency)
            for task_id in ready_tasks:
                await self._spawn_task(task_id)
            return f"Plan initialized with {len(tasks)} tasks (parallel mode, max_concurrency={self.max_concurrency}):\n\n{task_summary}"
        else:
            ready = await self._select_ready_tasks(limit=1)
            if ready:
                await self._spawn_task(ready[0])
            return f"Plan initialized with {len(tasks)} tasks (sequential mode):\n\n{task_summary}"

    async def _check_progress(self, **kwargs) -> str:
        """Check the status of all subtasks.

        Returns:
            A formatted status summary with next-step guidance.
        """
        if not self._context.is_plan_enabled():
            raise RuntimeError("Plan is not enabled. Please call _plan_tasks first.")

        # Reuse ExploreBlock interrupt mechanism
        self._context.check_user_interrupt()

        registry = self._context.task_registry
        status_text = await registry.get_all_status()

        # Check for busy-waiting (same status polled too frequently)
        now = time.time()
        is_same_status = (status_text == self._last_poll_status)
        interval = now - self._last_poll_time

        # Item 5: Polling Throttling (Debounce / Guidance)
        throttle_warning = ""
        if is_same_status and not await registry.is_all_done():
            if interval < 2.0:
                # Hard limit: return early to prevent busy-waiting
                self._last_poll_time = now
                return (
                    "Status Unchanged (checked too recently). \n\n"
                    "💡 Guidance: Subtasks need time to execute. Do not poll `_check_progress` repeatedly "
                    "within 1-2 seconds. Use `_wait(seconds=10)` or synthesize existing info instead."
                )
            elif interval < 5.0:
                # Soft guidance: add warning but allow execution
                throttle_warning = (
                    "\n\n⚠️  Polling Guidance: Tasks are still running. "
                    "Consider using _wait(seconds=5) to give them more time to progress, "
                    "or work on other parts of the answer while waiting."
                )

        self._last_poll_status = status_text
        self._last_poll_time = now

        # Summary stats
        counts = await registry.get_status_counts()
        stats = f"{counts['completed']} completed, {counts['running']} running, {counts['failed']} failed"

        # Reconciliation: if tasks are marked RUNNING but no asyncio task exists,
        # they were probably lost during a snapshot/restore or process restart.
        # We auto-restart them to prevent the plan from stalling.
        reconciled = []
        running_tasks = await registry.get_running_tasks()
        for t in running_tasks:
            # Check without lock first (fast path)
            if t.id not in registry.running_asyncio_tasks:
                # Double-check with lock to prevent race
                async with registry._lock:
                    if t.id not in registry.running_asyncio_tasks:
                        logger.warning(
                            f"[PlanSkillkit] Reconciliation: Task {t.id} is RUNNING in registry but has no asyncio task. "
                            "Restarting task."
                        )
                        # Note: _spawn_task creates the task entry in running_asyncio_tasks
                        await self._spawn_task(t.id)
                        reconciled.append(t.id)

        result = f"Task Status:\n{status_text}\n\nSummary: {stats}{throttle_warning}"
        if reconciled:
            result += f"\n\n⚠️  Reconciliation: Restarted {len(reconciled)} stalled tasks ({', '.join(reconciled)})."

        # Sequential mode defensive check: if no tasks are running but there are pending tasks,
        # it might indicate the task chain was broken (e.g., finally block never executed).
        # Automatically kickstart the next task to prevent starvation.
        if registry.exec_mode == PlanExecMode.SEQUENTIAL:
            running_count = counts.get("running", 0)
            pending_count = counts.get("pending", 0)
            if running_count == 0 and pending_count > 0:
                # Find the next ready task and start it
                ready_tasks = await self._select_ready_tasks(limit=1)
                if ready_tasks:
                    logger.warning(
                        f"Sequential mode: No running tasks but {pending_count} pending. "
                        f"Kickstarting next task: {ready_tasks[0]}"
                    )
                    await self._spawn_task(ready_tasks[0])
                    result += (
                        "\n\n⚠️  Sequential Mode: Detected stalled task chain. "
                        f"Automatically started next task: {ready_tasks[0]}"
                    )

        # Add guidance when plan reaches a terminal state.
        # Also auto-inject task outputs once per plan_id to help the LLM synthesize a final answer
        if await registry.is_all_done() and counts["completed"] > 0:
            result += "\n\n✅ All tasks completed! Next steps:\n"
            result += "Synthesize the results into a comprehensive response for the user"

            plan_id = self._context.get_plan_id()
            if plan_id:
                injected_var = f"{_VAR_PLAN_OUTPUTS_AUTO_INJECTED_PREFIX}.{plan_id}"
                injected = self._context.get_var_value(injected_var, False)
                if isinstance(injected, str):
                    injected = injected.strip().lower() == "true"

                if not injected:
                    outputs = await self._get_task_output(task_id="all")
                    max_len = int(self._context.get_max_answer_len() or 0) or 10000
                    if len(outputs) > max_len:
                        outputs = outputs[:max_len] + f"(... too long, truncated to {max_len})"

                    result += "\n\n=== Task Outputs (Auto) ===\n"
                    result += outputs
                    result += "\n\nPlease synthesize all task outputs into the final answer."
                    self._context.set_variable(injected_var, True)
        elif not await registry.is_all_done():
            # Suggest using _wait tool if tasks are still running
            result += "\n\n💡 Tip: Some tasks are still running. If you have no other tasks to perform, use the `_wait(seconds=10)` tool to wait for progress instead of polling `_check_progress` repeatedly."

        return result

    async def _get_task_output(self, task_id: str = "all", **kwargs) -> str:
        """Get the execution results of completed subtasks.

        Args:
            task_id: The ID of the task to retrieve. Defaults to "all", which returns
                    a summary of status and outputs for all tasks.

        Returns:
            The output of the task or a compiled summary.
        """
        if not self._context.is_plan_enabled():
            raise RuntimeError("Plan is not enabled")

        registry = self._context.task_registry

        if task_id == "all":
            all_tasks = await registry.get_all_tasks()
            if not all_tasks:
                return "No tasks found"

            outputs = []
            for task in all_tasks:
                if task.status == TaskStatus.COMPLETED:
                    output = task.answer or "(no output)"
                    outputs.append(f"=== {task.id}: {task.name} ===\n{output}\n")
                elif task.status == TaskStatus.RUNNING:
                    outputs.append(f"=== {task.id}: {task.name} ===\n[Still running]\n")
                elif task.status == TaskStatus.FAILED:
                    error_msg = task.error or "Unknown error"
                    outputs.append(f"=== {task.id}: {task.name} ===\n[Failed: {error_msg}]\n")
                else:
                    outputs.append(f"=== {task.id}: {task.name} ===\n[{task.status.value}]\n")

            if not outputs:
                return "No task outputs available"
            return "\n".join(outputs)
        
        else:
            task = await registry.get_task(task_id)
            if not task:
                raise RuntimeError(f"Task '{task_id}' not found")

            if task.status != TaskStatus.COMPLETED:
                raise RuntimeError(f"Task '{task_id}' is not completed (status: {task.status.value})")

            logger.debug(f"[_get_task_output] task_id={task_id}, answer type={type(task.answer)}, length={len(task.answer or '')}")
            return task.answer or "(no output)"

    async def _wait(self, seconds: float, **kwargs) -> str:
        """Wait for a specified time (can be interrupted by user).

        Args:
            seconds: Duration to wait in seconds

        Returns:
            Confirmation message
        """
        for i in range(int(seconds)):
            # Check user interrupt once per second
            self._context.check_user_interrupt()
            await asyncio.sleep(1)

        return f"Waited {seconds}s"

    async def _kill_task(self, task_id: str, **kwargs) -> str:
        """Terminate a running task.

        This method only sends the cancellation signal to the asyncio task.
        The task's exception handler (in _spawn_task's run_task) is responsible
        for updating the registry status to prevent race conditions.

        Args:
            task_id: Task identifier

        Returns:
            Confirmation or error message
        """
        if not self._context.is_plan_enabled():
            raise RuntimeError("Plan is not enabled")

        registry = self._context.task_registry

        # Use lock to safely check and cancel the task
        async with registry._lock:
            if task_id in registry.running_asyncio_tasks:
                asyncio_task = registry.running_asyncio_tasks[task_id]
                # Only send cancel signal; status update will be handled by the task's exception handler
                asyncio_task.cancel()
            else:
                raise RuntimeError(f"Task '{task_id}' is not running")

        # Note: Status update and cleanup are handled by the task's CancelledError handler
        # in _spawn_task's run_task() to avoid race conditions.
        # Yield control to allow the cancellation to propagate to the task.
        await asyncio.sleep(0)
        
        return f"Task '{task_id}' cancellation requested (status will update shortly)"

    async def _retry_task(self, task_id: str, **kwargs) -> str:
        """Retry a failed task.

        Args:
            task_id: Task identifier

        Returns:
            Confirmation or error message
        """
        if not self._context.is_plan_enabled():
            raise RuntimeError("Plan is not enabled")

        registry = self._context.task_registry
        task = await registry.get_task(task_id)

        if not task:
            raise RuntimeError(f"Task '{task_id}' not found")

        if task.status != TaskStatus.FAILED:
            raise RuntimeError(f"Task '{task_id}' cannot be retried (status: {task.status.value})")

        # Reset status and restart
        await registry.update_status(task_id, TaskStatus.PENDING, error=None)
        await self._spawn_task(task_id)

        return f"Task '{task_id}' restarted"

    def _createSkills(self) -> List[SkillFunction]:
        """Create skill functions for plan orchestration."""
        return [
            SkillFunction(self._plan_tasks),
            SkillFunction(self._check_progress),
            SkillFunction(self._get_task_output),
            SkillFunction(self._wait),
            SkillFunction(self._kill_task),
            SkillFunction(self._retry_task),
        ]

    # ===== Internal helpers =====

    def _get_filtered_subtask_tools(self) -> Optional[List[str]]:
        """Get filtered tool list for subtasks by removing PlanSkillkit tools.

        Returns:
            List of tool names (strings) or None if parent didn't specify tools
        """
        if self._parent_skills is None:
            # Parent didn't specify tools - let subtask inherit from COWContext
            logger.debug("No parent skills configured, subtasks will inherit from COWContext")
            return None

        # Filter out PlanSkillkit tools AND the skillkit name itself
        # (since PlanSkillkit is excluded from subtask contexts)
        excluded_patterns = self.EXCLUDED_SUBTASK_TOOLS | {"plan_skillkit"}

        filtered = [
            tool for tool in self._parent_skills
            if tool not in excluded_patterns
        ]

        excluded_found = excluded_patterns & set(self._parent_skills)
        logger.debug(
            f"[PlanSkillkit] Filtered subtask tools: {filtered} (excluded: {excluded_found})"
        )
        return filtered if filtered else None

    async def _spawn_task(self, task_id: str):
        """Spawn a single subtask using ExploreBlock with a COW Context.

        Args:
            task_id: Task identifier
        """
        from dolphin.core.code_block.explore_block import ExploreBlock

        registry = self._context.task_registry
        task = await registry.get_task(task_id)

        # Capture plan_id at spawn time to prevent cleanup race conditions
        spawn_plan_id = self._context.get_plan_id()

        # Filter parent skills to exclude PlanSkillkit tools
        subtask_tools = self._get_filtered_subtask_tools()
        
        explore_block_content = self._build_subtask_explore_block_content(
            task.prompt, 
            tools=subtask_tools
        )

        async def run_task():
            try:
                # Transition to RUNNING
                await registry.update_status(task_id, TaskStatus.RUNNING, started_at=time.time())

                self._context.write_output("plan_task_update", {
                    "plan_id": self._context.get_plan_id(),
                    "task_id": task_id,
                    "status": "running",
                })

                # Create COW context
                # Note: Subtask variable writes are isolated in this child_context.
                # By design, they are NOT merged back to the parent to prevent side effects
                # and maintain strict task isolation. Each task should communicate its results
                # via its 'answer' output.
                child_context = self._context.fork(task_id)

                # Execute via ExploreBlock
                explore = ExploreBlock(context=child_context)
                result = None
                async for output in explore.execute(content=explore_block_content):
                    result = output
                    # Stream output to UI
                    if isinstance(output, dict):
                        # Extract answer and think deltas if available
                        answer_chunk = output.get("answer", "")
                        think_chunk = output.get("think", "")
                        
                        if answer_chunk or think_chunk:
                            self._context.write_output("plan_task_output", {
                                "plan_id": self._context.get_plan_id(),
                                "task_id": task_id,
                                "answer": answer_chunk,
                                "think": think_chunk,
                                "stream_mode": "delta",
                                "is_final": False,
                            })

                # Extract final output components
                output_dict = self._extract_output_dict(result)

                # Clear COW context's local changes to release memory
                # This prevents memory bloat from intermediate variables in long-running tasks
                if hasattr(child_context, 'clear_local_changes'):
                    child_context.clear_local_changes()

                # Transition to COMPLETED
                duration = time.time() - task.started_at
                await registry.update_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    answer=output_dict.get("answer"),
                    think=output_dict.get("think"),
                    block_answer=output_dict.get("block_answer"),
                    duration=duration
                )

                self._context.write_output("plan_task_update", {
                    "plan_id": self._context.get_plan_id(),
                    "task_id": task_id,
                    "status": "completed",
                    "duration_ms": duration * 1000,
                })

                # Sequential mode: start next ready task
                # Note: This is only done on success. In case of failure or cancellation,
                # we rely on the orchestrator calling _check_progress(), which has a
                # recovery mechanism to kickstart the next task if the chain is stalled.
                if registry.exec_mode == PlanExecMode.SEQUENTIAL:
                    ready = await self._select_ready_tasks(limit=1)
                    if ready:
                        await self._spawn_task(ready[0])

            except asyncio.CancelledError:
                task_obj = await registry.get_task(task_id)
                started_at = task_obj.started_at if task_obj else None
                duration = (time.time() - started_at) if started_at else None
                await registry.update_status(task_id, TaskStatus.CANCELLED, duration=duration)

                payload = {
                    "plan_id": self._context.get_plan_id(),
                    "task_id": task_id,
                    "status": "cancelled",
                }
                if duration is not None:
                    payload["duration_ms"] = duration * 1000

                self._context.write_output("plan_task_update", payload)
                raise
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                await registry.update_status(task_id, TaskStatus.FAILED, error=str(e))

                self._context.write_output("plan_task_update", {
                    "plan_id": self._context.get_plan_id(),
                    "task_id": task_id,
                    "status": "failed",
                    "error": str(e),
                })
            finally:
                # Idempotent cleanup with plan_id check to prevent race conditions
                # Only clean up if the plan hasn't been reset/replaced
                # Use lock to prevent race conditions with _kill_task and _check_progress reconciliation
                current_plan_id = self._context.get_plan_id()
                if current_plan_id == spawn_plan_id:
                    async with registry._lock:
                        registry.running_asyncio_tasks.pop(task_id, None)
                else:
                    logger.debug(
                        f"Skipping cleanup for task {task_id}: plan_id mismatch "
                        f"(spawn={spawn_plan_id}, current={current_plan_id})"
                    )

        # Start asyncio task
        # Use lock to ensure atomicity when adding to running_asyncio_tasks
        asyncio_task = asyncio.create_task(run_task())
        async with registry._lock:
            registry.running_asyncio_tasks[task_id] = asyncio_task

    @staticmethod
    def _build_subtask_explore_block_content(prompt: str, tools: Optional[List[str]] = None) -> str:
        """Build a valid DPH explore block string for subtask execution.
        
        Args:
            prompt: Task description/instructions
            tools: List of tool names to include (if None, subtask inherits all parent skills)
        
        Subtask tool inheritance strategy:
        - Subtasks inherit parent Agent's tools configuration
        - PlanSkillkit tools are automatically excluded to prevent infinite recursion
        - If parent didn't specify tools, subtask inherits from COWContext (all skills)
        
        Excluded tools (defined in EXCLUDED_SUBTASK_TOOLS):
        - _plan_tasks, _check_progress, _get_task_output, _wait, _kill_task, _retry_task
        
        This design allows parent Agent to control subtask capabilities naturally.
        
        Example:
        - Parent: /explore/(tools=[_search, _plan_tasks, _bash, _cog_think])
        - Subtask: /explore/(tools=[_search, _bash, _cog_think])  # plan tools filtered out
        """
        prompt = (prompt or "").strip()
        # BasicCodeBlock.parse_block_content requires an assign suffix ("-> var").
        
        if tools is not None:
            # Use quoted tool names to avoid parsing ambiguity and support special characters.
            tools_str = ", ".join(json.dumps(tool) for tool in tools)
            return f"/explore/(tools=[{tools_str}]) {prompt} -> result"
        else:
            # Always include an empty params list to avoid ambiguity when prompt begins with "(".
            # No tools specified - inherit from COWContext (already filtered)
            return f"/explore/() {prompt} -> result"

    async def _select_ready_tasks(self, limit: int) -> List[str]:
        """Select runnable tasks based on dependency readiness.

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of task IDs
        """
        registry = self._context.task_registry
        ready_tasks = await registry.get_ready_tasks()
        return [t.id for t in ready_tasks][:limit]

    def _validate_tasks(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Validate task list.

        Args:
            tasks: List of task dictionaries

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        if not tasks:
            errors.append("Empty task list")
            return errors

        seen_ids = set()
        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                errors.append(f"Task {i} is not a dictionary")
                continue

            task_id = task.get("id")
            if not task_id:
                errors.append(f"Task {i} missing 'id' field")
            elif task_id in seen_ids:
                errors.append(f"Duplicate task ID: {task_id}")
            else:
                seen_ids.add(task_id)

            if not task.get("name"):
                errors.append(f"Task {i} ({task_id}) missing 'name' field")

            if not task.get("prompt"):
                errors.append(f"Task {i} ({task_id}) missing 'prompt' field")

        return errors

    def _extract_output(self, result: Any) -> str:
        """Extract primary answer text from results (for terminal logic)."""
        output_dict = self._extract_output_dict(result)
        return output_dict.get("answer") or ""

    def _extract_output_dict(self, result: Any) -> Dict[str, str]:
        """Extract multi-field output from ExploreBlock result.

        Args:
            result: ExploreBlock execution result

        Returns:
            Dict with answer, think, and block_answer
        """
        logger.debug(f"[_extract_output_dict] result type={type(result)}, value={repr(result)[:500] if result else None}")
        
        if isinstance(result, dict):
            # Capture all relevant fields
            return {
                "answer": result.get("answer", "") or result.get("output", "") or result.get("result", "") or "",
                "think": result.get("think", "") or "",
                "block_answer": result.get("block_answer", "") or "",
            }
        elif isinstance(result, str):
            return {"answer": result, "think": "", "block_answer": ""}
        else:
            return {"answer": str(result) if result is not None else "", "think": "", "block_answer": ""}

    @staticmethod
    def should_exclude_from_subtask() -> bool:
        """Mark this skillkit for exclusion from subtask contexts.

        Returns:
            True to exclude from subtasks
        """
        return True
