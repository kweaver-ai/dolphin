"""Unit tests for TaskRegistry."""

import pytest
import asyncio

from dolphin.core.task_registry import TaskRegistry, Task, TaskStatus, PlanExecMode


class TestTaskRegistry:
    """Test TaskRegistry functionality."""

    @pytest.mark.asyncio
    async def test_registry_initialization(self):
        """Test TaskRegistry initialization."""
        registry = TaskRegistry()
        
        assert registry.tasks == {}
        assert registry.exec_mode == PlanExecMode.PARALLEL
        assert registry.max_concurrency == 5
        assert not await registry.has_tasks()
    
    @pytest.mark.asyncio
    async def test_add_task(self):
        """Test adding tasks to registry."""
        registry = TaskRegistry()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        
        await registry.add_task(task)
        
        assert await registry.has_tasks()
        assert await registry.get_task("task_1") is task
    
    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        """Test getting non-existent task returns None."""
        registry = TaskRegistry()
        
        assert await registry.get_task("nonexistent") is None
    
    @pytest.mark.asyncio
    async def test_get_all_tasks(self):
        """Test getting all tasks."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        
        all_tasks = await registry.get_all_tasks()
        assert len(all_tasks) == 2
        assert task1 in all_tasks
        assert task2 in all_tasks
    
    @pytest.mark.asyncio
    async def test_get_pending_tasks(self):
        """Test getting pending tasks."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.PENDING)
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2", status=TaskStatus.RUNNING)
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3", status=TaskStatus.PENDING)
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        await registry.add_task(task3)
        
        pending = await registry.get_pending_tasks()
        assert len(pending) == 2
        assert task1 in pending
        assert task3 in pending
    
    @pytest.mark.asyncio
    async def test_get_ready_tasks_phase1(self):
        """Test get_ready_tasks (Phase 1: returns all PENDING)."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.PENDING)
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2", status=TaskStatus.RUNNING)
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3", status=TaskStatus.PENDING)
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        await registry.add_task(task3)
        
        ready = await registry.get_ready_tasks()
        
        # Phase 1: all PENDING tasks are ready
        assert len(ready) == 2
        assert task1 in ready
        assert task3 in ready
    
    @pytest.mark.asyncio
    async def test_update_status(self):
        """Test updating task status."""
        registry = TaskRegistry()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await registry.add_task(task)
        
        assert task.status == TaskStatus.PENDING
        
        await registry.update_status("task_1", TaskStatus.RUNNING)
        assert task.status == TaskStatus.RUNNING
        
        await registry.update_status("task_1", TaskStatus.COMPLETED, answer="Result")
        assert task.status == TaskStatus.COMPLETED
        assert task.answer == "Result"
    
    @pytest.mark.asyncio
    async def test_update_status_with_duration(self):
        """Test update_status computes duration for terminal states."""
        import time
        
        registry = TaskRegistry()
        task = Task(id="task_1", name="Test Task", prompt="Test prompt")
        await registry.add_task(task)
        
        # Start task
        start_time = time.time()
        await registry.update_status("task_1", TaskStatus.RUNNING, started_at=start_time)
        
        # Wait a bit
        await asyncio.sleep(0.1)
        
        # Complete task
        await registry.update_status("task_1", TaskStatus.COMPLETED)
        
        assert task.duration is not None
        assert task.duration > 0
    
    @pytest.mark.asyncio
    async def test_reset(self):
        """Test reset clears tasks."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        registry.exec_mode = PlanExecMode.SEQUENTIAL
        registry.max_concurrency = 10
        
        assert await registry.has_tasks()
        
        await registry.reset()
        
        # Tasks cleared
        assert not await registry.has_tasks()
        # Config preserved
        assert registry.exec_mode == PlanExecMode.SEQUENTIAL
        assert registry.max_concurrency == 10
    
    @pytest.mark.asyncio
    async def test_is_all_done_terminal_states(self):
        """Test is_all_done with all terminal states."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3")
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        await registry.add_task(task3)
        
        assert not await registry.is_all_done()
        
        await registry.update_status("task_1", TaskStatus.COMPLETED)
        assert not await registry.is_all_done()
        
        await registry.update_status("task_2", TaskStatus.FAILED)
        assert not await registry.is_all_done()
        
        await registry.update_status("task_3", TaskStatus.CANCELLED)
        assert await registry.is_all_done()
    
    @pytest.mark.asyncio
    async def test_get_status_counts(self):
        """Test getting status counts."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.PENDING)
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2", status=TaskStatus.RUNNING)
        task3 = Task(id="task_3", name="Task 3", prompt="Prompt 3", status=TaskStatus.COMPLETED)
        task4 = Task(id="task_4", name="Task 4", prompt="Prompt 4", status=TaskStatus.FAILED)
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        await registry.add_task(task3)
        await registry.add_task(task4)
        
        counts = await registry.get_status_counts()
        
        assert counts["pending"] == 1
        assert counts["running"] == 1
        assert counts["completed"] == 1
        assert counts["failed"] == 1
        assert counts["cancelled"] == 0
    
    @pytest.mark.asyncio
    async def test_get_all_status_format(self):
        """Test get_all_status returns formatted string."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1", status=TaskStatus.PENDING)
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2", status=TaskStatus.COMPLETED, duration=1.5)
        
        await registry.add_task(task1)
        await registry.add_task(task2)
        
        status = await registry.get_all_status()
        
        assert "task_1" in status
        assert "Task 1" in status
        assert "pending" in status
        assert "task_2" in status
        assert "Task 2" in status
        assert "completed" in status
    
    @pytest.mark.asyncio
    async def test_cancel_all_running(self):
        """Test cancel_all_running cancels asyncio tasks."""
        registry = TaskRegistry()
        
        async def dummy_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
        
        # Create and store asyncio tasks
        task1 = asyncio.create_task(dummy_task())
        task2 = asyncio.create_task(dummy_task())
        
        registry.running_asyncio_tasks["task_1"] = task1
        registry.running_asyncio_tasks["task_2"] = task2
        
        cancelled = await registry.cancel_all_running()
        
        assert cancelled == 2
        assert len(registry.running_asyncio_tasks) == 0
        
        # Wait for cancellation to propagate
        try:
            await task1
        except asyncio.CancelledError:
            pass
        try:
            await task2
        except asyncio.CancelledError:
            pass
        
        assert task1.cancelled()
        assert task2.cancelled()
