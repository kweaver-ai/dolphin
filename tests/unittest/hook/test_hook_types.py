#!/usr/bin/env python3
"""Unit tests for hook_types module."""

import unittest
from dolphin.core.hook.hook_types import (
    HookConfig,
    OnStopContext,
    HookResult,
    AgentRef,
    HookError,
    HookValidationError,
    parse_hook_config,
)


class TestAgentRef(unittest.TestCase):
    """Tests for AgentRef class."""

    def test_agent_ref_with_at_prefix(self):
        """Test AgentRef removes @ prefix."""
        ref = AgentRef("@verifier")
        self.assertEqual(ref.path, "verifier.dph")

    def test_agent_ref_without_at_prefix(self):
        """Test AgentRef works without @ prefix."""
        ref = AgentRef("verifier")
        self.assertEqual(ref.path, "verifier.dph")

    def test_agent_ref_with_dph_extension(self):
        """Test AgentRef keeps existing .dph extension."""
        ref = AgentRef("@verifier.dph")
        self.assertEqual(ref.path, "verifier.dph")


class TestHookConfig(unittest.TestCase):
    """Tests for HookConfig class."""

    def test_default_values(self):
        """Test default values are set correctly."""
        config = HookConfig(handler="len($answer) > 10")
        self.assertEqual(config.threshold, 0.5)
        self.assertEqual(config.max_retries, 0)
        self.assertIsNone(config.model)
        self.assertEqual(config.llm_timeout, 30)
        self.assertEqual(config.agent_timeout, 60)

    def test_threshold_validation(self):
        """Test threshold must be between 0 and 1."""
        with self.assertRaises(ValueError):
            HookConfig(handler="test", threshold=1.5)
        with self.assertRaises(ValueError):
            HookConfig(handler="test", threshold=-0.1)

    def test_max_retries_validation(self):
        """Test max_retries must be non-negative and <= 10."""
        with self.assertRaises(ValueError):
            HookConfig(handler="test", max_retries=-1)
        with self.assertRaises(ValueError):
            HookConfig(handler="test", max_retries=11)

    def test_exposed_variables_property(self):
        """Test exposed_variables property extraction."""
        config = HookConfig(
            handler="test",
            context={"exposed_variables": ["$datasources", "$config"]}
        )
        self.assertEqual(config.exposed_variables, ["$datasources", "$config"])

    def test_exposed_variables_empty(self):
        """Test exposed_variables returns empty list when not configured."""
        config = HookConfig(handler="test")
        self.assertEqual(config.exposed_variables, [])


class TestOnStopContext(unittest.TestCase):
    """Tests for OnStopContext class."""

    def test_to_dict(self):
        """Test context conversion to dictionary."""
        context = OnStopContext(
            attempt=1,
            answer="Hello World",
            think="Thinking process",
            steps=3,
            tool_calls=[{"name": "test_tool"}]
        )
        d = context.to_dict()
        self.assertEqual(d["attempt"], 1)
        self.assertEqual(d["answer"], "Hello World")
        self.assertEqual(d["think"], "Thinking process")
        self.assertEqual(d["steps"], 3)
        self.assertEqual(d["stage"], "explore")
        self.assertEqual(len(d["tool_calls"]), 1)

    def test_default_values(self):
        """Test default values in OnStopContext."""
        context = OnStopContext(attempt=1)
        self.assertEqual(context.stage, "explore")
        self.assertEqual(context.answer, "")
        self.assertEqual(context.think, "")
        self.assertEqual(context.steps, 0)
        self.assertEqual(context.tool_calls, [])


class TestHookResult(unittest.TestCase):
    """Tests for HookResult class."""

    def test_score_normalization(self):
        """Test score is normalized to 0-1 range."""
        result = HookResult(score=1.5, passed=True)
        self.assertEqual(result.score, 1.0)

        result = HookResult(score=-0.5, passed=False)
        self.assertEqual(result.score, 0.0)

    def test_retry_default(self):
        """Test retry defaults to not passed."""
        result = HookResult(score=0.5, passed=True, retry=None)
        self.assertFalse(result.retry)

        result = HookResult(score=0.3, passed=False, retry=None)
        self.assertTrue(result.retry)

    def test_to_dict(self):
        """Test result conversion to dictionary."""
        result = HookResult(
            score=0.85,
            passed=True,
            feedback="Good job!",
            breakdown={"accuracy": 0.9}
        )
        d = result.to_dict()
        self.assertEqual(d["score"], 0.85)
        self.assertTrue(d["passed"])
        self.assertEqual(d["feedback"], "Good job!")
        self.assertEqual(d["breakdown"], {"accuracy": 0.9})

    def test_to_dict_with_error(self):
        """Test result conversion includes error info."""
        result = HookResult(
            score=0.0,
            passed=False,
            error="Timeout",
            error_type=HookError.TIMEOUT,
            execution_status="timeout"
        )
        d = result.to_dict()
        self.assertEqual(d["error"], "Timeout")
        self.assertEqual(d["error_type"], HookError.TIMEOUT)
        self.assertEqual(d["execution_status"], "timeout")


class TestParseHookConfig(unittest.TestCase):
    """Tests for parse_hook_config function."""

    def test_none_returns_none(self):
        """Test None input returns None."""
        self.assertIsNone(parse_hook_config(None))

    def test_simple_expression(self):
        """Test simple expression string."""
        config = parse_hook_config("len($answer) > 100")
        self.assertIsInstance(config.handler, str)
        self.assertEqual(config.handler, "len($answer) > 100")

    def test_agent_reference_string(self):
        """Test agent reference string starting with @."""
        config = parse_hook_config("@verifier")
        self.assertIsInstance(config.handler, AgentRef)
        self.assertEqual(config.handler.path, "verifier.dph")

    def test_full_config_dict(self):
        """Test full configuration dictionary."""
        config = parse_hook_config({
            "handler": "len($answer) > 100",
            "threshold": 0.8,
            "max_retries": 2,
            "model": "v3-mini"
        })
        self.assertEqual(config.handler, "len($answer) > 100")
        self.assertEqual(config.threshold, 0.8)
        self.assertEqual(config.max_retries, 2)
        self.assertEqual(config.model, "v3-mini")

    def test_dict_with_agent_handler(self):
        """Test dict config with agent reference."""
        config = parse_hook_config({
            "handler": "@verifier",
            "threshold": 0.7
        })
        self.assertIsInstance(config.handler, AgentRef)
        self.assertEqual(config.threshold, 0.7)

    def test_invalid_dict_missing_handler(self):
        """Test dict without handler raises error."""
        with self.assertRaises(HookValidationError):
            parse_hook_config({"threshold": 0.5})

    def test_invalid_type_raises_error(self):
        """Test invalid type raises error."""
        with self.assertRaises(HookValidationError):
            parse_hook_config(123)


if __name__ == "__main__":
    unittest.main()
