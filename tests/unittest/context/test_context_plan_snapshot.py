import pytest
from dolphin.core.context.context import Context
from dolphin.core.task_registry import Task, TaskStatus

class TestContextPlanSnapshot:
    """Test Context plan mode state snapshot and restore."""

    @pytest.mark.asyncio
    async def test_snapshot_restore_plan_state(self):
        """Verify that plan state is correctly preserved across snapshot/apply."""
        context = Context()
        plan_id = "test_snapshot_plan"
        await context.enable_plan(plan_id=plan_id)
        
        # Add some tasks and set status
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        await context.task_registry.add_task(task1)
        await context.task_registry.update_status("task_1", TaskStatus.COMPLETED, answer="Answer 1")
        
        task2 = Task(id="task_2", name="Task 2", prompt="Prompt 2")
        await context.task_registry.add_task(task2)
        await context.task_registry.update_status("task_2", TaskStatus.RUNNING)
        
        # Export state
        snapshot = context.export_runtime_state(frame_id="test_frame")
        
        # Verify snapshot content (optional, but good for debugging)
        # print(f"Snapshot variables: {snapshot.variables}")
        # print(f"Snapshot context_manager_state: {snapshot.context_manager_state}")
        
        # Apply to a new context
        new_context = Context()
        new_context.apply_runtime_state(snapshot)
        
        # VERIFY Plan state
        # 1. Plan should be enabled
        assert new_context.is_plan_enabled(), "Plan mode should be enabled after restore"
        # 2. Plan ID should match
        assert new_context.get_plan_id() == plan_id, f"Plan ID mismatch: expected {plan_id}, got {new_context.get_plan_id()}"
        # 3. Task registry should exist and have tasks
        assert await new_context.task_registry.has_tasks(), "Restored TaskRegistry should have tasks"
        
        # 4. Verify specific tasks
        restored_task1 = await new_context.task_registry.get_task("task_1")
        assert restored_task1 is not None
        assert restored_task1.status == TaskStatus.COMPLETED
        assert restored_task1.answer == "Answer 1"
        
        restored_task2 = await new_context.task_registry.get_task("task_2")
        assert restored_task2 is not None
        assert restored_task2.status == TaskStatus.RUNNING
