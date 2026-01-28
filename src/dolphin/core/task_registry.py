"""Task Registry for Plan Mode.

This module provides task state management for unified plan architecture.

Logging conventions:
- DEBUG: Task registration, status updates, cancellations
- INFO: Registry lifecycle events (reset, mode changes)
- WARNING: Invalid operations (unknown task, missing registry)
- ERROR: Critical failures in task management
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from dolphin.core.logging.logger import get_logger

logger = get_logger("task_registry")


class OutputEventType(str, Enum):
    """Output event types for UI/SDK consumers.

    These events are emitted via Context.write_output() and can be consumed
    by UI components or SDK integrations for real-time updates.
    """
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_PROGRESS = "task_progress"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_FINISHED = "plan_finished"


class TaskStatus(str, Enum):
    """Task status values."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PlanExecMode(str, Enum):
    """Execution mode for plan orchestration."""
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"

    @staticmethod
    def from_str(mode: str) -> "PlanExecMode":
        """Convert a string (seq/para/sequential/parallel) to PlanExecMode."""
        if not mode:
            return PlanExecMode.PARALLEL
        
        mode = mode.lower().strip()
        if mode in ("seq", "sequential"):
            return PlanExecMode.SEQUENTIAL
        if mode in ("para", "parallel"):
            return PlanExecMode.PARALLEL
        
        raise ValueError(f"Invalid execution mode: {mode}. Must be 'seq' or 'para'.")


@dataclass
class Task:
    """Task metadata and state."""
    id: str
    name: str
    prompt: str

    # Runtime fields
    status: TaskStatus = TaskStatus.PENDING
    answer: Optional[str] = None
    think: Optional[str] = None
    block_answer: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    duration: Optional[float] = None
    attempt: int = 0

    # Reserved for Phase 2
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert Task to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "status": self.status.value,
            "answer": self.answer,
            "think": self.think,
            "block_answer": self.block_answer,
            "error": self.error,
            "started_at": self.started_at,
            "duration": self.duration,
            "attempt": self.attempt,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create Task from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            prompt=data["prompt"],
            status=TaskStatus(data["status"]),
            answer=data.get("answer"),
            think=data.get("think"),
            block_answer=data.get("block_answer"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            duration=data.get("duration"),
            attempt=data.get("attempt", 0),
            depends_on=data.get("depends_on", []),
        )


