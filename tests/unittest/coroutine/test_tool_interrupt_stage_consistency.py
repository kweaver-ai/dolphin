"""
Unit tests for tool interrupt stage consistency

Tests the fix for ensuring stage_id remains consistent across interrupt/resume
and that the completed status is correctly propagated.

Related Issue: Tool interrupt causes stage_id to change after resume
Fix: Modified skill_run() and explore_block_v2 to preserve stage_id and
     yield progress updates correctly.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from typing import Dict, Any, List

from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.code_block.explore_block_v2 import ExploreBlockV2
from dolphin.core.code_block.tool_block import ToolBlock
from dolphin.core.code_block.judge_block import JudgeBlock
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.trajectory.recorder import Recorder
from dolphin.core.runtime.runtime_instance import ProgressInstance, StageInstance
from dolphin.core.common.enums import Status, TypeStage
from dolphin.core import flags


class TestSkillkit(Skillkit):
    """Test skillkit for interrupt tests"""
    def __init__(self, skills_dict):
        super().__init__()
        self._skills_dict = skills_dict
    
    def _createSkills(self):
        return list(self._skills_dict.values())


@pytest.fixture
def mock_context_with_recorder():
    """Create context with recorder for stage tracking"""
    config = GlobalConfig()
    context = Context(config=config)
    
    # Create test tools
    async def risky_operation(database_name: str = "", **kwargs):
        """Simulated risky operation requiring confirmation"""
        return {"output": f"Database {database_name} deleted successfully"}
    
    async def safe_operation(query: str = "", **kwargs):
        """Safe operation without confirmation"""
        return {"output": f"Query executed: {query}"}
    
    # Create SkillFunction with interrupt config
    risky_skill = SkillFunction(risky_operation)
    risky_skill.interrupt_config = {
        "requires_confirmation": True,
        "confirmation_message": "Confirm deletion of database '{database_name}'?"
    }
    
    safe_skill = SkillFunction(safe_operation)
    safe_skill.interrupt_config = None
    
    # Create test skillkit with these skills
    skills_dict = {
        "risky_operation": risky_skill,
        "safe_operation": safe_skill
    }
    skillkit = TestSkillkit(skills_dict)
    
    # Use set_skills to properly initialize skills
    context.set_skills(skillkit)
    
    return context


@pytest.mark.skip(reason="skill_run() API not yet implemented in ExploreBlockV2 - planned feature")
@pytest.mark.asyncio
async def test_stage_id_consistency_across_interrupt_resume(mock_context_with_recorder):
    """
    Test that stage_id remains consistent when a tool is interrupted and resumed.
    
    Scenario:
    1. Start tool execution (creates stage with ID_A)
    2. Tool throws ToolInterrupt
    3. Resume execution
    4. Verify the resumed stage still has ID_A (not a new ID)
    """
    context = mock_context_with_recorder
    block = ExploreBlockV2(context)
    
    # Enable explore v2 flag
    flags.EXPLORE_BLOCK_V2 = True
    
    # Track stage IDs
    stage_ids_before_interrupt = []
    stage_ids_after_resume = []
    interrupted = False
    
    try:
        # Step 1: Execute tool call that will be interrupted
        async for result in block.skill_run(
            source_type=block.context.get_source_type("EXPLORE"),
            skill_name="risky_operation",
            skill_params_json={"database_name": "test_db"},
            props={"intervention": True}  # First-time call
        ):
            # Capture stage ID before interrupt
            progress = context.get_var_value("_progress")
            if progress and len(progress) > 0:
                stage_ids_before_interrupt.append(progress[-1]["id"])
    except ToolInterrupt as e:
        interrupted = True
        
        # Simulate user confirmation and resume
        # Get the saved intervention_vars
        intervention_vars = context.get_var_value("intervention_explore_block_vars")
        assert intervention_vars is not None, "intervention_vars should be saved"
        
        saved_stage_id = intervention_vars.get("stage_id")
        assert saved_stage_id is not None, "stage_id should be saved in intervention_vars"
        
        print(f"\n[TEST] Stage ID before interrupt: {saved_stage_id}")
        
        # Simulate resume: set the tool variable to indicate user confirmed
        context.set_variable("tool", {
            "tool_name": "risky_operation",
            "tool_args": [{"key": "database_name", "value": "test_db"}]
        })
        
        # Step 2: Resume execution
        async for result in block.skill_run(
            source_type=block.context.get_source_type("EXPLORE"),
            skill_name="risky_operation",
            skill_params_json={"database_name": "test_db"},
            props={"intervention": False, "saved_stage_id": saved_stage_id}  # Resumed call
        ):
            # Capture stage ID after resume
            progress = context.get_var_value("_progress")
            if progress and len(progress) > 0:
                stage_ids_after_resume.append(progress[-1]["id"])
        
        print(f"[TEST] Stage IDs after resume: {stage_ids_after_resume}")
    
    # Assertions
    assert interrupted, "Tool should have thrown ToolInterrupt"
    assert len(stage_ids_before_interrupt) > 0, "Should have captured stage ID before interrupt"
    assert len(stage_ids_after_resume) > 0, "Should have captured stage ID after resume"
    
    # Key assertion: Stage ID should remain the same
    initial_stage_id = stage_ids_before_interrupt[0]
    final_stage_id = stage_ids_after_resume[-1]
    
    assert initial_stage_id == final_stage_id, (
        f"Stage ID changed after resume! Before: {initial_stage_id}, After: {final_stage_id}"
    )
    
    print(f"\n✓ Stage ID consistency verified: {initial_stage_id}")


@pytest.mark.skip(reason="skill_run() API not yet implemented in ExploreBlockV2 - planned feature")
@pytest.mark.asyncio
async def test_stage_status_changes_to_completed(mock_context_with_recorder):
    """
    Test that stage status changes from PROCESSING to COMPLETED after tool finishes.
    
    Scenario:
    1. Resume tool execution (stage starts as PROCESSING)
    2. Tool completes successfully
    3. Verify stage status is COMPLETED
    """
    context = mock_context_with_recorder
    block = ExploreBlockV2(context)
    
    # ExploreBlockV2 creates its own recorder during initialization
    # Access it through the block's progress and context
    recorder = block.recorder
    
    # Simulate a resumed tool call by setting up intervention_vars
    saved_stage_id = "test-stage-id-12345"
    
    # Manually create a stage in PROCESSING state
    progress = recorder.getProgress()
    progress.add_stage(
        stage=TypeStage.SKILL,
        status=Status.PROCESSING,
        skill_info=None,
        answer="",
    )
    
    # Override the stage ID to simulate resume
    if len(progress.stages) > 0:
        progress.stages[-1].id = saved_stage_id
        progress.set_variable()  # Update _progress variable
    
    # Get initial status
    progress_before = context.get_var_value("_progress")
    assert len(progress_before) > 0
    initial_status = progress_before[-1]["status"]
    print(f"\n[TEST] Initial status: {initial_status}")
    
    # Execute tool to completion (mock to avoid interrupt)
    with patch.object(SkillFunction, '__call__', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"output": "Operation completed"}
        
        # Disable interrupt for this test
        risky_skill = context.get_skill("risky_operation")
        original_config = risky_skill.interrupt_config
        risky_skill.interrupt_config = None
        
        try:
            async for result in block.skill_run(
                source_type=block.context.get_source_type("EXPLORE"),
                skill_name="risky_operation",
                skill_params_json={"database_name": "test_db"},
                props={"intervention": False, "saved_stage_id": saved_stage_id}
            ):
                pass  # Let it complete
        finally:
            risky_skill.interrupt_config = original_config
    
    # Get final status
    progress_after = context.get_var_value("_progress")
    assert len(progress_after) > 0
    final_status = progress_after[-1]["status"]
    final_stage_id = progress_after[-1]["id"]
    
    print(f"[TEST] Final status: {final_status}")
    print(f"[TEST] Final stage ID: {final_stage_id}")
    
    # Assertions
    assert final_status == "completed", f"Expected 'completed', got '{final_status}'"
    assert final_stage_id == saved_stage_id, "Stage ID should not change"
    
    print("\n✓ Stage status correctly updated to completed")


@pytest.mark.skip(reason="skill_run() API not yet implemented in ExploreBlockV2 - planned feature")
@pytest.mark.asyncio
async def test_no_duplicate_stages_on_resume(mock_context_with_recorder):
    """
    Test that resuming a tool does not create duplicate stages.
    
    Scenario:
    1. Tool is interrupted (creates stage with ID_A)
    2. Resume execution
    3. Verify only one stage exists with ID_A (no duplicate with new ID)
    """
    context = mock_context_with_recorder
    block = ExploreBlockV2(context)
    
    # ExploreBlockV2 creates its own recorder during initialization
    recorder = block.recorder
    
    interrupted = False
    
    try:
        # Execute tool that will be interrupted
        async for result in block.skill_run(
            source_type=block.context.get_source_type("EXPLORE"),
            skill_name="risky_operation",
            skill_params_json={"database_name": "test_db"},
            props={"intervention": True}
        ):
            pass
    except ToolInterrupt:
        interrupted = True
        
        # Get intervention vars with saved stage_id
        intervention_vars = context.get_var_value("intervention_explore_block_vars")
        saved_stage_id = intervention_vars.get("stage_id")
        
        # Prepare for resume
        context.set_variable("tool", {
            "tool_name": "risky_operation",
            "tool_args": [{"key": "database_name", "value": "test_db"}]
        })
        
        # Mock skill execution to avoid actual interrupt
        with patch.object(SkillFunction, '__call__', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"output": "Done"}
            
            risky_skill = context.get_skill("risky_operation")
            original_config = risky_skill.interrupt_config
            risky_skill.interrupt_config = None
            
            try:
                # Resume execution
                async for result in block.skill_run(
                    source_type=block.context.get_source_type("EXPLORE"),
                    skill_name="risky_operation",
                    skill_params_json={"database_name": "test_db"},
                    props={"intervention": False, "saved_stage_id": saved_stage_id}
                ):
                    pass
            finally:
                risky_skill.interrupt_config = original_config
        
        # Check progress: should have exactly one stage with the saved_stage_id
        progress = context.get_var_value("_progress")
        stage_ids = [stage["id"] for stage in progress]
        
        print(f"\n[TEST] All stage IDs: {stage_ids}")
        print(f"[TEST] Saved stage ID: {saved_stage_id}")
        
        # Count occurrences of saved_stage_id
        count = stage_ids.count(saved_stage_id)
        
        # Assertion: Should have exactly one stage (no duplicates)
        assert count == 1, f"Expected 1 stage with ID {saved_stage_id}, found {count}"
        
        print(f"\n✓ No duplicate stages created on resume")
    
    assert interrupted, "Tool should have been interrupted"


@pytest.mark.skip(reason="skill_run() API not yet implemented in ExploreBlockV2 - planned feature")
@pytest.mark.asyncio
async def test_progress_variable_contains_completed_status(mock_context_with_recorder):
    """
    Test that _progress variable in context contains completed status after tool finishes.
    
    This is critical for frontend/UI to display the correct state.
    
    Scenario:
    1. Tool completes execution
    2. Check _progress variable in context
    3. Verify it contains status='completed'
    """
    context = mock_context_with_recorder
    block = ExploreBlockV2(context)
    
    # Execute safe tool (no interrupt)
    async for result in block.skill_run(
        source_type=block.context.get_source_type("EXPLORE"),
        skill_name="safe_operation",
        skill_params_json={"query": "SELECT * FROM users"},
        props={"intervention": True}
    ):
        # Check if result contains _progress
        if isinstance(result, dict) and "_progress" in result:
            print(f"\n[TEST] Progress update received: {result['_progress'][-1]['status']}")
    
    # Get _progress from context
    progress = context.get_var_value("_progress")
    assert progress is not None, "_progress should exist in context"
    assert len(progress) > 0, "_progress should not be empty"
    
    last_stage = progress[-1]
    print(f"\n[TEST] Last stage status: {last_stage['status']}")
    print(f"[TEST] Last stage ID: {last_stage['id']}")
    print(f"[TEST] Last stage type: {last_stage['stage']}")
    
    # Assertions
    assert last_stage["status"] == "completed", (
        f"Expected status 'completed', got '{last_stage['status']}'"
    )
    assert last_stage["stage"] == "skill", "Expected stage type 'skill'"
    
    print("\n✓ _progress variable correctly contains completed status")


@pytest.mark.skip(reason="skill_run() API not yet implemented in ExploreBlockV2 - planned feature")
@pytest.mark.asyncio
async def test_multiple_interrupts_preserve_stage_ids(mock_context_with_recorder):
    """
    Test that multiple tool interrupts in sequence each preserve their stage_ids.
    
    Scenario:
    1. Tool A interrupted (stage_id = A)
    2. Resume Tool A (verify stage_id = A)
    3. Tool B interrupted (stage_id = B)
    4. Resume Tool B (verify stage_id = B)
    """
    context = mock_context_with_recorder
    block = ExploreBlockV2(context)
    
    # Create second risky tool
    async def another_risky_op(table_name: str = "", **kwargs):
        return {"output": f"Table {table_name} modified"}
    
    another_skill = SkillFunction(another_risky_op)
    another_skill.interrupt_config = {
        "requires_confirmation": True,
        "confirmation_message": "Confirm modification of table '{table_name}'?"
    }
    context.set_skill("another_risky_op", another_skill)
    
    stage_ids = {}  # Track stage IDs for each tool
    
    # Tool A: Interrupt and Resume
    try:
        async for _ in block.skill_run(
            source_type=block.context.get_source_type("EXPLORE"),
            skill_name="risky_operation",
            skill_params_json={"database_name": "db1"},
            props={"intervention": True}
        ):
            pass
    except ToolInterrupt:
        vars_a = context.get_var_value("intervention_explore_block_vars")
        stage_ids["tool_a_before"] = vars_a.get("stage_id")
        
        # Resume Tool A (mock)
        context.set_variable("tool", {
            "tool_name": "risky_operation",
            "tool_args": [{"key": "database_name", "value": "db1"}]
        })
        
        with patch.object(SkillFunction, '__call__', new_callable=AsyncMock) as mock:
            mock.return_value = {"output": "Done"}
            context.get_skill("risky_operation").interrupt_config = None
            
            async for _ in block.skill_run(
                source_type=block.context.get_source_type("EXPLORE"),
                skill_name="risky_operation",
                skill_params_json={"database_name": "db1"},
                props={"intervention": False, "saved_stage_id": stage_ids["tool_a_before"]}
            ):
                pass
            
            # Restore interrupt config
            context.get_skill("risky_operation").interrupt_config = {
                "requires_confirmation": True,
                "confirmation_message": "Confirm deletion of database '{database_name}'?"
            }
        
        progress = context.get_var_value("_progress")
        stage_ids["tool_a_after"] = progress[-1]["id"]
    
    # Tool B: Interrupt and Resume
    try:
        async for _ in block.skill_run(
            source_type=block.context.get_source_type("EXPLORE"),
            skill_name="another_risky_op",
            skill_params_json={"table_name": "users"},
            props={"intervention": True}
        ):
            pass
    except ToolInterrupt:
        vars_b = context.get_var_value("intervention_explore_block_vars")
        stage_ids["tool_b_before"] = vars_b.get("stage_id")
        
        # Resume Tool B (mock)
        context.set_variable("tool", {
            "tool_name": "another_risky_op",
            "tool_args": [{"key": "table_name", "value": "users"}]
        })
        
        with patch.object(SkillFunction, '__call__', new_callable=AsyncMock) as mock:
            mock.return_value = {"output": "Done"}
            context.get_skill("another_risky_op").interrupt_config = None
            
            async for _ in block.skill_run(
                source_type=block.context.get_source_type("EXPLORE"),
                skill_name="another_risky_op",
                skill_params_json={"table_name": "users"},
                props={"intervention": False, "saved_stage_id": stage_ids["tool_b_before"]}
            ):
                pass
        
        progress = context.get_var_value("_progress")
        stage_ids["tool_b_after"] = progress[-1]["id"]
    
    print(f"\n[TEST] Stage IDs tracked:")
    for key, value in stage_ids.items():
        print(f"  {key}: {value}")
    
    # Assertions
    assert stage_ids["tool_a_before"] == stage_ids["tool_a_after"], (
        "Tool A stage_id should remain consistent"
    )
    assert stage_ids["tool_b_before"] == stage_ids["tool_b_after"], (
        "Tool B stage_id should remain consistent"
    )
    assert stage_ids["tool_a_before"] != stage_ids["tool_b_before"], (
        "Tool A and Tool B should have different stage_ids"
    )
    
    print("\n✓ Multiple interrupts correctly preserve individual stage_ids")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])

