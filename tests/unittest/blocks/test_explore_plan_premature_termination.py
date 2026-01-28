"""Integration test for plan mode premature termination issue.

This test reproduces the issue where explore block terminates before all
plan tasks are completed, even though has_active_plan() should prevent it.
"""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.task_registry import Task, TaskStatus, TaskRegistry
from dolphin.core.common.enums import MessageRole
from dolphin.lib.skillkits.plan_skillkit import PlanSkillkit


class TestExplorePlanPrematureTermination:
    """Integration tests for plan mode termination behavior."""

    @pytest_asyncio.fixture
    async def context_with_plan(self):
        """Create a context with plan mode enabled."""
        config = GlobalConfig()
        context = Context(config=config)
        await context.enable_plan()
        return context

    @pytest.fixture
    def mock_llm_responses(self):
        """Mock LLM responses for different scenarios."""
        return {
            "plan_tasks_call": {
                "answer": "Planning tasks...",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "_plan_tasks",
                        "arguments": '{"tasks": [{"id": "task_1", "name": "Task 1", "prompt": "Do task 1"}]}'
                    }
                }]
            },
            "check_progress_call": {
                "answer": "Checking progress...",
                "tool_calls": [{
                    "id": "call_2",
                    "function": {
                        "name": "_check_progress",
                        "arguments": "{}"
                    }
                }]
            },
            "no_tool_call": {
                "answer": "All tasks are running, waiting for completion.",
                "tool_calls": []
            }
        }

    @pytest.mark.asyncio
    async def test_explore_waits_for_running_tasks(self, context_with_plan):
        """Test that has_active_plan() prevents premature termination.
        
        This is a simplified test that verifies the core logic without
        full execute() flow complexity. The integration test
        test_stream_exploration_respects_plan_constraint already validates
        the complete behavior.
        """
        # Setup: Add tasks
        task1 = Task(id="task_1", name="Task 1", prompt="Test")
        task2 = Task(id="task_2", name="Task 2", prompt="Test")
        await context_with_plan.task_registry.add_task(task1)
        await context_with_plan.task_registry.add_task(task2)

        # Set one task as RUNNING, one as COMPLETED
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.RUNNING)
        await context_with_plan.task_registry.update_status("task_2", TaskStatus.COMPLETED)

        explore = ExploreBlock(context=context_with_plan)

        # Verify plan is active (has non-terminal tasks)
        assert context_with_plan.has_active_plan() is True, (
            "Plan should be active with 1 running task"
        )

        # Verify explore should continue despite should_stop_exploration flag
        explore.should_stop_exploration = True
        assert explore._should_continue_explore() is True, (
            "ExploreBlock should continue when plan has active tasks"
        )

        # Now complete all tasks
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.COMPLETED)

        # Verify plan is no longer active
        assert context_with_plan.has_active_plan() is False, (
            "Plan should not be active when all tasks are completed"
        )

        # Verify explore can now terminate
        assert explore._should_continue_explore() is False, (
            "ExploreBlock should terminate when plan has no active tasks"
        )

    @pytest.mark.asyncio
    async def test_should_continue_explore_with_running_tasks(self, context_with_plan):
        """Test _should_continue_explore returns True when tasks are running.
        
        This is a unit test for the constraint logic.
        """
        # Add running task
        task = Task(id="task_1", name="Test Task", prompt="Test")
        await context_with_plan.task_registry.add_task(task)
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.RUNNING)

        explore = ExploreBlock(context=context_with_plan)
        
        # Set should_stop_exploration (simulating no tool call scenario)
        explore.should_stop_exploration = True

        # CRITICAL: _should_continue_explore should return True due to active plan
        assert context_with_plan.has_active_plan() is True, "Plan should be active"
        assert explore._should_continue_explore() is True, (
            "ExploreBlock should continue when plan has running tasks, "
            "even if should_stop_exploration is True"
        )

    @pytest.mark.asyncio
    async def test_no_tool_call_does_not_terminate_with_active_plan(self, context_with_plan):
        """Test that no-tool-call scenario doesn't terminate when plan is active.
        
        This tests the _handle_new_tool_call logic specifically.
        """
        # Add running task
        task = Task(id="task_1", name="Test Task", prompt="Test")
        await context_with_plan.task_registry.add_task(task)
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.RUNNING)

        explore = ExploreBlock(context=context_with_plan)
        # Initialize required attributes for _handle_new_tool_call
        explore.model = "gpt-4"
        explore.content = "test"
        explore.system_prompt = None
        explore.output_var = "result"

        # Mock LLM response with no tool calls
        with patch.object(explore, 'llm_chat_stream') as mock_llm:
            from dolphin.core.common.enums import StreamItem
            stream_item = StreamItem()
            stream_item.answer = "No more actions needed."
            stream_item.tool_calls = []
            
            async def mock_stream(*args, **kwargs):
                yield stream_item
            
            mock_llm.side_effect = mock_stream

            # Execute one round of exploration
            result = None
            async for output in explore._handle_new_tool_call(no_cache=True):
                result = output

            # After _handle_new_tool_call processes "no tool call" with active plan,
            # should_stop_exploration flag should be False (modified behavior after fix)
            assert explore.should_stop_exploration is False, (
                "should_stop_exploration should be False when plan is active (fix applied)"
            )

            # And _should_continue_explore should still return True
            # because plan is active
            assert explore._should_continue_explore() is True, (
                "Plan constraint should keep exploration running"
            )

    @pytest.mark.asyncio
    async def test_explore_terminates_after_all_tasks_done(self, context_with_plan):
        """Test that explore DOES terminate once all tasks are completed."""
        # Add completed task
        task = Task(id="task_1", name="Test Task", prompt="Test")
        await context_with_plan.task_registry.add_task(task)
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.COMPLETED)

        explore = ExploreBlock(context=context_with_plan)
        # Initialize required attributes
        explore.model = "gpt-4"
        explore.content = "test"
        explore.system_prompt = None
        explore.output_var = "result"

        # Mock LLM response with no tool calls
        with patch.object(explore, 'llm_chat_stream') as mock_llm:
            from dolphin.core.common.enums import StreamItem
            stream_item = StreamItem()
            stream_item.answer = "All done."
            stream_item.tool_calls = []
            
            async def mock_stream(*args, **kwargs):
                yield stream_item
            
            mock_llm.side_effect = mock_stream

            # Execute one round
            async for _ in explore._handle_new_tool_call(no_cache=True):
                pass

            # Now plan is not active (all tasks done)
            assert context_with_plan.has_active_plan() is False

            # So _should_continue_explore should return False
            assert explore._should_continue_explore() is False, (
                "Explore should terminate when all tasks are done"
            )

    @pytest.mark.asyncio
    async def test_stream_exploration_respects_plan_constraint(self, context_with_plan):
        """Test _stream_exploration_with_assignment respects plan constraint.
        
        This tests the main exploration loop.
        """
        # Add a task that will complete after a delay
        task = Task(id="task_1", name="Delayed Task", prompt="Test")
        await context_with_plan.task_registry.add_task(task)
        await context_with_plan.task_registry.update_status("task_1", TaskStatus.RUNNING)

        # Schedule task completion
        async def complete_task():
            await asyncio.sleep(0.3)
            await context_with_plan.task_registry.update_status("task_1", TaskStatus.COMPLETED)
        
        task_coro = asyncio.create_task(complete_task())
        context_with_plan.task_registry.running_asyncio_tasks = {"task_1": task_coro}

        explore = ExploreBlock(context=context_with_plan)
        explore.output_var = "result"
        explore.assign_type = "->"
        # Initialize required attributes
        explore.model = "gpt-4"
        explore.content = "test"
        explore.system_prompt = None

        # Mock LLM to return no tool calls immediately
        with patch.object(explore, 'llm_chat_stream') as mock_llm:
            from dolphin.core.common.enums import StreamItem
            
            call_count = [0]  # Use list to allow mutation in nested function
            
            async def mock_stream(*args, **kwargs):
                call_count[0] += 1
                stream_item = StreamItem()
                
                # First call: no tool call (should NOT terminate due to plan)
                # Second call: check again (task should be completed by now)
                stream_item.answer = f"Round {call_count[0]}: waiting..."
                stream_item.tool_calls = []
                yield stream_item
            
            mock_llm.side_effect = mock_stream

            # Execute exploration
            start_time = asyncio.get_event_loop().time()
            results = []
            async for output in explore._stream_exploration_with_assignment():
                results.append(output)
                
                # Safety: only break after 1 second timeout (no call count limit)
                # This allows exploration to continue until tasks complete
                if (asyncio.get_event_loop().time() - start_time) > 1.0:
                    break
            
            duration = asyncio.get_event_loop().time() - start_time

            # Wait for task to complete (should already be done)
            try:
                await asyncio.wait_for(task_coro, timeout=0.1)
            except asyncio.TimeoutError:
                pass  # Task still running, that's a test failure

            # ASSERTION: Should have called LLM multiple times
            # (polling until task completes)
            assert call_count[0] >= 3, f"Expected at least 3 LLM calls (polling), got {call_count[0]}"

            # ASSERTION: Should have waited at least 0.3s for task completion
            assert duration >= 0.25, (
                f"Explore terminated too quickly ({duration:.2f}s), "
                f"should wait for task completion (~0.3s)"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
