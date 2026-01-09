import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_coroutine_tool_interrupt_pause_and_resume():
    from dolphin.sdk.agent.dolphin_agent import DolphinAgent
    from dolphin.core.agent.agent_state import AgentState
    from dolphin.core.coroutine.execution_frame import FrameStatus
    from dolphin.core.coroutine.resume_handle import ResumeHandle

    # Mock DolphinExecutor to simulate coroutine stepping behavior
    with (
        patch(
            "dolphin.core.executor.dolphin_executor.DolphinExecutor"
        ) as mock_executor_cls,
        patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ),
    ):
        mock_executor = MagicMock()
        mock_executor_cls.return_value = mock_executor

        # Mock context
        mock_context = MagicMock()
        mock_context.get_all_variables.return_value = {"a": 1}
        mock_context.set_cur_agent = MagicMock()
        mock_executor.context = mock_context

        # Mock state registry and frame
        class DummyFrame:
            def __init__(self):
                self.frame_id = "f1"
                self.status = FrameStatus.RUNNING
                self.block_pointer = 0

        dummy_frame = DummyFrame()

        mock_state_registry = MagicMock()
        mock_state_registry.get_frame.return_value = dummy_frame
        mock_executor.state_registry = mock_state_registry

        # executor_init no-op
        mock_executor.executor_init = AsyncMock()

        # start_coroutine returns a running frame
        mock_executor.start_coroutine = AsyncMock(return_value=dummy_frame)

        # First step: simulate ToolInterrupt by returning StepResult with ResumeHandle
        from dolphin.core.coroutine.step_result import StepResult

        resume_handle = ResumeHandle.create_handle("f1", "s1")
        interrupted_result = StepResult.interrupted(resume_handle=resume_handle)

        mock_executor.step_coroutine = AsyncMock(return_value=interrupted_result)

        # run_coroutine should also be AsyncMock for fast mode
        mock_executor.run_coroutine = AsyncMock(return_value=interrupted_result)

        # is_waiting_for_intervention returns True after interruption
        mock_executor.is_waiting_for_intervention = MagicMock(return_value=True)

        # resume_coroutine returns frame back to running
        mock_executor.resume_coroutine = AsyncMock(return_value=dummy_frame)

        agent = DolphinAgent(
            name="test_coroutine_agent",
            content="/explore/\nhello\n>>",
        )

        await agent.initialize()

        # Run first time: expect one yield then agent enters PAUSED state due to intervention
        results1 = []
        async for res in agent.arun():
            results1.append(res)
        assert len(results1) == 1
        assert agent.state == AgentState.PAUSED
        assert agent.get_resume_handle() is not None

        # Resume
        await agent.resume()
        mock_executor.resume_coroutine.assert_awaited()

        # After resume, further step completes
        completed_result = StepResult.completed(result={"status": "completed"})
        mock_executor.step_coroutine = AsyncMock(return_value=completed_result)
        mock_executor.run_coroutine = AsyncMock(return_value=completed_result)
        mock_executor.is_waiting_for_intervention = MagicMock(return_value=False)

        results2 = []
        async for res in agent.arun():
            results2.append(res)

        # Should have yielded variables once and then completed
        assert len(results2) == 1
        assert agent.state == AgentState.COMPLETED


@pytest.mark.asyncio
async def test_coroutine_mode_execution_info_has_mode():
    from dolphin.sdk.agent.dolphin_agent import DolphinAgent

    with (
        patch(
            "dolphin.core.executor.dolphin_executor.DolphinExecutor"
        ) as mock_executor_cls,
        patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ),
    ):
        mock_executor = MagicMock()
        mock_executor_cls.return_value = mock_executor

        # Minimal context
        mock_context = MagicMock()
        mock_context.get_all_variables.return_value = {"x": 1}
        mock_context.set_cur_agent = MagicMock()
        mock_executor.context = mock_context

        # executor_init no-op
        mock_executor.executor_init = AsyncMock()

        agent = DolphinAgent(
            name="test_coroutine_info",
            content="/explore/\nhello\n>>",
        )

        await agent.initialize()
        # Call start_coroutine so that execution_info is meaningful
        await agent.start_coroutine()
        info = agent.get_execution_info()
        assert info["execution_mode"] == "coroutine"
