class DolphinException(Exception):
    """Exception raised when the Dolphin is interrupted."""

    def __init__(
        self,
        code: str,
        message: str = "",
        *args,
        **kwargs,
    ):
        super().__init__(message, *args, **kwargs)
        self.code = code
        self.message = message

    def __str__(self):
        return f"DolphinException: {self.code}, {self.message}"


class ModelException(DolphinException):
    """Exception raised when the model is interrupted."""

    def __init__(
        self,
        code: str,
        message: str = "The model was interrupted.",
        *args,
        **kwargs,
    ):
        super().__init__(code, message, *args, **kwargs)

    def __str__(self):
        return f"ModelException: {self.code}, {self.message}"


class SkillException(DolphinException):
    """Exception raised when the skill is interrupted."""

    def __init__(
        self,
        code: str,
        message="The skill was interrupted.",
        *args,
        **kwargs,
    ):
        super().__init__(code, message, *args, **kwargs)

    def __str__(self):
        # If message contains multiple lines, format it nicely
        if '\n' in self.message:
            return f"SkillException [{self.code}]:\n{self.message}"
        return f"SkillException: {self.code}, {self.message}"


class ContextEngineerException(DolphinException):
    """Exception raised when the context engineer is interrupted."""

    def __init__(
        self,
        code: str = "",
        message: str = "The context engineer was interrupted.",
        *args,
        **kwargs,
    ):
        super().__init__(code, message, *args, **kwargs)

    def __str__(self):
        return f"ContextEngineerException: {self.code}, {self.message}"


class AgentLifecycleException(DolphinException):
    """Agent Lifecycle Exception"""

    def __init__(self, code: str, message: str = "Agent lifecycle error"):
        super().__init__(code, message)

    def __str__(self):
        return f"AgentLifecycleException: {self.code}, {self.message}"


class DolphinAgentException(DolphinException):
    """Dolphin Agent Exception"""

    def __init__(self, code: str, message: str = "Dolphin agent error"):
        super().__init__(code, message)


class SyncError(DolphinException):
    """Exception raised during message synchronization."""

    def __init__(self, message: str = "Message synchronization failed."):
        super().__init__("SYNC_ERROR", message)

    def __str__(self):
        return f"SyncError: {self.message}"


class DebuggerQuitException(Exception):
    """Exception raised when the user quits the debugger."""
    pass


class UserInterrupt(DolphinException):
    """User-initiated interrupt to provide new input during execution.

    This exception is raised when the user actively interrupts the agent's
    execution (e.g., pressing ESC) to provide new instructions or corrections.

    Key differences from ToolInterrupt:
    - ToolInterrupt: Tool requests user input, resumes from breakpoint
    - UserInterrupt: User actively interrupts, triggers re-reasoning with new context

    Use cases:
    - User discovers agent is going in wrong direction, wants to correct
    - User wants to add additional context information
    - User wants to insert new requirements at current step

    Attributes:
        partial_output: Optional partial LLM output captured at interrupt time
        interrupted_at: Timestamp when interrupt occurred
    """

    def __init__(
        self,
        message: str = "User interrupted execution",
        partial_output: str = None,
    ):
        super().__init__("USER_INTERRUPT", message)
        self.partial_output = partial_output
        from datetime import datetime
        self.interrupted_at = datetime.now()

    def __str__(self):
        return f"UserInterrupt: {self.message}"
