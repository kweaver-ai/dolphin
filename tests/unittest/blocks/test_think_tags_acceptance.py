"""Acceptance tests for <think> tag stripping (Issue #3).

These tests cover the three mandatory acceptance scenarios:

1. test_ifelse_block_with_think_tagged_variable
   - ifelse_block eval must succeed even when a variable's value has a
     <think>...</think> prefix containing Chinese full-width punctuation.

2. test_strip_think_tags_unclosed_tag_streaming_truncation
   - strip_think_tags must return input unchanged (not hang) when the
     closing </think> tag is absent, as happens with a truncated stream.

3. test_assign_block_interpolation_path_with_think_tags
   - When a variable containing think tags is interpolated via a string-
     literal expression, the function must produce a clearly-defined result.
     Chosen behavior: passthrough (tags are NOT stripped in the
     _interpolate_plain_text path because there is no eval crash risk there).
"""

from unittest.mock import patch, MagicMock

import pytest

from dolphin.core import flags
from dolphin.core.code_block.assign_block import AssignBlock
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.context.context import Context
from dolphin.core.context.variable_pool import VariablePool
from dolphin.core.executor.executor import Executor
from dolphin.core.utils.tools import strip_think_tags


# ---------------------------------------------------------------------------
# Acceptance test 1: ifelse_block with think-tagged variable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ifelse_block_with_think_tagged_variable():
    """ifelse_block eval must NOT raise SyntaxError on Chinese think content.

    A variable whose value is '<think>中文推理，包含全角标点</think>actual_value'
    is referenced in an /if/ condition.  After stripping the think block, the
    condition evaluates to True and the matching branch is executed.
    """
    ctx = Context(verbose=False)
    # Variable value contains inline reasoning with Chinese full-width comma
    ctx.set_var_output("var", "<think>中文推理，包含全角标点</think>actual_value")

    # Both ExploreBlock and ExploreBlockV2 require a full LLM config;
    # patch LLMClient so the Executor can be constructed in unit tests.
    with patch("dolphin.core.llm.llm_client.LLMClient.__init__", return_value=None), \
         flags.override({flags.EXPLORE_BLOCK_V2: False}):
        executor = Executor(context=ctx)

    # Well-formed if/end block: condition references $var; action assigns result
    content = "/if/ var == 'actual_value':\n'matched' -> result\n/end/"

    results = []
    # Must not raise SyntaxError; if-branch must be taken
    async for item in executor.ifelse_block(content):
        results.append(item)

    # The assign block inside the if branch yielded the value
    assert ctx.get_var_value("result") == "matched", (
        "Expected 'matched' branch to be taken after think tags are stripped from var"
    )


# ---------------------------------------------------------------------------
# Acceptance test 2: unclosed <think> tag (truncated streaming response)
# ---------------------------------------------------------------------------


def test_strip_think_tags_unclosed_tag_streaming_truncation():
    """strip_think_tags must return input unchanged for an unclosed think tag.

    A truncated streaming response may produce '<think>推理内容，还没结束'
    without a closing </think>.  The non-greedy regex must NOT match and must
    return the input as-is.  It must also NOT hang or catastrophically
    backtrack.
    """
    # Exact scenario from the acceptance test description
    val = "<think>这是推理过程，还没结束"
    result = strip_think_tags(val)

    # Input must be returned unchanged (not stripped, not truncated, not "")
    assert result == val, (
        f"Expected input to be returned unchanged for unclosed think tag, "
        f"got: {result!r}"
    )


def test_strip_think_tags_unclosed_tag_no_hang():
    """Confirm no catastrophic backtracking on a very long unclosed tag."""
    long_content = "这是超长推理，" * 1000  # ~7000 Chinese chars
    val = f"<think>{long_content}"
    # If this completes within the test timeout it proves no catastrophic backtrack
    result = strip_think_tags(val)
    assert result == val


# ---------------------------------------------------------------------------
# Acceptance test 3: interpolation path with think tags — passthrough behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_block_interpolation_path_with_think_tags():
    """String-literal interpolation must pass think tags through unchanged.

    Design decision (see Issue #3 design doc, F4):
    _interpolate_plain_text does NOT strip think tags because there is no
    eval() call on that path and thus no crash risk.  Think tags in the
    variable value appear verbatim in the interpolated result.

    Expression:  '"prefix $var suffix" -> result'
    Variable:    var = '<think>reasoning</think>hello world'
    Expected:    'prefix <think>reasoning</think>hello world suffix'
    """
    ctx = Context(verbose=False)
    ctx.set_var_output("var", "<think>reasoning</think>hello world")

    block = AssignBlock(context=ctx)

    results = []
    # String-literal expression: the double-quoted string forces the
    # _try_parse_string_literal → _interpolate_plain_text path.
    async for item in block.execute(
        '"prefix $var suffix" -> result', category=CategoryBlock.ASSIGN
    ):
        if item != {}:
            results.append(item)

    # Passthrough: think tags are preserved in interpolated output
    assert results == ["prefix <think>reasoning</think>hello world suffix"], (
        "Expected think tags to be preserved (passthrough) in interpolation path"
    )


# ---------------------------------------------------------------------------
# Supplementary test: variable_pool nested index access with think-tagged value
# ---------------------------------------------------------------------------


def test_variable_pool_get_variable_type_with_think_tags_in_nested_access():
    """variable_pool.get_variable_type must not SyntaxError on think-tagged base string values.

    When a base variable is a raw string like '<think>中文，推理</think>{"answer": "ok"}'
    (the reasoning model returned a JSON payload prefixed with an inline think block),
    the old code embedded the think tags verbatim into the eval() expression string:

        eval('<think>中文，推理</think>{"answer": "ok"}[\'answer\']')  → SyntaxError

    After the fix, strip_think_tags removes the think block before str() conversion:

        eval('{"answer": "ok"}[\'answer\']')  → "ok"
    """
    pool = VariablePool()
    # Simulate a model response that prefixes reasoning markup before a JSON payload
    pool.set_var("var", '<think>中文，推理</think>{"answer": "ok"}')

    # $var.answer → after convert_object_to_dict_access → var['answer']
    result = pool.get_variable_type("$var.answer")
    assert result == "ok", (
        f"Expected 'ok' from JSON payload after think-tag stripping, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Supplementary test: ifelse_block when variable is entirely a think block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ifelse_block_variable_with_only_think_tags_evaluates_empty():
    """After stripping, a variable that was entirely a think block becomes ''.

    An empty string is falsy in Python, so /if/ $var: should take the else
    branch.  This must not raise SyntaxError or any other error.
    """
    ctx = Context(verbose=False)
    # The variable's entire value is a think block — after stripping, it is ''
    ctx.set_var_output("var", "<think>推理内容</think>")

    with patch("dolphin.core.llm.llm_client.LLMClient.__init__", return_value=None), \
         flags.override({flags.EXPLORE_BLOCK_V2: False}):
        executor = Executor(context=ctx)

    # if-branch: var is truthy → assigns 'truthy'
    # else-branch: var is falsy  → assigns 'falsy'
    content = "/if/ var:\n'truthy' -> result\nelse:\n'falsy' -> result\n/end/"

    async for _ in executor.ifelse_block(content):
        pass

    # Empty string is falsy → else branch taken
    assert ctx.get_var_value("result") == "falsy", (
        "Expected else branch because think-only variable strips to empty string (falsy)"
    )
