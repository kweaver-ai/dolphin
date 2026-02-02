import pytest

from dolphin.core.code_block.assign_block import AssignBlock
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.context.context import Context


@pytest.mark.asyncio
async def test_assign_block_triple_quoted_string_interpolates_dollar_variables():
    ctx = Context(verbose=False)
    ctx.set_var_output("x", "world")

    block = AssignBlock(context=ctx)

    results = []
    async for item in block.execute("'''hello $x''' -> y", category=CategoryBlock.ASSIGN):
        if item != {}:
            results.append(item)

    assert results == ["hello world"]

