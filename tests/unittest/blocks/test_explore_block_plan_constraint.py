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
from dolphin.core.common.enums import StreamItem


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
        assert await block._should_continue_explore() is True
    
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
        
        assert await block._should_continue_explore() is True
    
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
        assert await context.has_active_plan() is False
        # Will depend on normal termination conditions
        block.should_stop_exploration = True
        assert await block._should_continue_explore() is False
    
    @pytest.mark.asyncio
    async def test_should_continue_plan_not_enabled(self):
        """Test _should_continue_explore when plan is not enabled."""
        config = GlobalConfig()
        context = Context(config=config)
        block = ExploreBlock(context=context)
        
        # Should use normal termination logic
        # When no tool calls, should_stop_exploration is True
        block.should_stop_exploration = True
        assert await block._should_continue_explore() is False
    
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
        assert await block._should_continue_explore() is False
    
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
        assert await block._should_continue_explore() is True

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
            for t in sorted(await context.task_registry.get_all_tasks(), key=lambda x: x.id)
        )
        block._plan_last_signature = signature
        block._plan_silent_rounds = 1
        block._last_tool_name = "unrelated_tool"

        with pytest.raises(ToolInterrupt):
            await block._should_continue_explore()

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
            for t in sorted(await context.task_registry.get_all_tasks(), key=lambda x: x.id)
        )
        block._plan_last_signature = signature
        block._plan_silent_rounds = 1
        block._current_round_tools = ["_check_progress"]

        assert await block._should_continue_explore() is True
        assert block._plan_silent_rounds == 0
    
    @pytest.mark.asyncio
    async def test_should_continue_normal_termination(self):
        """Test normal termination conditions when plan is not active."""
        config = GlobalConfig()
        context = Context(config=config)
        block = ExploreBlock(context=context)
        
        # Normal case: should stop when should_stop_exploration is True
        block.should_stop_exploration = True
        assert await block._should_continue_explore() is False
        
        # Normal case: should continue when no stop signal
        block.should_stop_exploration = False
        block.times = 0
        assert await block._should_continue_explore() is True

    # ===================== Bug 1: should_stop_exploration signal integrity =====================

    @pytest.mark.asyncio
    async def test_no_tool_call_sets_should_stop_true_even_with_active_plan(self):
        """After _handle_new_tool_call with no tool calls and active plan,
        should_stop_exploration must be True (not overridden to False)."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)
        await context.task_registry.update_status("task_1", TaskStatus.RUNNING)

        block = ExploreBlock(context=context)
        block.model = "gpt-4"
        block.content = "test"
        block.system_prompt = None
        block.output_var = "result"

        with patch.object(block, 'llm_chat_stream') as mock_llm:
            stream_item = StreamItem()
            stream_item.answer = "Waiting..."
            stream_item.tool_calls = []

            async def mock_stream(*args, **kwargs):
                yield stream_item

            mock_llm.side_effect = mock_stream

            async for _ in block._handle_new_tool_call(no_cache=True):
                pass

            assert block.should_stop_exploration is True, (
                "should_stop_exploration must be True when no tool call, "
                "even with active plan"
            )

    @pytest.mark.asyncio
    async def test_plan_mode_terminates_on_no_tool_call_no_progress(self):
        """With should_stop_exploration=True, no progress, no plan tool:
        _should_continue_explore returns False."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.should_stop_exploration = True
        # Set signature to current so has_progress=False
        signature = await context.task_registry.get_progress_signature()
        block._plan_last_signature = signature
        block._current_round_tools = []

        assert await block._should_continue_explore() is False, (
            "Should terminate: no tool call, no progress, no plan tool"
        )

    @pytest.mark.asyncio
    async def test_plan_mode_continues_on_no_tool_call_with_progress(self):
        """With should_stop_exploration=True but has_progress=True (first round):
        _should_continue_explore returns True."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.should_stop_exploration = True
        # _plan_last_signature=None means first round -> has_progress=True
        block._plan_last_signature = None

        assert await block._should_continue_explore() is True, (
            "Should continue: first round always has progress (signature change from None)"
        )

    # ===================== Bug 2: plan polling rounds limit =====================

    @pytest.mark.asyncio
    async def test_plan_polling_rounds_increments_on_plan_tool_without_progress(self):
        """Polling counter increments when plan tool used but no progress."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        signature = await context.task_registry.get_progress_signature()
        block._plan_last_signature = signature

        block._update_plan_silent_rounds(signature, has_progress=False, used_plan_tool=True)

        assert block._plan_polling_rounds == 1
        assert block._plan_silent_rounds == 0

    @pytest.mark.asyncio
    async def test_plan_polling_rounds_resets_on_progress(self):
        """Polling counter resets when actual progress occurs."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block._plan_polling_rounds = 50
        new_sig = (("task_1", "running"),)

        block._update_plan_silent_rounds(new_sig, has_progress=True, used_plan_tool=False)

        assert block._plan_polling_rounds == 0
        assert block._plan_silent_rounds == 0

    @pytest.mark.asyncio
    async def test_plan_polling_terminates_after_max_rounds(self):
        """ToolInterrupt raised when polling exceeds limit."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.plan_polling_max_rounds = 5
        block._plan_polling_rounds = 4
        signature = await context.task_registry.get_progress_signature()
        block._plan_last_signature = signature

        with pytest.raises(ToolInterrupt):
            block._update_plan_silent_rounds(
                signature, has_progress=False, used_plan_tool=True
            )

    @pytest.mark.asyncio
    async def test_plan_polling_does_not_terminate_with_progress(self):
        """No termination when progress is being made, even with high polling count."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await context.task_registry.add_task(task)

        block = ExploreBlock(context=context)
        block.plan_polling_max_rounds = 5
        block._plan_polling_rounds = 99  # would exceed if not reset
        new_sig = (("task_1", "completed"),)

        # Should NOT raise; progress resets both counters
        block._update_plan_silent_rounds(
            new_sig, has_progress=True, used_plan_tool=True
        )
        assert block._plan_polling_rounds == 0
