"""Hook Types Module

This module defines the data structures and protocols for the Hook-based verify system.

Key Components:
- HookConfig: Configuration for Hook behavior
- OnStopContext: Context passed to on_stop Hook handlers
- HookResult: Standardized result from Hook execution
- HookContextProtocol: Protocol for extensibility
- AgentRef: Reference to a verification agent (.dph file)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Union, Protocol, runtime_checkable


@runtime_checkable
class HookContextProtocol(Protocol):
    """Protocol for Hook Context, enabling future extensibility.

    Any Hook Context (on_stop, on_start, on_error, etc.) must satisfy this protocol.
    """
    attempt: int
    stage: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary representation."""
        ...


@dataclass
class AgentRef:
    """Reference to a verification agent (.dph file).

    Attributes:
        path: Path to the .dph file (without extension)
    """
    path: str

    def __post_init__(self):
        # Remove @ prefix if present
        if self.path.startswith('@'):
            self.path = self.path[1:]
        # Add .dph extension if not present
        if not self.path.endswith('.dph'):
            self.path = f"{self.path}.dph"


@dataclass
class HookConfig:
    """Configuration for Hook behavior.

    Attributes:
        handler: The handler for the Hook - can be an expression string or AgentRef
        threshold: Score threshold for passing (0.0 to 1.0)
        max_retries: Maximum number of retry attempts
        model: Optional model to use for verification
        context: Optional context configuration (e.g., exposed_variables)
        llm_timeout: Timeout for LLM calls in seconds
        agent_timeout: Timeout for agent execution in seconds
    """
    handler: Union[str, AgentRef]
    threshold: float = 0.5
    max_retries: int = 0
    model: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    llm_timeout: int = 30
    agent_timeout: int = 60

    def __post_init__(self):
        # Validate threshold range
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {self.threshold}")

        # Validate max_retries is non-negative
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {self.max_retries}")

        # Limit max_retries to prevent infinite loops
        if self.max_retries > 10:
            raise ValueError(f"max_retries cannot exceed 10, got {self.max_retries}")

    @property
    def exposed_variables(self) -> List[str]:
        """Get list of exposed variables from context config."""
        if self.context and 'exposed_variables' in self.context:
            return self.context['exposed_variables']
        return []


@dataclass
class OnStopContext:
    """Context for on_stop Hook - passed to handlers.

    This is the specialized context for on_stop hooks, containing
    all information about the explore block execution.

    Attributes:
        attempt: Current attempt number (1-indexed)
        stage: Execution stage (always "explore" for on_stop)
        answer: The generated answer from explore
        think: The thinking/reasoning process
        steps: Number of execution steps
        tool_calls: List of tool calls made during exploration
    """
    # Common fields (satisfies HookContextProtocol)
    attempt: int
    stage: str = "explore"

    # on_stop specific fields
    answer: str = ""
    think: str = ""
    steps: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary representation."""
        return asdict(self)


@dataclass
class HookResult:
    """Result from Hook execution.

    Attributes:
        score: Quality score between 0.0 and 1.0
        passed: Whether the verification passed (score >= threshold)
        feedback: Optional improvement suggestions
        retry: Whether to retry (defaults to not passed)
        breakdown: Optional score breakdown for debugging
        error: Error message if validation failed
        error_type: Type of error that occurred
        execution_status: Overall execution status
    """
    score: float
    passed: bool
    feedback: Optional[str] = None
    retry: bool = True
    breakdown: Optional[Dict[str, Any]] = None

    # Error handling fields
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_status: str = "success"

    def __post_init__(self):
        # Normalize score to 0-1 range
        self.score = max(0.0, min(1.0, self.score))

        # Default retry to not passed
        if self.retry is None:
            self.retry = not self.passed

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        result = {
            'score': self.score,
            'passed': self.passed,
            'retry': self.retry,
            'execution_status': self.execution_status,
        }
        if self.feedback:
            result['feedback'] = self.feedback
        if self.breakdown:
            result['breakdown'] = self.breakdown
        if self.error:
            result['error'] = self.error
            result['error_type'] = self.error_type
        return result


class HookError:
    """Hook error type constants."""
    VALIDATOR_ERROR = "validator_error"
    TIMEOUT = "timeout"
    INVALID_RESULT = "invalid_result"
    EXPRESSION_ERROR = "expression_error"
    AGENT_LOAD_ERROR = "agent_load_error"


class HookValidationError(Exception):
    """Exception raised when hook validation configuration is invalid.

    This error is raised for configuration errors that should stop execution,
    not for validation failures during runtime.
    """
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


def parse_hook_config(on_stop_value: Any) -> Optional[HookConfig]:
    """Parse on_stop parameter value into HookConfig.

    Supports multiple formats:
    - None: No hook configured
    - str: Simple expression handler
    - dict with 'handler' key: Full configuration
    - AgentRef: Agent reference

    Args:
        on_stop_value: The raw on_stop parameter value

    Returns:
        HookConfig if configured, None otherwise

    Raises:
        HookValidationError: If configuration is invalid
    """
    if on_stop_value is None:
        return None

    # Simple expression string
    if isinstance(on_stop_value, str):
        # Check if it's an agent reference
        if on_stop_value.startswith('@'):
            return HookConfig(handler=AgentRef(on_stop_value))
        return HookConfig(handler=on_stop_value)

    # AgentRef object
    if isinstance(on_stop_value, AgentRef):
        return HookConfig(handler=on_stop_value)

    # Full configuration dictionary
    if isinstance(on_stop_value, dict):
        handler = on_stop_value.get('handler')
        if handler is None:
            raise HookValidationError("HookConfig requires 'handler' field")

        # Parse handler
        if isinstance(handler, str) and handler.startswith('@'):
            handler = AgentRef(handler)
        elif isinstance(handler, dict) and 'path' in handler:
            handler = AgentRef(handler['path'])

        return HookConfig(
            handler=handler,
            threshold=on_stop_value.get('threshold', 0.5),
            max_retries=on_stop_value.get('max_retries', 0),
            model=on_stop_value.get('model'),
            context=on_stop_value.get('context'),
            llm_timeout=on_stop_value.get('llm_timeout', 30),
            agent_timeout=on_stop_value.get('agent_timeout', 60),
        )

    raise HookValidationError(f"Invalid on_stop configuration type: {type(on_stop_value)}")
