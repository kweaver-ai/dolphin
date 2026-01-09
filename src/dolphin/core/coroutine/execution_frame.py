import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict


class FrameStatus(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_INTERVENTION = "waiting_for_intervention"
    TERMINATED = "terminated"


class WaitReason(Enum):
    """Reason for WAITING status (entropy-reduction: reuse WAITING with discriminator).

    This enum distinguishes different waiting scenarios without adding new frame statuses.
    """
    TOOL_REQUEST = "tool_request"      # Tool requests user input (ToolInterrupt)
    USER_INTERRUPT = "user_interrupt"  # User actively interrupted (UserInterrupt)


@dataclass
class ExecutionFrame:
    """Execution frame - saves execution state and control flow information"""

    frame_id: str
    parent_id: Optional[str] = None
    agent_id: Optional[str] = None
    block_pointer: int = 0
    block_stack: List[Dict] = None
    status: FrameStatus = FrameStatus.RUNNING
    context_snapshot_id: str = ""
    children: List[str] = None
    created_at: float = None
    updated_at: float = None
    original_content: str = ""  # Added: Save original dolphin script content
    error: Optional[Dict] = None  # Added: Error Messages
    wait_reason: Optional[WaitReason] = None  # Reason when in WAITING status

    def __post_init__(self):
        if self.block_stack is None:
            self.block_stack = []
        if self.children is None:
            self.children = []
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()

    @classmethod
    def create_root_frame(cls, agent_id: Optional[str] = None) -> "ExecutionFrame":
        """Create root execution frame"""
        return cls(
            frame_id=str(uuid.uuid4()),
            parent_id=None,
            agent_id=agent_id,
            block_pointer=0,
            block_stack=[],
            status=FrameStatus.RUNNING,
            children=[],
        )

    @classmethod
    def create_child_frame(
        cls, parent_frame: "ExecutionFrame", agent_id: Optional[str] = None
    ) -> "ExecutionFrame":
        """Create sub-execution frame"""
        return cls(
            frame_id=str(uuid.uuid4()),
            parent_id=parent_frame.frame_id,
            agent_id=agent_id,
            block_pointer=0,
            block_stack=[],
            status=FrameStatus.RUNNING,
            children=[],
        )

    def update_timestamp(self):
        """Update timestamp"""
        self.updated_at = time.time()

    def is_completed(self) -> bool:
        """Check if completed"""
        return self.status == FrameStatus.COMPLETED

    def is_failed(self) -> bool:
        """Check if failed"""
        return self.status == FrameStatus.FAILED

    def is_paused(self) -> bool:
        """Check if paused"""
        return self.status == FrameStatus.PAUSED

    def is_running(self) -> bool:
        """Check if running"""
        return self.status == FrameStatus.RUNNING

    def is_waiting_for_intervention(self) -> bool:
        """Check if waiting for user intervention"""
        return self.status == FrameStatus.WAITING_FOR_INTERVENTION

    def is_terminated(self) -> bool:
        """Check if already terminated"""
        return self.status == FrameStatus.TERMINATED

    def is_waiting_for_user_input(self) -> bool:
        """Check if waiting for user input (due to UserInterrupt)"""
        return (
            self.status == FrameStatus.WAITING_FOR_INTERVENTION
            and self.wait_reason == WaitReason.USER_INTERRUPT
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            "frame_id": self.frame_id,
            "parent_id": self.parent_id,
            "agent_id": self.agent_id,
            "block_pointer": self.block_pointer,
            "block_stack": self.block_stack,
            "status": self.status.value,
            "context_snapshot_id": self.context_snapshot_id,
            "children": self.children,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "original_content": self.original_content,
            "error": self.error,
            "wait_reason": self.wait_reason.value if self.wait_reason else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionFrame":
        """Create execution frame from dictionary"""
        data = data.copy()
        data["status"] = FrameStatus(data["status"])
        # Handle wait_reason if present
        if data.get("wait_reason"):
            data["wait_reason"] = WaitReason(data["wait_reason"])
        else:
            data["wait_reason"] = None
        return cls(**data)
