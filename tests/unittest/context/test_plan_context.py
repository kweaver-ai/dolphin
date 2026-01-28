"""Unit tests for Context Plan Mode support."""

import pytest

from dolphin.core.context.context import Context
from dolphin.core.task_registry import TaskRegistry, Task, TaskStatus


class TestPlanContext:
    """Test Context plan mode lifecycle."""

    @pytest.mark.asyncio
    async def test_enable_plan_first_time(self):
        """Test first call to enable_plan creates TaskRegistry."""
        context = Context()
        
        assert not context.is_plan_enabled()
        assert context.task_registry is None
        assert context.get_plan_id() is None
        
        await context.enable_plan()
        
        assert context.is_plan_enabled()
        assert context.task_registry is not None
        assert isinstance(context.task_registry, TaskRegistry)
        assert context.get_plan_id() is not None
    
    @pytest.mark.asyncio
    async def test_enable_plan_with_custom_id(self):
        """Test enable_plan with custom plan_id."""
        context = Context()
        custom_id = "test_plan_123"
        
        await context.enable_plan(plan_id=custom_id)
        
        assert context.is_plan_enabled()
        assert context.get_plan_id() == custom_id
    
    @pytest.mark.asyncio
    async def test_enable_plan_replan(self):
        """Test replan (calling enable_plan multiple times)."""
        context = Context()
        
        # First plan
        await context.enable_plan(plan_id="plan_1")
        registry1 = context.task_registry
        plan_id_1 = context.get_plan_id()
        
        # Add a task
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await registry1.add_task(task)
        
        assert registry1.has_tasks()
        
        # Replan
        await context.enable_plan(plan_id="plan_2")
        registry2 = context.task_registry
        plan_id_2 = context.get_plan_id()
        
        # Should have same registry instance
        assert registry2 is registry1
        # Should have new plan_id
        assert plan_id_2 != plan_id_1
        assert plan_id_2 == "plan_2"
        # Tasks should be cleared by reset()
        assert not registry2.has_tasks()
    
    @pytest.mark.asyncio
    async def test_disable_plan(self):
        """Test disable_plan cleans up resources."""
        context = Context()
        
        await context.enable_plan()
        assert context.is_plan_enabled()
        
        await context.disable_plan()
        
        assert not context.is_plan_enabled()
        assert context.task_registry is None
        assert context.get_plan_id() is None
    
    def test_has_active_plan_not_enabled(self):
        """Test has_active_plan when plan is not enabled."""
        context = Context()
        
        assert not context.has_active_plan()
    
    @pytest.mark.asyncio
    async def test_has_active_plan_no_tasks(self):
        """Test has_active_plan when plan is enabled but no tasks."""
        context = Context()
        
        await context.enable_plan()
        
        assert not context.has_active_plan()
    
    @pytest.mark.asyncio
    async def test_has_active_plan_with_tasks(self):
        """Test has_active_plan with non-terminal tasks."""
        context = Context()
        await context.enable_plan()
        
        # Add pending task
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        await context.task_registry.add_task(task1)
        
        assert context.has_active_plan()
        
        # Mark task as running
        await context.task_registry.update_status("task_1", TaskStatus.RUNNING)
        assert context.has_active_plan()
        
        # Mark task as completed
        await context.task_registry.update_status("task_1", TaskStatus.COMPLETED)
        assert not context.has_active_plan()
    
    @pytest.mark.asyncio
    async def test_has_active_plan_all_terminal(self):
        """Test has_active_plan when all tasks are in terminal states."""
        context = Context()
        await context.enable_plan()
        
        # Add tasks
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3")
        
        await context.task_registry.add_task(task1)
        await context.task_registry.add_task(task2)
        await context.task_registry.add_task(task3)
        
        assert context.has_active_plan()
        
        # Mark all as terminal states
        await context.task_registry.update_status("task_1", TaskStatus.COMPLETED)
        await context.task_registry.update_status("task_2", TaskStatus.FAILED)
        await context.task_registry.update_status("task_3", TaskStatus.CANCELLED)
        
        assert not context.has_active_plan()
    
    @pytest.mark.asyncio
    async def test_fork_creates_cow_context(self):
        """Test fork creates COWContext."""
        context = Context()
        await context.enable_plan()
        
        child = context.fork("task_1")
        
        assert child is not None
        assert hasattr(child, 'parent')
        assert child.parent is context
        assert hasattr(child, 'task_id')
        assert child.task_id == "task_1"
