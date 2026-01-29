import pytest

from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.task_registry import PlanExecMode

def test_explore_block_exec_mode_validation():
    context = Context(config=GlobalConfig())
    explore = ExploreBlock(context=context)
    
    # Valid "seq"
    explore.parse_block_content('/explore/(exec_mode="seq") query -> result', category=CategoryBlock.EXPLORE)
    assert explore.params["exec_mode"] == PlanExecMode.SEQUENTIAL
    
    # Valid "para"
    explore.parse_block_content('/explore/(exec_mode="para") query -> result', category=CategoryBlock.EXPLORE)
    assert explore.params["exec_mode"] == PlanExecMode.PARALLEL
    
    # Invalid value
    with pytest.raises(ValueError, match="Invalid execution mode: invalid"):
        explore.parse_block_content('/explore/(exec_mode="invalid") query -> result', category=CategoryBlock.EXPLORE)
        
if __name__ == "__main__":
    test_explore_block_exec_mode_validation()
    print("Validation tests passed!")
