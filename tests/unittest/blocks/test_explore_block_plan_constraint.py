"""Unit tests for ExploreBlock plan mode hard constraint."""

import pytest
from unittest.mock import MagicMock, patch

from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.code_block.skill_call_deduplicator import DefaultSkillCallDeduplicator
from dolphin.core.task_registry import Task, TaskStatus
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.common.constants import MAX_SKILL_CALL_TIMES


class TestExploreBlockPlanConstraint:
    """Test ExploreBlock _should_continue_explore with plan mode."""

    @pytest.mark.asyncio
    async def test_should_continue_with_active_plan(self):
        """Test _should_continue_explore returns True when plan is active."""
        # Create a minimal context with config
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        
        # Add a pending task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        
        block = ExploreBlock(context=context)
        
        # Hard constraint: must continue when plan is active
        assert block._should_continue_explore() is True
    
    @pytest.mark.asyncio
    async def test_should_continue_with_running_tasks(self):
        """Test _should_continue_explore with running tasks."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        
        # Add running task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        await context.task_registry.update_status("task_1", TaskStatus.RUNNING)
        
        block = ExploreBlock(context=context)
        
        assert block._should_continue_explore() is True
    
    @pytest.mark.asyncio
    async def test_should_continue_when_all_done(self):
        """Test _should_continue_explore when all tasks are done."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        
        # Add completed task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        await context.task_registry.update_status("task_1", TaskStatus.COMPLETED)
        
        block = ExploreBlock(context=context)
        
        # No active plan, should use normal logic
        assert context.has_active_plan() is False
        # Will depend on normal termination conditions
    
    def test_should_continue_plan_not_enabled(self):
        """Test _should_continue_explore when plan is not enabled."""
        config = GlobalConfig()
        context = Context(config=config)
        block = ExploreBlock(context=context)
        
        # Should use normal termination logic
        # When no tool calls, should_stop_exploration is True
        block.should_stop_exploration = True
        assert block._should_continue_explore() is False
    
    @pytest.mark.asyncio
    async def test_should_continue_max_calls_reached_with_active_plan(self):
        """Test plan mode does not bypass max calls limit."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        
        # Add pending task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        
        block = ExploreBlock(context=context)
        block.times = MAX_SKILL_CALL_TIMES
        
        # Plan mode must still be bounded to prevent infinite loops
        assert block._should_continue_explore() is False
    
    @pytest.mark.asyncio
    async def test_should_continue_repeated_calls_with_active_plan(self):
        """Test hard constraint overrides repeated calls limit."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        
        # Add pending task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        
        block = ExploreBlock(context=context)
        
        # Mock repeated calls detection
        mock_deduplicator = MagicMock()
        # Exceeds MAX_DUPLICATE_COUNT to trigger repeated calls detection
        excessive_call_count = DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT + 1
        mock_deduplicator.skillcalls = {"tool1": excessive_call_count}
        block.strategy = MagicMock()
        block.strategy.get_deduplicator.return_value = mock_deduplicator
        
        # Hard constraint overrides repeated calls detection
        assert block._should_continue_explore() is True

    @pytest.mark.asyncio
    async def test_plan_silent_rounds_terminates_on_no_progress_and_non_plan_tool(self):
        """Test plan silent rounds guard terminates when repeatedly making no progress."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()

        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.plan_silent_max_rounds = 2

        signature = tuple(
            (t.id, t.status.value)
            for t in sorted(context.task_registry.get_all_tasks(), key=lambda x: x.id)
        )
        block._plan_last_signature = signature
        block._plan_silent_rounds = 1
        block._last_tool_name = "unrelated_tool"

        with pytest.raises(ToolInterrupt):
            block._should_continue_explore()

    @pytest.mark.asyncio
    async def test_plan_silent_rounds_resets_when_using_plan_tool(self):
        """Test plan silent rounds reset when agent uses plan-related tools."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()

        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.plan_silent_max_rounds = 2

        signature = tuple(
            (t.id, t.status.value)
            for t in sorted(context.task_registry.get_all_tasks(), key=lambda x: x.id)
        )
        block._plan_last_signature = signature
        block._plan_silent_rounds = 1
        block._current_round_tools = ["_check_progress"]

        assert block._should_continue_explore() is True
        assert block._plan_silent_rounds == 0
    
    def test_should_continue_normal_termination(self):
        """Test normal termination conditions when plan is not active."""
        config = GlobalConfig()
        context = Context(config=config)
        block = ExploreBlock(context=context)
        
        # Normal case: should stop when should_stop_exploration is True
        block.should_stop_exploration = True
        assert block._should_continue_explore() is False
        
        # Normal case: should continue when no stop signal
        block.should_stop_exploration = False
        block.times = 0
        assert block._should_continue_explore() is True
