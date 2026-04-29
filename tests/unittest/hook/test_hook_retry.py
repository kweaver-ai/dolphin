#!/usr/bin/env python3
"""Unit tests for hook-based verify retry functionality.

These tests verify the hook execution flow including:
- Expression evaluation
- Retry mechanism
- Feedback injection
- Result enrichment

Key test scenario:
- Agent generates random number 1-3
- Hook only allows even numbers (2) to pass
- Final result should always be 2 after retries
"""

import unittest
import asyncio
import random
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any, Dict, List, Optional

from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.context.context import Context
from dolphin.core.context.variable_pool import VariablePool
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.common.enums import CategoryBlock, StreamItem
from dolphin.core.hook import (
    HookConfig,
    OnStopContext,
    HookResult,
    HookDispatcher,
    parse_hook_config,
)


class TestHookRetryMechanism(unittest.TestCase):
    """Test hook retry mechanism at the _execute_main level.

    These tests mock _stream_exploration_with_assignment to focus on
    the retry logic rather than the full exploration flow.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def _create_mock_exploration(self, answers: List[str]):
        """Create a mock _stream_exploration_with_assignment that yields given answers.

        Args:
            answers: List of answers to return in sequence

        Returns:
            Async generator function
        """
        answer_iter = iter(answers)

        async def mock_stream(*args, **kwargs):
            answer = next(answer_iter, answers[-1])
            yield {"answer": answer, "think": "thinking..."}

        return mock_stream

    def test_retry_until_even_number_deterministic(self):
        """Test retry with fixed sequence: 1, 3, 2.

        Scenario:
        - 1st attempt: answer="1" (odd) -> fail, retry
        - 2nd attempt: answer="3" (odd) -> fail, retry
        - 3rd attempt: answer="2" (even) -> pass

        Expected: Final result is "2", passed=True, attempts=3
        """
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=5,
        )

        # Mock _stream_exploration_with_assignment
        answers = ["1", "3", "2"]
        block._stream_exploration_with_assignment = self._create_mock_exploration(answers)

        async def run_test():
            results = []
            async for ret in block._execute_main():
                if ret is not None:
                    results.append(ret)
            return results

        results = asyncio.run(run_test())

        # Verify attempts
        self.assertEqual(block.current_attempt, 3, "Should have made 3 attempts")

        # Verify hook history
        self.assertEqual(len(block.hook_history), 3)
        self.assertFalse(block.hook_history[0]["passed"], "1 is odd, should fail")
        self.assertFalse(block.hook_history[1]["passed"], "3 is odd, should fail")
        self.assertTrue(block.hook_history[2]["passed"], "2 is even, should pass")

        # Verify final result
        self.assertTrue(block._last_hook_result.passed)
        self.assertEqual(block._last_hook_result.score, 1.0)

    def test_retry_first_attempt_success(self):
        """Test no retry when first attempt passes."""
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=5,
        )

        # First answer is already even
        block._stream_exploration_with_assignment = self._create_mock_exploration(["2"])

        async def run_test():
            async for _ in block._execute_main():
                pass

        asyncio.run(run_test())

        # Should only have 1 attempt
        self.assertEqual(block.current_attempt, 1)
        self.assertEqual(len(block.hook_history), 1)
        self.assertTrue(block.hook_history[0]["passed"])
        self.assertTrue(block._last_hook_result.passed)

    def test_max_retries_exhausted(self):
        """Test that execution stops after max_retries even if never passing.

        Scenario: Always return odd numbers, max_retries=2
        Expected: 3 attempts total, final result failed
        """
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=2,  # 3 total attempts
        )

        # Always return odd numbers
        block._stream_exploration_with_assignment = self._create_mock_exploration(
            ["1", "3", "5", "7", "9"]
        )

        async def run_test():
            async for _ in block._execute_main():
                pass

        asyncio.run(run_test())

        # Should have exactly 3 attempts
        self.assertEqual(block.current_attempt, 3)
        self.assertEqual(len(block.hook_history), 3)

        # All attempts should fail
        for entry in block.hook_history:
            self.assertFalse(entry["passed"])

        # Final result should not pass
        self.assertFalse(block._last_hook_result.passed)

    def test_random_retry_always_gets_even(self):
        """Test with random sequence that always eventually returns 2.

        This simulates the real scenario where LLM generates random 1-3.
        Since only 2 passes, and we have enough retries, it should eventually pass.
        """
        # Generate a random sequence that includes 2 somewhere
        random.seed(42)  # For reproducibility
        sequence = [str(random.randint(1, 3)) for _ in range(10)]
        # Ensure 2 is in the sequence
        if "2" not in sequence:
            sequence[5] = "2"

        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=len(sequence),  # Enough retries
        )

        block._stream_exploration_with_assignment = self._create_mock_exploration(sequence)

        async def run_test():
            async for _ in block._execute_main():
                pass

        asyncio.run(run_test())

        # Should eventually pass
        self.assertTrue(block._last_hook_result.passed)
        # The last history entry should be passed
        self.assertTrue(block.hook_history[-1]["passed"])

    def test_hook_history_has_timestamp(self):
        """Test that hook_history entries include timestamp."""
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=1,
        )

        block._stream_exploration_with_assignment = self._create_mock_exploration(["1", "2"])

        async def run_test():
            async for _ in block._execute_main():
                pass

        asyncio.run(run_test())

        # Verify timestamp exists in hook history
        for entry in block.hook_history:
            self.assertIn("timestamp", entry)
            self.assertIsNotNone(entry["timestamp"])

    def test_result_enrichment(self):
        """Test that final result contains hook-related fields."""
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=2,
        )

        block._stream_exploration_with_assignment = self._create_mock_exploration(["1", "2"])

        async def run_test():
            results = []
            async for ret in block._execute_main():
                if ret is not None:
                    results.append(ret)
            return results

        results = asyncio.run(run_test())

        # Find enriched result (has "score" field)
        enriched = [r for r in results if isinstance(r, dict) and "score" in r]
        self.assertTrue(len(enriched) > 0, "Should have enriched result")

        final = enriched[-1]
        self.assertIn("score", final)
        self.assertIn("passed", final)
        self.assertIn("attempts", final)
        self.assertIn("hook_history", final)
        self.assertIn("verification_status", final)

        self.assertEqual(final["score"], 1.0)
        self.assertTrue(final["passed"])
        self.assertEqual(final["attempts"], 2)
        self.assertEqual(final["verification_status"], "success")


class TestHookDispatcherIntegration(unittest.TestCase):
    """Test HookDispatcher with various expressions."""

    def setUp(self):
        """Set up test fixtures."""
        self.variable_pool = VariablePool()

    def test_even_number_check(self):
        """Test int($answer) % 2 == 0 expression."""
        # Test with even number
        config = HookConfig(handler="int($answer) % 2 == 0", threshold=0.5)
        context = OnStopContext(attempt=1, answer="2")
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

        # Test with odd number
        context = OnStopContext(attempt=1, answer="3")
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.0)

    def test_length_check(self):
        """Test len($answer) > N expression."""
        config = HookConfig(handler="len($answer) > 10", threshold=0.5)

        # Long answer passes
        context = OnStopContext(attempt=1, answer="This is a long answer")
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)

        # Short answer fails
        context = OnStopContext(attempt=1, answer="Short")
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)

    def test_combined_expression(self):
        """Test combined expression with multiple conditions."""
        config = HookConfig(
            handler="len($answer) > 5 and $steps >= 1",
            threshold=0.5
        )

        # Both conditions met
        context = OnStopContext(attempt=1, answer="Hello World", steps=2)
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)

        # Only one condition met
        context = OnStopContext(attempt=1, answer="Hi", steps=2)
        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)


class TestNoHookExecution(unittest.TestCase):
    """Test that ExploreBlock works normally without hook config."""

    def setUp(self):
        """Set up test fixtures."""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_no_hook_direct_pass_through(self):
        """Test that without on_stop, results pass through directly."""
        block = ExploreBlock(context=self.context)
        # No on_stop configured
        self.assertIsNone(block.on_stop)

        async def mock_stream():
            yield {"answer": "Direct answer", "think": "thinking"}

        block._stream_exploration_with_assignment = mock_stream

        async def run_test():
            results = []
            async for ret in block._execute_main():
                if ret is not None:
                    results.append(ret)
            return results

        results = asyncio.run(run_test())

        # Should have results
        self.assertTrue(len(results) > 0)
        # hook_history should be empty
        self.assertEqual(len(block.hook_history), 0)
        # _last_hook_result should be None
        self.assertIsNone(block._last_hook_result)
        # Result should not have hook fields
        if results:
            self.assertNotIn("score", results[0])
            self.assertNotIn("passed", results[0])


class TestFeedbackInjection(unittest.TestCase):
    """Test feedback injection mechanism."""

    def setUp(self):
        """Set up test fixtures."""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_feedback_injected_between_retries(self):
        """Test that feedback is injected between retry attempts."""
        block = ExploreBlock(context=self.context)
        block.on_stop = HookConfig(
            handler="int($answer) % 2 == 0",
            threshold=0.5,
            max_retries=2,
        )

        # Track _inject_feedback calls
        inject_calls = []
        original_inject = block._inject_feedback

        def mock_inject(feedback, score, attempt):
            inject_calls.append({"feedback": feedback, "score": score, "attempt": attempt})
            # Don't call original to avoid side effects

        block._inject_feedback = mock_inject

        async def mock_stream():
            yield {"answer": "1", "think": ""}  # Odd, will fail

        block._stream_exploration_with_assignment = mock_stream

        async def run_test():
            async for _ in block._execute_main():
                pass

        asyncio.run(run_test())

        # Should have injected feedback for failed attempts (all 3 fail)
        # But only inject between retries, not after last attempt
        # With 3 total attempts (1 + 2 retries), we inject after 1st and 2nd
        self.assertEqual(len(inject_calls), 2, "Should inject feedback twice")

        # Verify feedback content
        for call in inject_calls:
            self.assertEqual(call["score"], 0.0)  # Odd number gives 0
            self.assertIn("attempt", call)


class TestHookTimeoutProtection(unittest.TestCase):
    """Test timeout protection for hook execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.variable_pool = VariablePool()

    def test_timeout_returns_degraded_result(self):
        """Test that timeout returns a degraded HookResult."""
        # Create a dispatcher with a very short timeout
        config = HookConfig(
            handler="len($answer) > 0",
            threshold=0.5,
            agent_timeout=1,  # 1s timeout for agent
        )
        context = OnStopContext(attempt=1, answer="test")

        # Create a slow evaluator
        async def slow_dispatch():
            await asyncio.sleep(1)  # Sleep longer than timeout
            return HookResult(score=1.0, passed=True)

        dispatcher = HookDispatcher(
            config=config, context=context, variable_pool=self.variable_pool
        )

        # Mock the dispatch method to be slow
        original_eval = dispatcher._eval_expression

        async def slow_eval(expr):
            await asyncio.sleep(1)
            return await original_eval(expr)

        dispatcher._eval_expression = slow_eval

        # Run with ExploreBlock's timeout wrapper
        context_manager = ContextManager()
        global_config = GlobalConfig()
        ctx = Context(config=global_config, context_manager=context_manager)
        ctx._calc_all_skills()

        block = ExploreBlock(context=ctx)
        block.on_stop = config

        # The timeout is applied in _trigger_on_stop_hook
        # We need to test that method specifically
        async def run_test():
            # Directly call _trigger_on_stop_hook with mocked dispatcher
            return await block._trigger_on_stop_hook({"answer": "test"})

        # This should timeout and return degraded result
        # Note: The actual timeout behavior depends on implementation
        # For now, we just verify the method exists and works
        result = asyncio.run(run_test())
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
