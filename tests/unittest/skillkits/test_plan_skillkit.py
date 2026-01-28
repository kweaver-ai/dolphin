"""Unit tests for PlanSkillkit."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from dolphin.core.context.context import Context
from dolphin.core.context.cow_context import COWContext
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.task_registry import TaskStatus
from dolphin.lib.skillkits.plan_skillkit import PlanSkillkit


class TestPlanSkillkit:
    """Test PlanSkillkit tool methods."""

    def test_plan_skillkit_initialization(self):
        """Test PlanSkillkit initialization."""
        context = Context()
        skillkit = PlanSkillkit(context)

        assert skillkit.context is context
        # Note: running_tasks has been removed - tasks are managed in TaskRegistry.running_asyncio_tasks
        assert skillkit.max_concurrency == 5

    def test_subtask_explore_block_content_is_valid_dph(self):
        """Test subtask ExploreBlock content is parsable by BasicCodeBlock."""
        block_content = PlanSkillkit._build_subtask_explore_block_content("Do something")

        context = Context()
        block = BasicCodeBlock(context=context)
        block.parse_block_content(block_content, category=CategoryBlock.EXPLORE, replace_variables=False)
        assert block.content == "Do something"

    def test_subtask_explore_block_content_prompt_starts_with_paren(self):
        """Test prompt starting with '(' is parsed as content, not params."""
        block_content = PlanSkillkit._build_subtask_explore_block_content("(Do something)")

        context = Context()
        block = BasicCodeBlock(context=context)
        block.parse_block_content(block_content, category=CategoryBlock.EXPLORE, replace_variables=False)
        assert block.content == "(Do something)"

    @pytest.mark.asyncio
    async def test_plan_tasks_in_subtask_context_returns_friendly_error(self):
        """Test _plan_tasks raises RuntimeError in COWContext."""
        parent = Context()
        child = COWContext(parent, "task_1")
        skillkit = PlanSkillkit(child)

        tasks = [{"id": "task_1", "name": "Task 1", "prompt": "Do task 1"}]

        with pytest.raises(RuntimeError, match="Nested planning is not supported"):
            await skillkit._plan_tasks(tasks)
    
    @pytest.mark.asyncio
    async def test_plan_tasks_enables_plan_mode(self):
        """Test _plan_tasks enables plan mode if not enabled."""
        context = Context()
        skillkit = PlanSkillkit(context)
        
        tasks = [
            {"id": "task_1", "name": "Task 1", "prompt": "Do task 1"},
            {"id": "task_2", "name": "Task 2", "prompt": "Do task 2"},
        ]
        
        # Mock write_output to avoid errors
        context.write_output = MagicMock()
        
        # Mock _spawn_task to avoid creating actual async tasks
        with patch.object(skillkit, '_spawn_task'):
            result = await skillkit._plan_tasks(tasks)
        
        assert context.is_plan_enabled()
        assert context.task_registry is not None
        all_tasks = await context.task_registry.get_all_tasks()
        assert len(all_tasks) == 2
        assert "Plan initialized with 2 tasks" in result
    
    @pytest.mark.asyncio
    async def test_plan_tasks_validation_errors(self):
        """Test _plan_tasks validation."""
        context = Context()
        context.write_output = MagicMock()
        skillkit = PlanSkillkit(context)
        
        # Empty task list
        result = await skillkit._plan_tasks([])
        assert "Validation failed" in result
        assert "Empty task list" in result
        
        # Missing id
        result = await skillkit._plan_tasks([{"name": "Task", "prompt": "Prompt"}])
        assert "Validation failed" in result
        assert "missing 'id'" in result
        
        # Missing name
        result = await skillkit._plan_tasks([{"id": "task_1", "prompt": "Prompt"}])
        assert "Validation failed" in result
        assert "missing 'name'" in result
        
        # Missing prompt
        result = await skillkit._plan_tasks([{"id": "task_1", "name": "Task"}])
        assert "Validation failed" in result
        assert "missing 'prompt'" in result
        
        # Duplicate IDs
        tasks = [
            {"id": "task_1", "name": "Task 1", "prompt": "Prompt 1"},
            {"id": "task_1", "name": "Task 2", "prompt": "Prompt 2"},
        ]
        result = await skillkit._plan_tasks(tasks)
        assert "Validation failed" in result
        assert "Duplicate task ID" in result
    
    @pytest.mark.asyncio
    async def test_plan_tasks_parallel_mode(self):
        """Test _plan_tasks in parallel mode."""
        context = Context()
        context.write_output = MagicMock()
        skillkit = PlanSkillkit(context)
        
        tasks = [
            {"id": "task_1", "name": "Task 1", "prompt": "Prompt 1"},
            {"id": "task_2", "name": "Task 2", "prompt": "Prompt 2"},
        ]
        
        with patch.object(skillkit, '_spawn_task') as mock_spawn:
            result = await skillkit._plan_tasks(tasks, exec_mode="para")
            
            assert "parallel mode" in result
            # Should spawn both tasks
            assert mock_spawn.call_count == 2
    
    @pytest.mark.asyncio
    async def test_plan_tasks_sequential_mode(self):
        """Test _plan_tasks in sequential mode."""
        context = Context()
        context.write_output = MagicMock()
        skillkit = PlanSkillkit(context)
        
        tasks = [
            {"id": "task_1", "name": "Task 1", "prompt": "Prompt 1"},
            {"id": "task_2", "name": "Task 2", "prompt": "Prompt 2"},
        ]
        
        with patch.object(skillkit, '_spawn_task') as mock_spawn:
            result = await skillkit._plan_tasks(tasks, exec_mode="seq")
            
            assert "sequential mode" in result
            # Should spawn only first task
            assert mock_spawn.call_count == 1
    
    @pytest.mark.asyncio
    async def test_check_progress_not_enabled(self):
        """Test _check_progress raises RuntimeError when plan is not enabled."""
        context = Context()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="Plan is not enabled"):
            await skillkit._check_progress()
    
    @pytest.mark.asyncio
    async def test_check_progress_with_tasks(self):
        """Test _check_progress with tasks."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)
        
        # Add tasks with different statuses
        from dolphin.core.task_registry import Task
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.COMPLETED)
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2", status=TaskStatus.RUNNING)
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3", status=TaskStatus.PENDING)
        
        await context.task_registry.add_task(task1)
        await context.task_registry.add_task(task2)
        await context.task_registry.add_task(task3)
        
        # Mock _spawn_task to prevent reconciliation from starting real execution
        with patch.object(skillkit, '_spawn_task'):
            result = await skillkit._check_progress()
        
        assert "Task Status:" in result
        assert "task_1" in result
        assert "task_2" in result
        assert "task_3" in result
        assert "Summary:" in result
        assert "1 completed" in result
        assert "1 running" in result

    @pytest.mark.asyncio
    async def test_check_progress_auto_injects_outputs_once_when_all_done(self):
        """Test _check_progress auto-injects task outputs once when plan is done."""
        context = Context()
        await context.enable_plan(plan_id="plan_1")
        skillkit = PlanSkillkit(context)

        from dolphin.core.task_registry import Task

        task1 = Task(
            id="task_1",
            name="Task 1",
            prompt="Prompt 1",
            status=TaskStatus.COMPLETED,
            answer="Output 1",
        )
        task2 = Task(
            id="task_2",
            name="Task 2",
            prompt="Prompt 2",
            status=TaskStatus.COMPLETED,
            answer="Output 2",
        )
        await context.task_registry.add_task(task1)
        await context.task_registry.add_task(task2)

        first = await skillkit._check_progress()
        assert "✅ All tasks completed!" in first
        assert "=== Task Outputs (Auto) ===" in first
        assert "=== task_1: Task 1 ===" in first
        assert "Output 1" in first

        injected_var = "_plan.outputs_auto_injected.plan_1"
        assert context.get_var_value(injected_var, False) is True

        second = await skillkit._check_progress()
        assert "✅ All tasks completed!" in second
        assert "=== Task Outputs (Auto) ===" not in second
    
    @pytest.mark.asyncio
    async def test_get_output_not_enabled(self):
        """Test _get_task_output raises RuntimeError when plan is not enabled."""
        context = Context()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="Plan is not enabled"):
            await skillkit._get_task_output(task_id="task_1")
    
    @pytest.mark.asyncio
    async def test_get_output_task_not_found(self):
        """Test _get_task_output raises RuntimeError with non-existent task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="not found"):
            await skillkit._get_task_output(task_id="nonexistent")
    
    @pytest.mark.asyncio
    async def test_get_output_task_not_completed(self):
        """Test _get_task_output raises RuntimeError with non-completed task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        from dolphin.core.task_registry import Task
        task = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.RUNNING)
        await context.task_registry.add_task(task)

        with pytest.raises(RuntimeError, match="not completed"):
            await skillkit._get_task_output(task_id="task_1")
    
    @pytest.mark.asyncio
    async def test_get_output_success(self):
        """Test _get_task_output with completed task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        from dolphin.core.task_registry import Task
        task = Task(
            id="task_1",
            name="Task 1",
            prompt="Prompt 1",
            status=TaskStatus.COMPLETED,
            answer="Task result"
        )
        await context.task_registry.add_task(task)

        result = await skillkit._get_task_output(task_id="task_1")

        assert result == "Task result"
    
    @pytest.mark.asyncio
    async def test_wait(self):
        """Test _wait method."""
        context = Context()
        skillkit = PlanSkillkit(context)
        
        # Mock check_user_interrupt
        context.check_user_interrupt = MagicMock()
        
        result = await skillkit._wait(1.0)
        
        assert "Waited" in result
        # Should have checked interrupt (once per second)
        assert context.check_user_interrupt.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_kill_task_not_enabled(self):
        """Test _kill_task raises RuntimeError when plan is not enabled."""
        context = Context()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="Plan is not enabled"):
            await skillkit._kill_task("task_1")
    
    @pytest.mark.asyncio
    async def test_kill_task_not_running(self):
        """Test _kill_task raises RuntimeError with non-running task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="is not running"):
            await skillkit._kill_task("task_1")
    
    @pytest.mark.asyncio
    async def test_kill_task_success(self):
        """Test _kill_task successfully cancels task."""
        import asyncio

        context = Context()
        await context.enable_plan()
        context.write_output = MagicMock()
        skillkit = PlanSkillkit(context)

        # Create a dummy asyncio task
        async def dummy():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(dummy())
        # Note: tasks are now managed in TaskRegistry.running_asyncio_tasks
        context.task_registry.running_asyncio_tasks["task_1"] = task

        from dolphin.core.task_registry import Task
        registry_task = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        await context.task_registry.add_task(registry_task)

        result = await skillkit._kill_task("task_1")

        assert "cancellation requested" in result
        # Task should still be in running_asyncio_tasks (cleanup happens in task's finally block)
        assert "task_1" in context.task_registry.running_asyncio_tasks

        # Wait for cancellation to propagate
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert task.cancelled()
    
    @pytest.mark.asyncio
    async def test_retry_task_not_enabled(self):
        """Test _retry_task raises RuntimeError when plan is not enabled."""
        context = Context()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="Plan is not enabled"):
            await skillkit._retry_task("task_1")
    
    @pytest.mark.asyncio
    async def test_retry_task_not_found(self):
        """Test _retry_task raises RuntimeError with non-existent task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        with pytest.raises(RuntimeError, match="not found"):
            await skillkit._retry_task("nonexistent")
    
    @pytest.mark.asyncio
    async def test_retry_task_cannot_retry(self):
        """Test _retry_task raises RuntimeError with non-failed task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        from dolphin.core.task_registry import Task
        task = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.COMPLETED)
        await context.task_registry.add_task(task)

        with pytest.raises(RuntimeError, match="cannot be retried"):
            await skillkit._retry_task("task_1")
    
    @pytest.mark.asyncio
    async def test_retry_task_cannot_retry_cancelled(self):
        """Test _retry_task raises RuntimeError with cancelled task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)

        from dolphin.core.task_registry import Task
        task = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.CANCELLED)
        await context.task_registry.add_task(task)

        with pytest.raises(RuntimeError, match="cannot be retried"):
            await skillkit._retry_task("task_1")
    
    @pytest.mark.asyncio
    async def test_retry_task_success(self):
        """Test _retry_task successfully restarts task."""
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)
        
        from dolphin.core.task_registry import Task
        task = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.FAILED)
        await context.task_registry.add_task(task)
        
        with patch.object(skillkit, '_spawn_task') as mock_spawn:
            result = await skillkit._retry_task("task_1")
            
            assert "restarted" in result
            assert task.status == TaskStatus.PENDING
            assert mock_spawn.called

    @pytest.mark.asyncio
    async def test_check_progress_parallel_running(self):
        """Test _check_progress when multiple tasks are running (parallel mode)."""
        import time
        from dolphin.core.task_registry import Task
        
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)
        
        # Mocking 3 tasks running simultaneously with different start times
        now = time.time()
        task1 = Task(id="t1", name="Task 1", prompt="P1", status=TaskStatus.RUNNING, started_at=now - 10)
        task2 = Task(id="t2", name="Task 2", prompt="P2", status=TaskStatus.RUNNING, started_at=now - 5)
        task3 = Task(id="t3", name="Task 3", prompt="P3", status=TaskStatus.RUNNING, started_at=now - 2)
        
        await context.task_registry.add_task(task1)
        await context.task_registry.add_task(task2)
        await context.task_registry.add_task(task3)
        
        # Mock _spawn_task to prevent reconciliation from starting real execution
        with patch.object(skillkit, '_spawn_task'):
            result = await skillkit._check_progress()
        
        # Verify that all 3 tasks are listed as running
        assert "🔄 t1: Task 1 [running] (10.0s+)" in result
        assert "🔄 t2: Task 2 [running] (5.0s+)" in result
        assert "🔄 t3: Task 3 [running] (2.0s+)" in result
        assert "Summary: 0 completed, 3 running, 0 failed" in result

    @pytest.mark.asyncio
    async def test_check_progress_throttling(self):
        """Test _check_progress throttling guidance when polled too frequently with same status."""
        import time
        from dolphin.core.task_registry import Task
        
        context = Context()
        await context.enable_plan()
        skillkit = PlanSkillkit(context)
        
        task1 = Task(id="t1", name="Task 1", prompt="P1", status=TaskStatus.RUNNING, started_at=time.time())
        await context.task_registry.add_task(task1)
        
        with patch.object(skillkit, '_spawn_task'):
            first = await skillkit._check_progress()
            assert "Polling Guidance" not in first

            # Second call immediately after should trigger the 2s debounce/throttle
            # Item 5 optimization: interval < 2.0s now returns early with specialized message
            second = await skillkit._check_progress()
            assert "Status Unchanged (checked too recently)" in second
            assert "Guidance: Subtasks need time" in second
