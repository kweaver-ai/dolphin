from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Dict, Any

if TYPE_CHECKING:
    from dolphin.core.coroutine.resume_handle import ResumeHandle


@dataclass
class StepResult:
    """Unified result for a single coroutine step.

    - status: "running" when more steps remain, "completed" when finished, "interrupted" when intervention needed
    - result: optional payload at any status (e.g., intermediate data during running, final user variables when completed)
    - resume_handle: handle for resuming from interruption

    Status values:
    - "running": execution continuing, more steps remain
    - "completed": execution finished successfully
    - "interrupted": execution paused due to interruption (tool or user)
    - "user_interrupted": (internal) specifically marks UserInterrupt, but external yield uses "interrupted" + interrupt_type

    Interrupt Type Discrimination:
    - When yielded externally, all interrupts use status="interrupted"
    - Use resume_handle.interrupt_type to distinguish:
      - "tool_interrupt": tool requested user input (ToolInterrupt)
      - "user_interrupt": user actively interrupted (UserInterrupt)

    Truthiness: bool(StepResult) is True only when status == "completed".
    This preserves existing `if is_complete:` style checks.
    """

    status: Literal["running", "completed", "interrupted", "user_interrupted"]
    result: Optional[Dict[str, Any]] = None
    resume_handle: Optional["ResumeHandle"] = None

    def __bool__(self) -> bool:  # pragma: no cover - simple helper
        """Returns True only when status is 'completed' for backward compatibility"""
        return self.status == "completed"

    @property
    def is_interrupted(self) -> bool:
        """Check if execution was interrupted (tool or user).

        Returns True for both 'interrupted' (ToolInterrupt) and 'user_interrupted' (UserInterrupt).
        Use is_user_interrupted or is_tool_interrupted for specific checks.
        """
        return self.status in ("interrupted", "user_interrupted")

    @property
    def is_tool_interrupted(self) -> bool:
        """Check if execution was interrupted by a tool (ToolInterrupt)"""
        return self.status == "interrupted"

    @property
    def is_user_interrupted(self) -> bool:
        """Check if execution was interrupted by user (UserInterrupt)"""
        return self.status == "user_interrupted"

    @property
    def is_running(self) -> bool:
        """Check if execution is still running"""
        return self.status == "running"

    @property
    def is_completed(self) -> bool:
        """Check if execution is completed"""
        return self.status == "completed"

    @classmethod
    def running(cls, result: Optional[Dict[str, Any]] = None) -> "StepResult":
        """Create a running status result with optional intermediate data"""
        return cls(status="running", result=result)

    @classmethod
    def completed(cls, result: Optional[Dict[str, Any]] = None) -> "StepResult":
        """Create a completed status result with optional result data"""
        return cls(status="completed", result=result)

    @classmethod
    def interrupted(cls, resume_handle: "ResumeHandle") -> "StepResult":
        """Create an interrupted status result with resume handle (ToolInterrupt)"""
        return cls(status="interrupted", resume_handle=resume_handle)

    @classmethod
    def user_interrupted(
        cls,
        resume_handle: "ResumeHandle",
        result: Optional[Dict[str, Any]] = None,
    ) -> "StepResult":
        """Create a user-interrupted status result with resume handle (UserInterrupt).

        Args:
            resume_handle: Handle for resuming execution
            result: Optional partial result data (e.g., partial LLM output)

        Returns:
            StepResult with status="user_interrupted"
        """
        return cls(status="user_interrupted", resume_handle=resume_handle, result=result)
