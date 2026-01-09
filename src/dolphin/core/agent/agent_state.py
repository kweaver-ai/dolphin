"""Agent state enumeration definition"""

from datetime import datetime
from enum import Enum
from typing import Any


class AgentState(Enum):
    """Agent State Enumeration"""

    CREATED = "created"  # Created, not initialized
    INITIALIZED = "initialized"  # Initialized
    RUNNING = "running"  # Running
    PAUSED = "paused"  # Paused
    COMPLETED = "completed"  # Completed
    TERMINATED = "terminated"  # Terminated
    ERROR = "error"  # Error State


class PauseType(Enum):
    """Type of pause that caused agent to enter PAUSED state.

    Values:
        MANUAL: User explicitly called pause()
        TOOL_INTERRUPT: Tool requested user input (ToolInterrupt)
        USER_INTERRUPT: User actively interrupted execution (UserInterrupt)
    """
    MANUAL = "manual"
    TOOL_INTERRUPT = "tool_interrupt"
    USER_INTERRUPT = "user_interrupt"


class AgentEvent(Enum):
    """Agent Event Enumeration"""

    INIT = "init"  # Initialize event
    START = "start"  # Start executing event
    PAUSE = "pause"  # Pause Event
    RESUME = "resume"  # Recover event
    TERMINATE = "terminate"  # Termination Event
    COMPLETE = "complete"  # Completion Event
    ERROR = "error"  # Error Event


class AgentStatus:
    """Agent State Information Container"""

    def __init__(
        self,
        state: AgentState = AgentState.CREATED,
        message: str = "",
        data: Any = None,
    ):
        self.state = state
        self.message = message
        self.data = data
        self.timestamp: datetime = datetime.now()

    def to_dict(self) -> dict:
        """Convert to dictionary format"""
        return {
            "state": self.state.value,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    def __str__(self) -> str:
        return f"AgentStatus(state={self.state.value}, message='{self.message}')"
