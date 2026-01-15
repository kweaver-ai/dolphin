"""Hook Module - Hook-based Verify System

This module provides the Hook-based verify functionality for Dolphin Language.

Key Components:
- HookConfig: Configuration for Hook behavior
- OnStopContext: Context for on_stop hooks
- HookResult: Standardized verification result
- HookDispatcher: Core dispatching logic
- ExpressionEvaluator: Safe expression evaluation
- IsolatedVariablePool: Read-only variable pool for agents

Example Usage:
    ```python
    from dolphin.core.hook import (
        HookConfig,
        OnStopContext,
        HookDispatcher,
        parse_hook_config,
    )

    # Parse hook config from parameters
    config = parse_hook_config("len($answer) > 100")

    # Create context from explore output
    context = OnStopContext(
        attempt=1,
        answer="Hello World",
        think="...",
        steps=3,
        tool_calls=[],
    )

    # Dispatch and get result
    dispatcher = HookDispatcher(config, context, variable_pool)
    result = await dispatcher.dispatch()

    if result.passed:
        print(f"Verification passed with score: {result.score}")
    else:
        print(f"Verification failed: {result.feedback}")
    ```
"""

from dolphin.core.hook.hook_types import (
    HookConfig,
    OnStopContext,
    HookResult,
    HookContextProtocol,
    AgentRef,
    HookError,
    HookValidationError,
    parse_hook_config,
)

from dolphin.core.hook.hook_dispatcher import (
    HookDispatcher,
    FeedbackGenerator,
)

from dolphin.core.hook.expression_evaluator import (
    ExpressionEvaluator,
    ExpressionError,
)

from dolphin.core.hook.isolated_variable_pool import (
    IsolatedVariablePool,
    VariableAccessError,
)

__all__ = [
    # Types
    'HookConfig',
    'OnStopContext',
    'HookResult',
    'HookContextProtocol',
    'AgentRef',
    'HookError',
    'HookValidationError',

    # Functions
    'parse_hook_config',

    # Dispatcher
    'HookDispatcher',
    'FeedbackGenerator',

    # Expression
    'ExpressionEvaluator',
    'ExpressionError',

    # Variable Pool
    'IsolatedVariablePool',
    'VariableAccessError',
]
