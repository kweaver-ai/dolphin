#!/usr/bin/env python3
"""Unit tests for expression_evaluator module."""

import unittest
import asyncio
from dolphin.core.hook.expression_evaluator import (
    ExpressionEvaluator,
    ExpressionError,
)


class TestExpressionEvaluator(unittest.TestCase):
    """Tests for ExpressionEvaluator class."""

    def test_simple_comparison_true(self):
        """Test simple comparison that evaluates to true."""
        evaluator = ExpressionEvaluator(
            expr="len($answer) > 10",
            context={"answer": "Hello World, this is a long answer"}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 1.0)

    def test_simple_comparison_false(self):
        """Test simple comparison that evaluates to false."""
        evaluator = ExpressionEvaluator(
            expr="len($answer) > 100",
            context={"answer": "Short"}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 0.0)

    def test_weighted_expression(self):
        """Test weighted expression calculation."""
        evaluator = ExpressionEvaluator(
            expr="0.5 * 0.8 + 0.5 * 0.6",
            context={}
        )
        score = evaluator.evaluate_sync()
        self.assertAlmostEqual(score, 0.7, places=5)

    def test_variable_substitution(self):
        """Test $variable syntax is properly handled."""
        evaluator = ExpressionEvaluator(
            expr="$steps >= 3",
            context={"steps": 5}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 1.0)

    def test_multiple_variables(self):
        """Test expression with multiple variables."""
        evaluator = ExpressionEvaluator(
            expr="len($answer) > 50 and $tool_calls >= 1",
            context={"answer": "A" * 60, "tool_calls": 2}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 1.0)

    def test_builtin_len_function(self):
        """Test len() function."""
        evaluator = ExpressionEvaluator(
            expr="len($answer)",
            context={"answer": "Hello"}
        )
        score = evaluator.evaluate_sync()
        # "Hello" has 5 chars, but normalized to 0-1
        self.assertEqual(score, 1.0)  # 5 > 1, so clamped to 1.0

    def test_builtin_min_function(self):
        """Test min() function."""
        evaluator = ExpressionEvaluator(
            expr="min(0.8, 0.6, 0.9)",
            context={}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 0.6)

    def test_builtin_max_function(self):
        """Test max() function."""
        evaluator = ExpressionEvaluator(
            expr="max(0.2, 0.7, 0.5)",
            context={}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 0.7)

    def test_builtin_abs_function(self):
        """Test abs() function."""
        evaluator = ExpressionEvaluator(
            expr="abs(-0.5)",
            context={}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 0.5)

    def test_boolean_and_operator(self):
        """Test 'and' operator."""
        evaluator = ExpressionEvaluator(
            expr="True and True",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

        evaluator = ExpressionEvaluator(
            expr="True and False",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 0.0)

    def test_boolean_or_operator(self):
        """Test 'or' operator."""
        evaluator = ExpressionEvaluator(
            expr="False or True",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

        evaluator = ExpressionEvaluator(
            expr="False or False",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 0.0)

    def test_boolean_not_operator(self):
        """Test 'not' operator."""
        evaluator = ExpressionEvaluator(
            expr="not False",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

    def test_arithmetic_operations(self):
        """Test arithmetic operations."""
        # Addition
        evaluator = ExpressionEvaluator(expr="0.3 + 0.4", context={})
        self.assertAlmostEqual(evaluator.evaluate_sync(), 0.7, places=5)

        # Subtraction
        evaluator = ExpressionEvaluator(expr="0.8 - 0.3", context={})
        self.assertAlmostEqual(evaluator.evaluate_sync(), 0.5, places=5)

        # Multiplication
        evaluator = ExpressionEvaluator(expr="0.5 * 0.6", context={})
        self.assertAlmostEqual(evaluator.evaluate_sync(), 0.3, places=5)

        # Division
        evaluator = ExpressionEvaluator(expr="0.8 / 2", context={})
        self.assertAlmostEqual(evaluator.evaluate_sync(), 0.4, places=5)

    def test_comparison_operators(self):
        """Test comparison operators."""
        tests = [
            ("5 > 3", 1.0),
            ("3 > 5", 0.0),
            ("5 >= 5", 1.0),
            ("5 < 3", 0.0),
            ("3 <= 3", 1.0),
            ("5 == 5", 1.0),
            ("5 != 3", 1.0),
        ]
        for expr, expected in tests:
            evaluator = ExpressionEvaluator(expr=expr, context={})
            self.assertEqual(evaluator.evaluate_sync(), expected, f"Failed for: {expr}")

    def test_ternary_expression(self):
        """Test ternary/conditional expression."""
        evaluator = ExpressionEvaluator(
            expr="0.9 if $answer else 0.1",
            context={"answer": "Hello"}
        )
        self.assertEqual(evaluator.evaluate_sync(), 0.9)

        evaluator = ExpressionEvaluator(
            expr="0.9 if $answer else 0.1",
            context={"answer": ""}
        )
        self.assertEqual(evaluator.evaluate_sync(), 0.1)

    def test_unknown_variable_raises_error(self):
        """Test unknown variable raises ExpressionError."""
        evaluator = ExpressionEvaluator(
            expr="$unknown_var > 0",
            context={}
        )
        with self.assertRaises(ExpressionError):
            evaluator.evaluate_sync()

    def test_unknown_function_raises_error(self):
        """Test unknown function raises ExpressionError."""
        evaluator = ExpressionEvaluator(
            expr="unknown_func($answer)",
            context={"answer": "test"}
        )
        with self.assertRaises(ExpressionError):
            evaluator.evaluate_sync()

    def test_syntax_error_raises_error(self):
        """Test syntax error raises ExpressionError."""
        with self.assertRaises(ExpressionError):
            ExpressionEvaluator(
                expr="((( unbalanced",
                context={}
            )

    def test_normalization_clamps_to_range(self):
        """Test values are clamped to 0-1 range."""
        # Value > 1
        evaluator = ExpressionEvaluator(expr="2.0", context={})
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

        # Value < 0
        evaluator = ExpressionEvaluator(expr="-0.5", context={})
        self.assertEqual(evaluator.evaluate_sync(), 0.0)

    def test_string_normalization(self):
        """Test string normalization (non-empty -> 1.0)."""
        evaluator = ExpressionEvaluator(expr="$answer", context={"answer": "hello"})
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

        evaluator = ExpressionEvaluator(expr="$answer", context={"answer": ""})
        self.assertEqual(evaluator.evaluate_sync(), 0.0)

    def test_async_evaluate(self):
        """Test async evaluate method."""
        async def run():
            evaluator = ExpressionEvaluator(
                expr="len($answer) > 5",
                context={"answer": "Hello World"}
            )
            return await evaluator.evaluate()

        score = asyncio.run(run())
        self.assertEqual(score, 1.0)

    def test_complex_expression(self):
        """Test complex real-world expression."""
        evaluator = ExpressionEvaluator(
            expr="0.5 * (len($answer) > 300) + 0.5 * ($tool_calls >= 1)",
            context={"answer": "A" * 350, "tool_calls": 2}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 1.0)

        # When answer is short
        evaluator = ExpressionEvaluator(
            expr="0.5 * (len($answer) > 300) + 0.5 * ($tool_calls >= 1)",
            context={"answer": "Short", "tool_calls": 2}
        )
        score = evaluator.evaluate_sync()
        self.assertEqual(score, 0.5)


class TestExpressionEdgeCases(unittest.TestCase):
    """Edge case tests for ExpressionEvaluator."""

    def test_empty_expression(self):
        """Test empty expression handling."""
        with self.assertRaises(ExpressionError):
            ExpressionEvaluator(expr="", context={})

    def test_whitespace_expression(self):
        """Test whitespace-only expression."""
        with self.assertRaises(ExpressionError):
            ExpressionEvaluator(expr="   ", context={})

    def test_list_literal(self):
        """Test list literal in expression."""
        evaluator = ExpressionEvaluator(
            expr="len([1, 2, 3])",
            context={}
        )
        self.assertEqual(evaluator.evaluate_sync(), 1.0)  # 3 clamped to 1.0

    def test_in_operator(self):
        """Test 'in' operator."""
        evaluator = ExpressionEvaluator(
            expr="'hello' in $answer",
            context={"answer": "hello world"}
        )
        self.assertEqual(evaluator.evaluate_sync(), 1.0)

        evaluator = ExpressionEvaluator(
            expr="'missing' in $answer",
            context={"answer": "hello world"}
        )
        self.assertEqual(evaluator.evaluate_sync(), 0.0)

    def test_division_by_zero_raises_error(self):
        """Test division by zero raises ExpressionError."""
        # Test basic division by zero
        evaluator = ExpressionEvaluator(
            expr="10 / 0",
            context={}
        )
        with self.assertRaises(ExpressionError) as cm:
            evaluator.evaluate_sync()
        self.assertIn("Division by zero", str(cm.exception))

    def test_division_by_zero_in_comparison_raises_error(self):
        """Test division by zero in comparison raises ExpressionError."""
        # This was the original bug: "10/0 >= 0.5" would evaluate to True
        evaluator = ExpressionEvaluator(
            expr="10 / 0 >= 0.5",
            context={}
        )
        with self.assertRaises(ExpressionError) as cm:
            evaluator.evaluate_sync()
        self.assertIn("Division by zero", str(cm.exception))

    def test_floor_division_by_zero_raises_error(self):
        """Test floor division by zero raises ExpressionError."""
        evaluator = ExpressionEvaluator(
            expr="10 // 0",
            context={}
        )
        with self.assertRaises(ExpressionError) as cm:
            evaluator.evaluate_sync()
        self.assertIn("Division by zero", str(cm.exception))

    def test_modulo_by_zero_raises_error(self):
        """Test modulo by zero raises ExpressionError."""
        evaluator = ExpressionEvaluator(
            expr="10 % 0",
            context={}
        )
        with self.assertRaises(ExpressionError) as cm:
            evaluator.evaluate_sync()
        self.assertIn("Modulo by zero", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
