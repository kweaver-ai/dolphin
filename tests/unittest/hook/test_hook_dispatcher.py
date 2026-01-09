#!/usr/bin/env python3
"""Unit tests for hook_dispatcher module."""

import unittest
import asyncio
from unittest.mock import MagicMock

from dolphin.core.context.variable_pool import VariablePool
from dolphin.core.hook.hook_types import (
    HookConfig,
    OnStopContext,
    HookResult,
    AgentRef,
    HookValidationError,
)
from dolphin.core.hook.hook_dispatcher import (
    HookDispatcher,
    FeedbackGenerator,
)


class TestFeedbackGenerator(unittest.TestCase):
    """Tests for FeedbackGenerator class."""

    def test_generate_basic_feedback(self):
        """Test basic feedback generation."""
        generator = FeedbackGenerator(
            handler="len($answer) > 100",
            score=0.3,
            threshold=0.7
        )
        feedback = generator.generate()
        self.assertIn("0.30", feedback)
        self.assertIn("0.70", feedback)

    def test_feedback_for_length_check(self):
        """Test feedback for answer length check."""
        generator = FeedbackGenerator(
            handler="len($answer) > 100",
            score=0.3,
            threshold=0.7
        )
        feedback = generator.generate()
        self.assertIn("short", feedback.lower())

    def test_feedback_for_tool_calls(self):
        """Test feedback for tool calls check."""
        generator = FeedbackGenerator(
            handler="$tool_calls >= 1",
            score=0.0,
            threshold=0.5
        )
        feedback = generator.generate()
        self.assertIn("tool", feedback.lower())