class TaskRegistry:
    """Persistent task state registry.

    Notes:
    - Stores only serializable task state.
    - Runtime handles (asyncio.Task) are kept outside for correctness and recoverability.
    - Thread-safe via asyncio.Lock.
    """

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()

        # Config fields (set by PlanSkillkit._plan_tasks)
        self.exec_mode: PlanExecMode = PlanExecMode.PARALLEL
        self.max_concurrency: int = 5

        # Runtime handles (not persisted)
        self.running_asyncio_tasks: Dict[str, asyncio.Task] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert TaskRegistry to dictionary."""
        return {
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
            "exec_mode": self.exec_mode.value,
            "max_concurrency": self.max_concurrency,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRegistry":
        """Create TaskRegistry from dictionary."""
        registry = cls()
        registry.tasks = {
            task_id: Task.from_dict(task_data)
            for task_id, task_data in data.get("tasks", {}).items()
        }
        registry.exec_mode = PlanExecMode(data.get("exec_mode", PlanExecMode.PARALLEL.value))
        registry.max_concurrency = data.get("max_concurrency", 5)
        return registry

    async def add_task(self, task: Task):
        """Register a new task."""
        async with self._lock:
            self.tasks[task.id] = task
            logger.debug(f"Task registered: {task.id} ({task.name})")

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID (thread-safe)."""
        async with self._lock:
            return self.tasks.get(task_id)

    async def get_all_tasks(self) -> List[Task]:
        """Return all tasks (thread-safe)."""
        async with self._lock:
            return list(self.tasks.values())

    async def get_pending_tasks(self) -> List[Task]:
        """Return tasks that are pending (thread-safe)."""
        async with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    async def get_ready_tasks(self) -> List[Task]:
        """Return tasks that are ready to be started (thread-safe).

        Phase 1 (no dependency scheduling):
        - All PENDING tasks are considered ready.

        Phase 2 (reserved):
        - Check depends_on and only return tasks whose dependencies are completed.
        """
        async with self._lock:
            return [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]

    async def get_running_tasks(self) -> List[Task]:
        """Return tasks that are running (thread-safe)."""
        async with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]

    async def get_completed_tasks(self) -> List[Task]:
        """Return tasks that are completed (thread-safe)."""
        async with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]

    async def get_failed_tasks(self) -> List[Task]:
        """Return tasks that have failed (thread-safe)."""
        async with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.FAILED]

    async def has_tasks(self) -> bool:
        """Return whether any tasks are registered (thread-safe)."""
        async with self._lock:
            return bool(self.tasks)

    async def reset(self):
        """Reset task state (used for replan).

        Clears:
        - All tasks
        - Running asyncio task handles (cancels them first)

        Preserves:
        - exec_mode (will be overwritten by next _plan_tasks call)
        - max_concurrency (will be overwritten by next _plan_tasks call)

        Note:
            This is an async method to ensure proper locking for concurrent safety.
        """
        async with self._lock:
            # Cancel all running asyncio tasks to prevent background leaks during replan
            for task_id, asyncio_task in self.running_asyncio_tasks.items():
                if not asyncio_task.done():
                    asyncio_task.cancel()
                    logger.debug(f"Cancelled orphaned task {task_id} during registry reset")

            self.tasks.clear()
            self.running_asyncio_tasks.clear()
            logger.info("TaskRegistry reset (replan)")

    async def is_all_done(self) -> bool:
        """Return whether all tasks have reached a terminal state (thread-safe)."""
        async with self._lock:
            terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
            return all(task.status in terminal for task in self.tasks.values())

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        **kwargs
    ):
        """Update task status and related fields.

        Args:
            task_id: Task identifier
            status: New status
            **kwargs: Additional fields to update (answer, think, block_answer, error, started_at, etc.)

        Note:
            Terminal states (COMPLETED, FAILED, CANCELLED, SKIPPED) cannot be transitioned.
            This prevents race conditions during task cancellation or completion.
        """
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.warning(f"Cannot update status for unknown task: {task_id}")
                return

            # Validate state transitions: terminal states cannot be changed
            # Note: FAILED is excluded from terminal states to allow retries
            terminal_states = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
            if task.status in terminal_states:
                logger.warning(
                    f"Cannot transition task {task_id} from terminal state {task.status.value} to {status.value}"
                )
                return

            task.status = status

            # Update additional fields
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)

            # Compute duration for terminal states
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.started_at and not task.duration:
                    task.duration = time.time() - task.started_at

            logger.debug(f"Task {task_id} status updated: {status.value}")

    async def get_status_counts(self) -> Dict[str, int]:
        """Return count per status (thread-safe)."""
        async with self._lock:
            counts = {status.value: 0 for status in TaskStatus}
            for task in self.tasks.values():
                counts[task.status.value] += 1
            return counts

    async def get_progress_signature(self) -> tuple:
        """Compute a signature representing the current task progress state (thread-safe).

        Returns:
            A tuple of (task_id, status) pairs sorted by task_id.
            This signature changes whenever any task changes status.

        Usage:
            Used by ExploreBlock to detect whether tasks have made progress.
            If the signature is the same across multiple rounds, it indicates
            the plan is stalled (no status changes).

        Example:
            >>> registry.get_progress_signature()
            (('task_1', 'running'), ('task_2', 'pending'))
        """
        async with self._lock:
            tasks = list(self.tasks.values())
            return tuple(
                (t.id, getattr(t.status, "value", str(t.status)))
                for t in sorted(tasks, key=lambda x: x.id)
            )

    async def get_all_status(self) -> str:
        """Return a formatted status summary (for _check_progress, thread-safe).

        Returns:
            A multi-line string with task status, including error details for failed tasks.
        """
        async with self._lock:
            lines = []
            now = time.time()
            for task in self.tasks.values():
                if task.status == TaskStatus.RUNNING and task.started_at:
                    duration_str = f"{now - task.started_at:.1f}s+"
                else:
                    duration_str = f"{task.duration:.1f}s" if task.duration else "N/A"

                icon_map = {
                    TaskStatus.PENDING: "⏳",
                    TaskStatus.RUNNING: "🔄",
                    TaskStatus.COMPLETED: "✅",
                    TaskStatus.FAILED: "❌",
                    TaskStatus.CANCELLED: "🚫",
                    TaskStatus.SKIPPED: "⏭️",
                }
                icon = icon_map.get(task.status, "?")
                status_label = task.status.value

                # Item 3 Optimization: Check if task is in the process of being cancelled
                if task.status == TaskStatus.RUNNING and task.id in self.running_asyncio_tasks:
                    asyncio_task = self.running_asyncio_tasks[task.id]
                    # Check if cancelling (Python 3.11+) or if it's already done but status not updated
                    is_cancelling = False
                    if hasattr(asyncio_task, "cancelling"):
                        is_cancelling = asyncio_task.cancelling() > 0
                    
                    if is_cancelling:
                        icon = "⏳🚫"
                        status_label = "cancelling..."

                base_line = f"{icon} {task.id}: {task.name} [{status_label}] ({duration_str})"

                # For failed tasks, include error details to enable self-correction
                if task.status == TaskStatus.FAILED and task.error:
                    error_preview = task.error[:150]  # Limit error length
                    if len(task.error) > 150:
                        error_preview += "..."
                    base_line += f"\n    Error: {error_preview}"

                lines.append(base_line)

            return "\n".join(lines)

    async def cancel_all_running(self) -> int:
        """Cancel all running asyncio tasks and update their status.

        Returns:
            Number of tasks cancelled

        Note:
            This method both cancels the asyncio.Task objects and updates
            the Task status to CANCELLED to keep state synchronized.
        """
        async with self._lock:
            cancelled = 0
            for task_id, asyncio_task in list(self.running_asyncio_tasks.items()):
                if not asyncio_task.done():
                    asyncio_task.cancel()
                    cancelled += 1
                    # Update task status to CANCELLED
                    # This ensures Registry state matches actual execution state
                    task = self.tasks.get(task_id)
                    if task:
                        task.status = TaskStatus.CANCELLED
                        # Compute duration if task was started
                        if task.started_at and not task.duration:
                            task.duration = time.time() - task.started_at
                    logger.debug(f"Cancelled running task: {task_id}")

            self.running_asyncio_tasks.clear()
            return cancelled
