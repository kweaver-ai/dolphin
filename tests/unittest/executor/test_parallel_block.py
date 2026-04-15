"""Tests for parallel block race condition (GitHub Issue #49).

When two @tool calls run inside a /parallel/ block, they share a single
ToolBlock instance on the Executor.  The second branch overwrites
output_var / recorder before the first branch finishes its await,
causing one variable assignment to be lost.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from dolphin.core.context.context import Context
from dolphin.core.executor.executor import Executor
from dolphin.core.skill.skill_function import SkillFunction


def _make_skill(name: str, delay: float, return_value: str):
    """Create an async skill function with a configurable delay.

    Parameters
    ----------
    name : str
        The function (skill) name exposed to the DPH runtime.
    delay : float
        How long the skill sleeps before returning (seconds).
    return_value : str
        The string placed in the ``answer`` field of the result dict.
    """

    async def _skill(input: str = "", props: dict = None):
        await asyncio.sleep(delay)
        return {"answer": return_value, "agent_name": "main"}

    # The runtime uses func.__name__ as the skill name.
    _skill.__name__ = name
    return SkillFunction(_skill)


@pytest.mark.asyncio
async def test_parallel_tool_calls_assign_to_correct_variables():
    """Two tool calls in /parallel/ must each write to their own variable.

    The slow tool (SlowTool, 0.15 s) writes to ``var_a``.
    The fast tool (FastTool, 0.01 s) writes to ``var_b``.

    Because they share one ToolBlock instance, the fast tool's
    parse_block_content overwrites output_var / recorder while the slow
    tool is still awaiting.  The slow tool then writes its result to
    var_b (the fast tool's variable) instead of var_a.

    Expected (after fix): both var_a and var_b are set.
    Actual   (before fix): var_a is None -- the race condition drops it.
    """
    ctx = Context(verbose=False)

    # Register two mock skills with the context's skillkit.
    slow_skill = _make_skill("SlowTool", delay=0.15, return_value="slow_result")
    fast_skill = _make_skill("FastTool", delay=0.01, return_value="fast_result")

    # Inject skills into the skillkit's cache so get_skill() finds them.
    ctx.skillkit._skills_cache = [slow_skill, fast_skill]

    # Pre-set the input variable used by the DPH script.
    ctx.set_var_output("q", "hello")

    # DPH script: run both tools in parallel, each writing to a
    # different output variable.
    dph_script = (
        "/parallel/\n"
        "@SlowTool(input=$q) -> var_a\n"
        "@FastTool(input=$q) -> var_b\n"
        "/end/"
    )

    # Patch blocks that require LLMClient (which needs a full config).
    # The test only exercises tool blocks inside /parallel/.
    # Patch blocks that require LLMClient (which needs a full config).
    # The patch must cover both Executor construction and run() because
    # _create_blocks() is called during parallel execution.
    with patch(
        "dolphin.core.executor.executor.ExploreBlockV2",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.ExploreBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.JudgeBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.PromptBlock",
        return_value=MagicMock(),
    ):
        executor = Executor(context=ctx)

        # Consume the entire async generator produced by executor.run().
        async for _ in executor.run(dph_script):
            pass

    var_a = ctx.get_var_value("var_a")
    var_b = ctx.get_var_value("var_b")

    # --- Assertions ---
    # var_b (fast tool) is almost always written correctly.
    assert var_b is not None, "var_b should be set by FastTool"

    # var_a (slow tool) is the one lost due to the race condition.
    # This assertion is expected to FAIL on the buggy code, proving the
    # race condition exists.
    assert var_a is not None, (
        "var_a should be set by SlowTool, but was None -- "
        "the parallel race condition dropped it"
    )


@pytest.mark.asyncio
async def test_parallel_many_concurrent_branches():
    """Stress test: 5 tool calls in /parallel/ must all write correctly."""
    ctx = Context(verbose=False)

    skills = [
        _make_skill(f"Tool{i}", delay=0.01 * i, return_value=f"value_{i}")
        for i in range(5)
    ]
    ctx.skillkit._skills_cache = list(skills)
    ctx.set_var_output("q", "hello")

    lines = [f"@Tool{i}(input=$q) -> result_{i}" for i in range(5)]
    dph_script = "/parallel/\n" + "\n".join(lines) + "\n/end/"

    with patch(
        "dolphin.core.executor.executor.ExploreBlockV2",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.ExploreBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.JudgeBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.PromptBlock",
        return_value=MagicMock(),
    ):
        executor = Executor(context=ctx)
        async for _ in executor.run(dph_script):
            pass

    for i in range(5):
        val = ctx.get_var_value(f"result_{i}")
        assert val is not None, (
            f"result_{i} should be set by Tool{i}, but was None"
        )


@pytest.mark.asyncio
async def test_sequential_tool_calls_unaffected():
    """Regression: sequential (non-parallel) tool calls must still work."""
    ctx = Context(verbose=False)

    skill_a = _make_skill("ToolA", delay=0.01, return_value="alpha")
    skill_b = _make_skill("ToolB", delay=0.01, return_value="beta")
    ctx.skillkit._skills_cache = [skill_a, skill_b]
    ctx.set_var_output("q", "hello")

    dph_script = (
        "@ToolA(input=$q) -> seq_a\n"
        "@ToolB(input=$q) -> seq_b"
    )

    with patch(
        "dolphin.core.executor.executor.ExploreBlockV2",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.ExploreBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.JudgeBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.PromptBlock",
        return_value=MagicMock(),
    ):
        executor = Executor(context=ctx)
        async for _ in executor.run(dph_script):
            pass

    assert ctx.get_var_value("seq_a") is not None, "seq_a should be set by ToolA"
    assert ctx.get_var_value("seq_b") is not None, "seq_b should be set by ToolB"


@pytest.mark.asyncio
async def test_parallel_variable_isolation_no_cross_write():
    """Parallel variable isolation: slow and fast tools write to their own vars."""
    ctx = Context(verbose=False)

    slow_skill = _make_skill("SlowOne", delay=0.1, return_value="slow_val")
    fast_skill = _make_skill("FastOne", delay=0.01, return_value="fast_val")
    ctx.skillkit._skills_cache = [slow_skill, fast_skill]
    ctx.set_var_output("q", "hello")

    dph_script = (
        "/parallel/\n"
        "@SlowOne(input=$q) -> slow_result\n"
        "@FastOne(input=$q) -> fast_result\n"
        "/end/"
    )

    with patch(
        "dolphin.core.executor.executor.ExploreBlockV2",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.ExploreBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.JudgeBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.PromptBlock",
        return_value=MagicMock(),
    ):
        executor = Executor(context=ctx)
        async for _ in executor.run(dph_script):
            pass

    slow_val = ctx.get_var_value("slow_result")
    fast_val = ctx.get_var_value("fast_result")
    assert slow_val is not None, "slow_result should be set by SlowOne"
    assert fast_val is not None, "fast_result should be set by FastOne"


@pytest.mark.asyncio
async def test_parallel_with_assign_and_tool_mixed():
    """Parallel block with mixed block types: one @tool and one assign."""
    ctx = Context(verbose=False)

    skill = _make_skill("MyTool", delay=0.05, return_value="tool_val")
    ctx.skillkit._skills_cache = [skill]
    ctx.set_var_output("q", "hello")
    ctx.set_var_output("x", "assign_val")

    dph_script = (
        "/parallel/\n"
        "@MyTool(input=$q) -> tool_result\n"
        "$x -> assign_result\n"
        "/end/"
    )

    with patch(
        "dolphin.core.executor.executor.ExploreBlockV2",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.ExploreBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.JudgeBlock",
        return_value=MagicMock(),
    ), patch(
        "dolphin.core.executor.executor.PromptBlock",
        return_value=MagicMock(),
    ):
        executor = Executor(context=ctx)
        async for _ in executor.run(dph_script):
            pass

    assert ctx.get_var_value("tool_result") is not None, "tool_result should be set by MyTool"
    assert ctx.get_var_value("assign_result") is not None, "assign_result should be set by assign block"