class TestHookDispatcher(unittest.TestCase):
    """Tests for HookDispatcher class."""

    def setUp(self):
        """Set up test fixtures."""
        self.variable_pool = VariablePool()
        self.variable_pool.set_var("test_var", "test_value")

    def test_dispatch_expression_pass(self):
        """Test dispatch with passing expression."""
        config = HookConfig(
            handler="len($answer) > 5",
            threshold=0.5
        )
        context = OnStopContext(
            attempt=1,
            answer="Hello World, this is a long answer"
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_dispatch_expression_fail(self):
        """Test dispatch with failing expression."""
        config = HookConfig(
            handler="len($answer) > 100",
            threshold=0.5
        )
        context = OnStopContext(
            attempt=1,
            answer="Short"
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.0)
        self.assertIsNotNone(result.feedback)

    def test_dispatch_with_threshold(self):
        """Test dispatch respects threshold."""
        config = HookConfig(
            handler="0.6",  # Direct score
            threshold=0.7
        )
        context = OnStopContext(attempt=1, answer="test")

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)  # 0.6 < 0.7
        self.assertEqual(result.score, 0.6)

        # With lower threshold
        config = HookConfig(handler="0.6", threshold=0.5)
        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )
        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)  # 0.6 >= 0.5

    def test_dispatch_expression_with_steps(self):
        """Test expression using steps variable."""
        config = HookConfig(
            handler="$steps >= 3",
            threshold=0.5
        )
        context = OnStopContext(
            attempt=1,
            answer="test",
            steps=5
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)

    def test_dispatch_expression_with_tool_calls(self):
        """Test expression using tool_calls count."""
        config = HookConfig(
            handler="$tool_calls >= 1",
            threshold=0.5
        )
        context = OnStopContext(
            attempt=1,
            answer="test",
            tool_calls=[{"name": "tool1"}, {"name": "tool2"}]
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_dispatch_invalid_expression(self):
        """Test dispatch with invalid expression raises error."""
        config = HookConfig(
            handler="invalid ++ syntax",
            threshold=0.5
        )
        context = OnStopContext(attempt=1, answer="test")

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        with self.assertRaises(HookValidationError):
            asyncio.run(dispatcher.dispatch())

    def test_dispatch_agent_without_runtime(self):
        """Test dispatch with agent handler requires runtime."""
        config = HookConfig(
            handler=AgentRef("@verifier"),
            threshold=0.5
        )
        context = OnStopContext(attempt=1, answer="test")

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool,
            runtime=None  # No runtime
        )

        with self.assertRaises(HookValidationError):
            asyncio.run(dispatcher.dispatch())

    def test_dispatch_weighted_expression(self):
        """Test dispatch with weighted expression."""
        config = HookConfig(
            handler="0.5 * (len($answer) > 10) + 0.5 * ($steps >= 1)",
            threshold=0.5
        )
        context = OnStopContext(
            attempt=1,
            answer="Hello World!",  # > 10 chars
            steps=2
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_dispatch_partial_weighted_expression(self):
        """Test dispatch with partially satisfied weighted expression."""
        config = HookConfig(
            handler="0.5 * (len($answer) > 100) + 0.5 * ($steps >= 1)",
            threshold=0.7
        )
        context = OnStopContext(
            attempt=1,
            answer="Short",  # < 100 chars
            steps=2
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = asyncio.run(dispatcher.dispatch())
        self.assertFalse(result.passed)  # 0.5 < 0.7
        self.assertEqual(result.score, 0.5)

    def test_build_eval_context(self):
        """Test _build_eval_context extracts correct fields."""
        config = HookConfig(handler="True", threshold=0.5)
        context = OnStopContext(
            attempt=2,
            answer="test answer",
            think="thinking process",
            steps=5,
            tool_calls=[{"name": "tool1"}]
        )

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        eval_ctx = dispatcher._build_eval_context()
        self.assertEqual(eval_ctx["answer"], "test answer")
        self.assertEqual(eval_ctx["think"], "thinking process")
        self.assertEqual(eval_ctx["steps"], 5)
        self.assertEqual(eval_ctx["tool_calls"], 1)  # Count, not list
        self.assertEqual(eval_ctx["attempt"], 2)

    def test_build_result_with_feedback(self):
        """Test _build_result generates feedback when failed."""
        config = HookConfig(handler="len($answer) > 100", threshold=0.7)
        context = OnStopContext(attempt=1, answer="test")

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = dispatcher._build_result(0.3)
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.feedback)
        self.assertTrue(result.retry)

    def test_build_result_no_feedback_when_passed(self):
        """Test _build_result has no feedback when passed."""
        config = HookConfig(handler="True", threshold=0.5)
        context = OnStopContext(attempt=1, answer="test")

        dispatcher = HookDispatcher(
            config=config,
            context=context,
            variable_pool=self.variable_pool
        )

        result = dispatcher._build_result(0.8)
        self.assertTrue(result.passed)
        self.assertIsNone(result.feedback)
        self.assertFalse(result.retry)


class TestHookDispatcherAgentResult(unittest.TestCase):
    """Tests for HookDispatcher agent result parsing."""

    def setUp(self):
        """Set up test fixtures."""
        self.variable_pool = VariablePool()
        self.config = HookConfig(handler="True", threshold=0.5)
        self.context = OnStopContext(attempt=1, answer="test")
        self.dispatcher = HookDispatcher(
            config=self.config,
            context=self.context,
            variable_pool=self.variable_pool
        )

    def test_parse_agent_result_full_dict(self):
        """Test parsing full HookResult dict."""
        result = self.dispatcher._parse_agent_result({
            "score": 0.85,
            "passed": True,
            "feedback": "Good job!",
            "breakdown": {"accuracy": 0.9}
        })
        self.assertEqual(result.score, 0.85)
        self.assertTrue(result.passed)
        self.assertEqual(result.feedback, "Good job!")
        self.assertEqual(result.breakdown, {"accuracy": 0.9})

    def test_parse_agent_result_minimal_dict(self):
        """Test parsing minimal dict with just score."""
        result = self.dispatcher._parse_agent_result({"score": 0.6})
        self.assertEqual(result.score, 0.6)
        self.assertTrue(result.passed)  # 0.6 >= 0.5

    def test_parse_agent_result_numeric(self):
        """Test parsing simple numeric result."""
        result = self.dispatcher._parse_agent_result(0.75)
        self.assertEqual(result.score, 0.75)
        self.assertTrue(result.passed)

    def test_parse_agent_result_int(self):
        """Test parsing integer result."""
        result = self.dispatcher._parse_agent_result(1)
        self.assertEqual(result.score, 1.0)

    def test_parse_agent_result_invalid(self):
        """Test parsing invalid result returns error result."""
        result = self.dispatcher._parse_agent_result("invalid")
        self.assertEqual(result.score, 0.0)
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.error)

    def test_parse_agent_result_nested_answer(self):
        """Test parsing nested answer structure from explore block."""
        result = self.dispatcher._parse_agent_result({
            "answer": {
                "score": 0.9,
                "passed": True
            }
        })
        self.assertEqual(result.score, 0.9)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
