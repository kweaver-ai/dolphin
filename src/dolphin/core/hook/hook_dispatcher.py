"""Hook Dispatcher Module

This module provides the core Hook dispatching logic.

Key Responsibilities:
- Dispatch to different handler types (expression, agent)
- Build evaluation context
- Standardize HookResult
- Handle errors gracefully
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Dict, Optional, TYPE_CHECKING

from dolphin.core.hook.hook_types import (
    HookConfig,
    HookResult,
    HookError,
    HookValidationError,
    HookContextProtocol,
    AgentRef,
)
from dolphin.core.hook.expression_evaluator import ExpressionEvaluator, ExpressionError
from dolphin.core.hook.isolated_variable_pool import IsolatedVariablePool
from dolphin.core.logging.logger import get_logger

if TYPE_CHECKING:
    from dolphin.core.context.variable_pool import VariablePool

logger = get_logger("hook.dispatcher")


class FeedbackGenerator:
    """Generate feedback messages based on verification results."""

    def __init__(
        self,
        handler: str,
        score: float,
        threshold: float,
    ):
        self.handler = handler
        self.score = score
        self.threshold = threshold

    def generate(self) -> str:
        """Generate feedback message for failed verification.

        Returns:
            Formatted feedback string
        """
        feedback_parts = [
            f"[Score: {self.score:.2f}, Target: {self.threshold:.2f}]",
            "Please improve your answer based on the following feedback:",
        ]

        # Analyze expression to provide specific feedback
        if isinstance(self.handler, str):
            specific_feedback = self._analyze_expression()
            if specific_feedback:
                feedback_parts.append(specific_feedback)

        return "\n".join(feedback_parts)

    def _analyze_expression(self) -> str:
        """Analyze expression to provide specific feedback."""
        handler = self.handler

        if 'len($answer)' in handler or 'len(answer)' in handler:
            return "- Your answer may be too short. Please provide more detailed content."

        if '$tool_calls' in handler or 'tool_calls' in handler:
            return "- Please use tools to gather real data instead of making assumptions."

        if '$steps' in handler or 'steps' in handler:
            return "- Please show more reasoning steps in your analysis."

        return ""


class HookDispatcher:
    """Hook Dispatcher - handles different types of Hook handlers.

    Supports:
    - Expression handlers: Evaluate Python-like expressions
    - Agent handlers: Execute verification agents (.dph files)

    Example:
        ```python
        dispatcher = HookDispatcher(
            config=HookConfig(handler="len($answer) > 100", threshold=0.7),
            context=OnStopContext(answer="Hello", attempt=1),
            variable_pool=context.variable_pool
        )
        result = await dispatcher.dispatch()
        ```
    """

    def __init__(
        self,
        config: HookConfig,
        context: HookContextProtocol,
        variable_pool: VariablePool,
        runtime: Any = None,
    ):
        """Initialize dispatcher.

        Args:
            config: Hook configuration
            context: Hook context (OnStopContext for on_stop hooks)
            variable_pool: Variable pool for variable access
            runtime: Optional runtime for agent execution
        """
        self.config = config
        self.context = context
        self.variable_pool = variable_pool
        self.runtime = runtime

    async def dispatch(self) -> HookResult:
        """Dispatch to appropriate handler and return standardized result.

        Returns:
            HookResult with score, passed status, and optional feedback

        Raises:
            HookValidationError: For configuration errors (should stop execution)
        """
        handler = self.config.handler

        try:
            # 1. Determine handler type and execute
            if isinstance(handler, str):
                # String expression
                score = await self._eval_expression(handler)
                return self._build_result(score)

            elif isinstance(handler, AgentRef):
                # Agent reference - execute verification agent
                return await self._call_agent(handler)

            else:
                raise HookValidationError(f"Unknown handler type: {type(handler)}")

        except asyncio.TimeoutError as e:
            # Timeout error
            logger.error(f"Hook handler timeout: {handler}")
            return HookResult(
                score=0.0,
                passed=False,
                feedback=None,
                retry=False,  # Don't retry on system error
                error=f"Handler execution timeout after {self.config.agent_timeout}s",
                error_type=HookError.TIMEOUT,
                execution_status="timeout",
            )

        except ExpressionError as e:
            # Expression syntax/evaluation error - raise to stop execution
            raise HookValidationError(
                f"Invalid hook expression: {handler}",
                original_error=e,
            ) from e

        except HookValidationError:
            # Re-raise validation errors
            raise

        except FileNotFoundError as e:
            # Agent file not found - raise to stop execution
            raise HookValidationError(
                f"Verifier agent not found: {handler}",
                original_error=e,
            ) from e

        except Exception as e:
            # Other errors - degrade gracefully
            logger.error(
                f"Hook handler failed: {handler}",
                exc_info=True,
            )
            return HookResult(
                score=0.0,
                passed=False,
                feedback=None,
                retry=False,  # Don't retry on validator error
                error=str(e),
                error_type=HookError.VALIDATOR_ERROR,
                execution_status="validator_error",
            )

    async def _eval_expression(self, expr: str) -> float:
        """Evaluate expression handler.

        Args:
            expr: Expression string

        Returns:
            Score between 0.0 and 1.0
        """
        eval_context = self._build_eval_context()
        evaluator = ExpressionEvaluator(
            expr=expr,
            context=eval_context,
            model=self.config.model,
        )
        return await evaluator.evaluate()

    async def _call_agent(self, agent_ref: AgentRef) -> HookResult:
        """Execute verification agent.

        Args:
            agent_ref: Reference to the verification agent

        Returns:
            HookResult from agent execution
        """
        if self.runtime is None:
            raise HookValidationError(
                "Runtime is required for agent-based verification"
            )

        try:
            # Load .dph file
            agent = await self.runtime.load_agent(agent_ref.path)
        except FileNotFoundError:
            raise  # Re-raise for dispatch() to handle
        except Exception as e:
            raise HookValidationError(
                f"Failed to load verifier agent: {agent_ref.path}"
            ) from e

        try:
            # Create isolated variable pool
            isolated_pool = self._create_isolated_variable_pool()

            # Inject hook context
            isolated_pool.set('_hook_context', asdict(self.context))

            # Set agent's variable pool
            agent.variable_pool = isolated_pool

            # Execute agent with timeout
            result = await asyncio.wait_for(
                agent.execute(),
                timeout=self.config.agent_timeout,
            )

            # Parse agent result
            return self._parse_agent_result(result)

        except asyncio.TimeoutError:
            raise  # Re-raise for dispatch() to handle

        except Exception as e:
            logger.error(
                f"Verifier agent {agent_ref.path} failed",
                exc_info=True,
            )
            raise

        finally:
            # Cleanup agent resources
            if 'agent' in dir() and hasattr(agent, 'cleanup'):
                await agent.cleanup()

    def _create_isolated_variable_pool(self) -> IsolatedVariablePool:
        """Create isolated variable pool for agent execution.

        Returns:
            IsolatedVariablePool with read-only access
        """
        exposed_vars = self.config.exposed_variables

        return IsolatedVariablePool(
            parent=self.variable_pool,
            read_only=True,
            exposed_variables=exposed_vars if exposed_vars else None,
        )

    def _build_eval_context(self) -> Dict[str, Any]:
        """Build context dictionary for expression evaluation.

        Returns:
            Dictionary with context fields accessible in expressions
        """
        # Get context as dict
        ctx_dict = self.context.to_dict()

        # Build evaluation context
        eval_ctx = {
            'answer': ctx_dict.get('answer', ''),
            'think': ctx_dict.get('think', ''),
            'steps': ctx_dict.get('steps', 0),
            'tool_calls': len(ctx_dict.get('tool_calls', [])),
            'attempt': ctx_dict.get('attempt', 1),
        }

        return eval_ctx

    def _build_result(self, score: float) -> HookResult:
        """Build standardized HookResult from score.

        Args:
            score: Evaluation score (0.0 to 1.0)

        Returns:
            HookResult with passed status and optional feedback
        """
        passed = score >= self.config.threshold

        # Generate feedback if not passed
        feedback = None
        if not passed:
            generator = FeedbackGenerator(
                handler=self.config.handler if isinstance(self.config.handler, str) else str(self.config.handler),
                score=score,
                threshold=self.config.threshold,
            )
            feedback = generator.generate()

        return HookResult(
            score=score,
            passed=passed,
            feedback=feedback,
            retry=not passed,
            breakdown=None,
        )

    def _parse_agent_result(self, result: Any) -> HookResult:
        """Parse verification agent result into HookResult.

        Supports:
        - Full HookResult dict: {"score": 0.85, "passed": true, ...}
        - Simple numeric: 0.85

        Args:
            result: Agent execution result

        Returns:
            Parsed HookResult
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for score field
            if 'score' in result:
                score = float(result['score'])
                passed = result.get('passed', score >= self.config.threshold)

                return HookResult(
                    score=score,
                    passed=passed,
                    feedback=result.get('feedback'),
                    retry=result.get('retry', not passed),
                    breakdown=result.get('breakdown'),
                )

            # Check for nested answer structure (from explore block)
            if 'answer' in result:
                answer = result['answer']
                if isinstance(answer, dict) and 'score' in answer:
                    return self._parse_agent_result(answer)

        # Handle numeric result
        if isinstance(result, (int, float)):
            return self._build_result(float(result))

        # Invalid result format
        logger.warning(f"Invalid agent result format: {type(result)}")
        return HookResult(
            score=0.0,
            passed=False,
            feedback="Verification agent returned invalid result format",
            retry=False,
            error="Invalid result format",
            error_type=HookError.INVALID_RESULT,
            execution_status="validator_error",
        )
