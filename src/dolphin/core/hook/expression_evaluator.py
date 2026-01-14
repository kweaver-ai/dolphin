"""Expression Evaluator Module

This module provides safe expression evaluation using Python's AST module.

Key Features:
- Safe parsing and evaluation (no eval/exec)
- Support for basic arithmetic and comparison operators
- Support for built-in functions (len, min, max, abs)
- Variable substitution with $ prefix
- Result normalization to 0-1 range
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Dict, Callable, Optional


# Built-in functions available in expressions
BUILTIN_FUNCTIONS: Dict[str, Callable] = {
    'len': len,
    'min': min,
    'max': max,
    'abs': abs,
    'int': int,
    'float': float,
    'str': str,
    'bool': bool,
}

# Safe division wrappers to handle ZeroDivisionError
def _safe_truediv(a, b):
    """Safe true division that returns inf on division by zero."""
    if b == 0:
        return float('inf') if a >= 0 else float('-inf')
    return operator.truediv(a, b)


def _safe_floordiv(a, b):
    """Safe floor division that returns inf on division by zero."""
    if b == 0:
        return float('inf') if a >= 0 else float('-inf')
    return operator.floordiv(a, b)


def _safe_mod(a, b):
    """Safe modulo that returns 0 on division by zero."""
    if b == 0:
        return 0
    return operator.mod(a, b)


# Supported binary operators
BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: _safe_truediv,
    ast.FloorDiv: _safe_floordiv,
    ast.Mod: _safe_mod,
    ast.Pow: operator.pow,
}

# Supported comparison operators
COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Supported unary operators
UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

# Maximum AST nesting depth for safety
MAX_AST_DEPTH = 10


class ExpressionError(Exception):
    """Exception raised for expression parsing or evaluation errors."""
    pass


class ExpressionEvaluator:
    """Safe expression evaluator using Python AST.

    Supports:
    - Arithmetic: +, -, *, /, //, %, **
    - Comparison: ==, !=, <, <=, >, >=, in, not in
    - Logical: and, or, not
    - Built-in functions: len(), min(), max(), abs(), int(), float(), str(), bool()
    - Variable access: $answer, $think, $steps, $tool_calls
    - Boolean literals: True, False
    - Numeric literals: 1, 2.5, 0.8

    Example:
        ```python
        evaluator = ExpressionEvaluator(
            expr="len($answer) > 100",
            context={'answer': 'Hello World', 'think': '...'}
        )
        score = await evaluator.evaluate()  # Returns 0.0 or 1.0
        ```
    """

    def __init__(
        self,
        expr: str,
        context: Dict[str, Any],
        model: Optional[str] = None,
    ):
        """Initialize expression evaluator.

        Args:
            expr: Expression string to evaluate
            context: Dictionary of variable values
            model: Optional model name (reserved for future LLM-based evaluation)
        """
        self.original_expr = expr
        self.context = context
        self.model = model

        # Preprocess and parse expression
        self.processed_expr = self._preprocess_variables(expr)
        self.ast_tree = self._parse_expr(self.processed_expr)

    def _preprocess_variables(self, expr: str) -> str:
        """Convert $variable syntax to Python-compatible format.

        Transforms:
        - $answer -> __var_answer
        - $tool_calls -> __var_tool_calls

        Args:
            expr: Original expression with $ variables

        Returns:
            Processed expression with renamed variables
        """
        # Pattern to match $variable_name (with optional path like $obj.attr)
        pattern = r'\$([a-zA-Z_][a-zA-Z0-9_]*)'

        def replace_var(match):
            var_name = match.group(1)
            return f'__var_{var_name}'

        return re.sub(pattern, replace_var, expr)

    def _parse_expr(self, expr: str) -> ast.Expression:
        """Parse expression string into AST.

        Args:
            expr: Preprocessed expression string

        Returns:
            Parsed AST tree

        Raises:
            ExpressionError: If expression is syntactically invalid
        """
        try:
            tree = ast.parse(expr, mode='eval')
            self._validate_ast(tree, depth=0)
            return tree
        except SyntaxError as e:
            raise ExpressionError(f"Invalid expression syntax: {self.original_expr}") from e

    def _validate_ast(self, node: ast.AST, depth: int) -> None:
        """Validate AST for safety.

        Checks:
        - Maximum nesting depth
        - Only allowed node types

        Args:
            node: AST node to validate
            depth: Current nesting depth

        Raises:
            ExpressionError: If AST contains unsafe constructs
        """
        if depth > MAX_AST_DEPTH:
            raise ExpressionError(f"Expression too deeply nested (max {MAX_AST_DEPTH} levels)")

        # Allowed node types
        allowed_types = (
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.BoolOp,
            ast.Call,
            ast.Name,
            ast.Constant,
            ast.Num,  # Python 3.7 compatibility
            ast.Str,  # Python 3.7 compatibility
            ast.NameConstant,  # Python 3.7 compatibility
            ast.List,
            ast.Tuple,
            ast.Subscript,
            ast.Index,  # Python 3.8 compatibility
            ast.Slice,
            ast.Attribute,
            # Operators
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
            ast.And, ast.Or, ast.Not,
            ast.UAdd, ast.USub,
            ast.Load,
            ast.IfExp,  # Ternary expression: x if cond else y
        )

        if not isinstance(node, allowed_types):
            raise ExpressionError(f"Unsupported expression construct: {type(node).__name__}")

        # Recursively validate children
        for child in ast.iter_child_nodes(node):
            self._validate_ast(child, depth + 1)

    async def evaluate(self) -> float:
        """Evaluate expression and return normalized score.

        Returns:
            Score between 0.0 and 1.0

        Raises:
            ExpressionError: If evaluation fails
        """
        try:
            result = self._eval_node(self.ast_tree.body)
            return self._normalize(result)
        except ExpressionError:
            raise
        except Exception as e:
            raise ExpressionError(f"Expression evaluation failed: {e}") from e

    def evaluate_sync(self) -> float:
        """Synchronous version of evaluate().

        Returns:
            Score between 0.0 and 1.0
        """
        try:
            result = self._eval_node(self.ast_tree.body)
            return self._normalize(result)
        except ExpressionError:
            raise
        except Exception as e:
            raise ExpressionError(f"Expression evaluation failed: {e}") from e

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate AST node.

        Args:
            node: AST node to evaluate

        Returns:
            Evaluated value
        """
        # Constant values (Python 3.8+)
        if isinstance(node, ast.Constant):
            return node.value

        # Numeric constants (Python 3.7)
        if isinstance(node, ast.Num):
            return node.n

        # String constants (Python 3.7)
        if isinstance(node, ast.Str):
            return node.s

        # Boolean/None constants (Python 3.7)
        if isinstance(node, ast.NameConstant):
            return node.value

        # Variable access
        if isinstance(node, ast.Name):
            return self._get_variable(node.id)

        # Binary operations
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_func = BINARY_OPS.get(type(node.op))
            if op_func is None:
                raise ExpressionError(f"Unsupported binary operator: {type(node.op).__name__}")
            return op_func(left, right)

        # Unary operations
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_func = UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise ExpressionError(f"Unsupported unary operator: {type(node.op).__name__}")
            return op_func(operand)

        # Comparison operations
        if isinstance(node, ast.Compare):
            return self._eval_compare(node)

        # Boolean operations (and, or)
        if isinstance(node, ast.BoolOp):
            return self._eval_bool_op(node)

        # Function calls
        if isinstance(node, ast.Call):
            return self._eval_call(node)

        # List literals
        if isinstance(node, ast.List):
            return [self._eval_node(elem) for elem in node.elts]

        # Tuple literals
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elem) for elem in node.elts)

        # Subscript (indexing)
        if isinstance(node, ast.Subscript):
            value = self._eval_node(node.value)
            # Handle different Python versions
            if isinstance(node.slice, ast.Index):
                index = self._eval_node(node.slice.value)
            else:
                index = self._eval_node(node.slice)
            return value[index]

        # Attribute access
        if isinstance(node, ast.Attribute):
            value = self._eval_node(node.value)
            if isinstance(value, dict):
                return value.get(node.attr)
            return getattr(value, node.attr, None)

        # Ternary expression
        if isinstance(node, ast.IfExp):
            condition = self._eval_node(node.test)
            if condition:
                return self._eval_node(node.body)
            else:
                return self._eval_node(node.orelse)

        raise ExpressionError(f"Cannot evaluate node type: {type(node).__name__}")

    def _get_variable(self, name: str) -> Any:
        """Get variable value from context.

        Args:
            name: Variable name (possibly prefixed with __var_)

        Returns:
            Variable value
        """
        # Check for our renamed variables
        if name.startswith('__var_'):
            var_name = name[6:]  # Remove __var_ prefix
            if var_name in self.context:
                return self.context[var_name]
            raise ExpressionError(f"Unknown variable: ${var_name}")

        # Check built-in functions (used as names)
        if name in BUILTIN_FUNCTIONS:
            return BUILTIN_FUNCTIONS[name]

        # Check boolean constants
        if name == 'True':
            return True
        if name == 'False':
            return False
        if name == 'None':
            return None

        # Check context directly
        if name in self.context:
            return self.context[name]

        raise ExpressionError(f"Unknown variable: {name}")

    def _eval_compare(self, node: ast.Compare) -> bool:
        """Evaluate comparison expression.

        Handles chained comparisons like: a < b < c

        Args:
            node: Compare AST node

        Returns:
            Boolean result
        """
        left = self._eval_node(node.left)

        for op, comparator in zip(node.ops, node.comparators):
            right = self._eval_node(comparator)
            op_func = COMPARE_OPS.get(type(op))
            if op_func is None:
                raise ExpressionError(f"Unsupported comparison operator: {type(op).__name__}")

            if not op_func(left, right):
                return False
            left = right

        return True

    def _eval_bool_op(self, node: ast.BoolOp) -> bool:
        """Evaluate boolean operation (and/or).

        Implements short-circuit evaluation.

        Args:
            node: BoolOp AST node

        Returns:
            Boolean result
        """
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not self._eval_node(value):
                    return False
            return True
        elif isinstance(node.op, ast.Or):
            for value in node.values:
                if self._eval_node(value):
                    return True
            return False
        else:
            raise ExpressionError(f"Unsupported boolean operator: {type(node.op).__name__}")

    def _eval_call(self, node: ast.Call) -> Any:
        """Evaluate function call.

        Args:
            node: Call AST node

        Returns:
            Function result
        """
        # Get function name
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            # Method calls like str.upper() - not supported yet
            raise ExpressionError("Method calls are not supported in expressions")
        else:
            raise ExpressionError(f"Unsupported function call type: {type(node.func).__name__}")

        # Check if function is allowed
        if func_name not in BUILTIN_FUNCTIONS:
            raise ExpressionError(f"Unknown function: {func_name}")

        # Evaluate arguments
        args = [self._eval_node(arg) for arg in node.args]

        # Call function
        func = BUILTIN_FUNCTIONS[func_name]
        return func(*args)

    def _normalize(self, value: Any) -> float:
        """Normalize value to 0-1 range.

        Conversion rules:
        - bool: True -> 1.0, False -> 0.0
        - int/float: Clamp to [0, 1]
        - str: non-empty -> 1.0, empty -> 0.0
        - list/tuple: non-empty -> 1.0, empty -> 0.0
        - None: 0.0
        - Other: 0.0

        Args:
            value: Value to normalize

        Returns:
            Float between 0.0 and 1.0
        """
        if isinstance(value, bool):
            return 1.0 if value else 0.0

        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))

        if isinstance(value, str):
            return 1.0 if len(value) > 0 else 0.0

        if isinstance(value, (list, tuple)):
            return 1.0 if len(value) > 0 else 0.0

        if value is None:
            return 0.0

        # Default: try to convert to bool
        return 1.0 if bool(value) else 0.0
