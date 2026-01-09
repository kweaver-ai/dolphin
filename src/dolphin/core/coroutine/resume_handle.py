import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal


@dataclass
class ResumeHandle:
    """Resume handle - used to restore paused execution.

    Supports two interrupt types:
    - "tool_interrupt": Tool requested user input, resume from breakpoint
    - "user_interrupt": User actively interrupted, restart block with new context

    Attributes:
        frame_id: ID of the execution frame
        snapshot_id: ID of the context snapshot
        resume_token: Unique token for this resume operation
        interrupt_type: Type of interrupt ("tool_interrupt" or "user_interrupt")
        current_block: Block pointer at interrupt time (for user_interrupt)
        restart_block: Whether to restart the block (True for user_interrupt)
    """

    frame_id: str
    snapshot_id: str
    resume_token: str
    interrupt_type: Literal["tool_interrupt", "user_interrupt"] = "tool_interrupt"
    current_block: Optional[int] = None
    restart_block: bool = False

    @classmethod
    def create_handle(cls, frame_id: str, snapshot_id: str) -> "ResumeHandle":
        """Create recovery handle (for tool interrupt - backward compatible)"""
        return cls(
            frame_id=frame_id,
            snapshot_id=snapshot_id,
            resume_token=str(uuid.uuid4()),
            interrupt_type="tool_interrupt",
            restart_block=False,
        )

    @classmethod
    def create_user_interrupt_handle(
        cls,
        frame_id: str,
        snapshot_id: str,
        current_block: Optional[int] = None,
    ) -> "ResumeHandle":
        """Create resume handle for user interrupt.

        Args:
            frame_id: ID of the execution frame
            snapshot_id: ID of the context snapshot
            current_block: Block pointer at interrupt time

        Returns:
            ResumeHandle configured for user interrupt (restart_block=True)
        """
        return cls(
            frame_id=frame_id,
            snapshot_id=snapshot_id,
            resume_token=str(uuid.uuid4()),
            interrupt_type="user_interrupt",
            current_block=current_block,
            restart_block=True,
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            "frame_id": self.frame_id,
            "snapshot_id": self.snapshot_id,
            "resume_token": self.resume_token,
            "interrupt_type": self.interrupt_type,
            "current_block": self.current_block,
            "restart_block": self.restart_block,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ResumeHandle":
        """Create a restore handle from a dictionary"""
        # Handle backward compatibility for old data without new fields
        return cls(
            frame_id=data["frame_id"],
            snapshot_id=data["snapshot_id"],
            resume_token=data["resume_token"],
            interrupt_type=data.get("interrupt_type", "tool_interrupt"),
            current_block=data.get("current_block"),
            restart_block=data.get("restart_block", False),
        )

    def is_valid(self) -> bool:
        """Check if the handle is valid"""
        return bool(self.frame_id and self.snapshot_id and self.resume_token)

    def is_user_interrupt(self) -> bool:
        """Check if this handle is for a user interrupt"""
        return self.interrupt_type == "user_interrupt"

    def is_tool_interrupt(self) -> bool:
        """Check if this handle is for a tool interrupt"""
        return self.interrupt_type == "tool_interrupt"
