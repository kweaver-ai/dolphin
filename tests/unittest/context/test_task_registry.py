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
        """Test reset clears tasks and gracefully cancels running tasks."""
        registry = TaskRegistry()
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")

        await registry.add_task(task1)
        await registry.add_task(task2)
        registry.exec_mode = PlanExecMode.SEQUENTIAL
        registry.max_concurrency = 10

        # Add a running task that responds quickly to cancellation
        async def dummy_task():
            try:
                await asyncio.sleep(0.5)  # Short sleep
            except asyncio.CancelledError:
                raise

        asyncio_task = asyncio.create_task(dummy_task())
        registry.running_asyncio_tasks["task_1"] = asyncio_task

        assert await registry.has_tasks()
        assert len(registry.running_asyncio_tasks) == 1

        # Reset with reasonable timeout
        await registry.reset(cancel_timeout=1.0)

        # Tasks cleared
        assert not await registry.has_tasks()
        # Running tasks cleared
        assert len(registry.running_asyncio_tasks) == 0
        # Task was cancelled
        assert asyncio_task.cancelled()
        # Config preserved
        assert registry.exec_mode == PlanExecMode.SEQUENTIAL
        assert registry.max_concurrency == 10

    @pytest.mark.asyncio
    async def test_reset_with_slow_cleanup(self):
        """Test reset waits for tasks to complete cleanup."""
        registry = TaskRegistry()

        cleanup_done = asyncio.Event()
        task_started = asyncio.Event()

        async def cleanup_task():
            task_started.set()
            try:
                await asyncio.sleep(0.5)  # Short initial sleep
            except asyncio.CancelledError:
                await asyncio.sleep(0.1)  # Quick cleanup
                cleanup_done.set()
                raise

        task = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        await registry.add_task(task)

        asyncio_task = asyncio.create_task(cleanup_task())
        registry.running_asyncio_tasks["task_1"] = asyncio_task

        # Wait for task to start
        await task_started.wait()

        # Reset with sufficient timeout
        await registry.reset(cancel_timeout=1.0)

        # Verify cleanup completed
        assert cleanup_done.is_set()
        assert not await registry.has_tasks()
        assert len(registry.running_asyncio_tasks) == 0
    
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
        """Test cancel_all_running cancels asyncio tasks and waits for completion."""
        registry = TaskRegistry()

        async def dummy_task():
            try:
                await asyncio.sleep(0.5)  # Short sleep
            except asyncio.CancelledError:
                raise

        # Create and store asyncio tasks
        task1 = asyncio.create_task(dummy_task())
        task2 = asyncio.create_task(dummy_task())

        registry.running_asyncio_tasks["task_1"] = task1
        registry.running_asyncio_tasks["task_2"] = task2

        result = await registry.cancel_all_running()

        # Check new return format
        assert result["cancelled"] == 2
        assert result["timeout"] == 0
        assert result["task_ids"] == []
        assert len(registry.running_asyncio_tasks) == 0

        # Verify tasks are done
        assert task1.cancelled()
        assert task2.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_all_running_waits_for_completion(self):
        """Test cancel_all_running waits for tasks to complete their cleanup."""
        registry = TaskRegistry()

        cleanup_done = asyncio.Event()
        task_started = asyncio.Event()

        async def cleanup_task():
            task_started.set()
            try:
                await asyncio.sleep(0.5)  # Short sleep
            except asyncio.CancelledError:
                # Simulate cleanup (e.g., closing file handles)
                await asyncio.sleep(0.05)
                cleanup_done.set()
                raise

        # Create task and add to registry with metadata
        task = Task(id="task_1", name="task with cleanup", prompt="test")
        await registry.add_task(task)

        import time
        await registry.update_status("task_1", TaskStatus.RUNNING, started_at=time.time())

        asyncio_task = asyncio.create_task(cleanup_task())
        registry.running_asyncio_tasks["task_1"] = asyncio_task

        # Wait for task to actually start
        await task_started.wait()

        # Cancel and wait
        result = await registry.cancel_all_running(timeout=1.0)

        # Verify task completed cleanup
        assert cleanup_done.is_set(), "Cleanup should have executed"
        assert result["cancelled"] == 1
        assert result["timeout"] == 0
        assert asyncio_task.done()
        assert len(registry.running_asyncio_tasks) == 0

        # Verify task status was updated
        task_obj = await registry.get_task("task_1")
        assert task_obj.status == TaskStatus.CANCELLED
        assert task_obj.duration is not None

    @pytest.mark.asyncio
    async def test_cancel_all_running_force_cleanup(self):
        """Test cancel_all_running with force=True clears registry.

        This verifies the key safety mechanism: force=True ensures registry
        cleanup even if tasks take time to complete.
        """
        registry = TaskRegistry()

        cleanup_started = asyncio.Event()
        task_started = asyncio.Event()

        async def task_with_cleanup():
            task_started.set()
            try:
                await asyncio.sleep(0.5)  # Short sleep
            except asyncio.CancelledError:
                cleanup_started.set()
                # Simulate cleanup
                await asyncio.sleep(0.1)
                raise

        # Create task and add to registry
        import time
        task = Task(id="task_1", name="task with cleanup", prompt="test")
        await registry.add_task(task)
        await registry.update_status("task_1", TaskStatus.RUNNING, started_at=time.time())

        asyncio_task = asyncio.create_task(task_with_cleanup())
        registry.running_asyncio_tasks["task_1"] = asyncio_task

        # Wait for task to start
        await task_started.wait()

        # Cancel with force=True
        result = await registry.cancel_all_running(timeout=1.0, force=True)

        # Verify cleanup was started
        assert cleanup_started.is_set()

        # Key assertion: force cleanup cleared registry
        assert len(registry.running_asyncio_tasks) == 0

        # Task was processed
        assert result["cancelled"] >= 1

    @pytest.mark.asyncio
    async def test_cancel_all_running_empty_registry(self):
        """Test cancel_all_running with no running tasks."""
        registry = TaskRegistry()

        result = await registry.cancel_all_running()

        assert result["cancelled"] == 0
        assert result["timeout"] == 0
        assert result["task_ids"] == []

    @pytest.mark.asyncio
    async def test_cancel_all_running_already_done_tasks(self):
        """Test cancel_all_running skips already completed tasks."""
        registry = TaskRegistry()

        async def quick_task():
            await asyncio.sleep(0.01)
            return "done"

        asyncio_task = asyncio.create_task(quick_task())
        await asyncio_task  # Wait for it to complete

        registry.running_asyncio_tasks["task_1"] = asyncio_task

        result = await registry.cancel_all_running()

        assert result["cancelled"] == 0
        assert result["timeout"] == 0
        assert len(registry.running_asyncio_tasks) == 0

    def test_task_from_dict_supports_legacy_output_field(self):
        """Test Task.from_dict supports the legacy 'output' field for backward compatibility."""
        task = Task.from_dict({
            "id": "task_1",
            "name": "Task 1",
            "prompt": "Prompt 1",
            "status": TaskStatus.COMPLETED.value,
            "output": "Legacy output",
        })
        assert task.answer == "Legacy output"
