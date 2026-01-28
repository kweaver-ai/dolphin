import pytest
import asyncio
from dolphin.core.context.context import Context
from dolphin.core.task_registry import Task, TaskStatus
from dolphin.lib.skillkits.plan_skillkit import PlanSkillkit

class TestPlanReconciliation:
    """Test reconciliation of plan tasks after snapshot/restore."""

    @pytest.mark.asyncio
    async def test_reconciliation_after_restore(self):
        """Verify that tasks marked RUNNING in registry but missing asyncio tasks are restarted."""
        context = Context()
        plan_id = "reconciliation_test"
        await context.enable_plan(plan_id=plan_id)
        
        # Add a task
        task1 = Task(id="task_1", name="Task 1", prompt="Prompt 1")
        await context.task_registry.add_task(task1)
        
        # Manually mark as RUNNING (simulating a state where it was running but the asyncio task is lost)
        await context.task_registry.update_status("task_1", TaskStatus.RUNNING)
        
        # Snapshot and restore to a new context (although we don't strictly need to restore, 
        # just having a new PlanSkillkit instance is enough)
        snapshot = context.export_runtime_state(frame_id="frame_1")
        
        new_context = Context()
        new_context.apply_runtime_state(snapshot)
        
        # Create a new PlanSkillkit
        skillkit = PlanSkillkit(context=new_context)

        # At this point, task_1 is RUNNING in registry, but running_asyncio_tasks is empty.
        # Note: tasks are now managed in TaskRegistry.running_asyncio_tasks
        assert "task_1" not in new_context.task_registry.running_asyncio_tasks
        assert new_context.task_registry.get_task("task_1").status == TaskStatus.RUNNING

        # Call _check_progress which should trigger reconciliation
        # Note: we need to mock or ensure _spawn_task doesn't actually try to run an ExploreBlock
        # because we don't have a full environment here.
        # But wait, PlanSkillkit uses ExploreBlock which needs LLM etc.

        # Let's patch _spawn_task to just record it was called
        spawned_tasks = []
        async def mock_spawn(tid):
            spawned_tasks.append(tid)
        original_spawn = skillkit._spawn_task
        skillkit._spawn_task = mock_spawn

        await skillkit._check_progress()

        assert "task_1" in spawned_tasks, "Task 1 should have been restarted by reconciliation"
