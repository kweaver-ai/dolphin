"""
Unit tests for User Interrupt mechanism.

Tests cover:
1. UserInterrupt exception
2. Context interrupt methods
3. WaitReason enum and ExecutionFrame extensions
4. StepResult extensions for user interrupt
5. ResumeHandle extensions for user interrupt
6. BaseAgent interrupt() and resume_with_input() methods
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
from typing import Optional, Any

from dolphin.core.common.exceptions import UserInterrupt, DolphinException
from dolphin.core.context.context import Context
from dolphin.core.coroutine.execution_frame import (
    ExecutionFrame,
    FrameStatus,
    WaitReason,
)
from dolphin.core.coroutine.step_result import StepResult
from dolphin.core.coroutine.resume_handle import ResumeHandle
from dolphin.core.agent.agent_state import AgentState
from dolphin.core.agent.base_agent import BaseAgent
from dolphin.sdk.agent import PauseType
from dolphin.core.common.exceptions import AgentLifecycleException


class TestUserInterruptException:
    """Tests for UserInterrupt exception class."""

    def test_user_interrupt_is_dolphin_exception(self):
        """UserInterrupt should inherit from DolphinException."""
        exc = UserInterrupt()
        assert isinstance(exc, DolphinException)

    def test_user_interrupt_default_message(self):
        """UserInterrupt should have a default message."""
        exc = UserInterrupt()
        assert exc.message == "User interrupted execution"
        assert exc.code == "USER_INTERRUPT"

    def test_user_interrupt_custom_message(self):
        """UserInterrupt should accept custom message."""
        exc = UserInterrupt(message="Custom interrupt reason")
        assert exc.message == "Custom interrupt reason"

    def test_user_interrupt_partial_output(self):
        """UserInterrupt should capture partial output."""
        exc = UserInterrupt(partial_output="Partial LLM response...")
        assert exc.partial_output == "Partial LLM response..."

    def test_user_interrupt_timestamp(self):
        """UserInterrupt should record interrupt timestamp."""
        before = datetime.now()
        exc = UserInterrupt()
        after = datetime.now()
        assert before <= exc.interrupted_at <= after

    def test_user_interrupt_str(self):
        """UserInterrupt __str__ should be readable."""
        exc = UserInterrupt(message="Test message")
        assert str(exc) == "UserInterrupt: Test message"


class TestContextInterruptMethods:
    """Tests for Context interrupt-related methods."""

    def test_set_and_get_interrupt_event(self):
        """Context should store and return interrupt event."""
        context = Context()
        event = asyncio.Event()

        context.set_interrupt_event(event)
        assert context.get_interrupt_event() is event

    def test_get_interrupt_event_default_none(self):
        """Context should return None if no event set."""
        context = Context()
        assert context.get_interrupt_event() is None

    def test_is_interrupted_false_when_no_event(self):
        """is_interrupted should be False when no event set."""
        context = Context()
        assert context.is_interrupted() is False

    def test_is_interrupted_false_when_event_not_set(self):
        """is_interrupted should be False when event exists but not set."""
        context = Context()
        event = asyncio.Event()
        context.set_interrupt_event(event)
        assert context.is_interrupted() is False

    def test_is_interrupted_true_when_event_set(self):
        """is_interrupted should be True when event is set."""
        context = Context()
        event = asyncio.Event()
        context.set_interrupt_event(event)
        event.set()
        assert context.is_interrupted() is True

    def test_check_user_interrupt_no_exception_when_not_interrupted(self):
        """check_user_interrupt should not raise when not interrupted."""
        context = Context()
        event = asyncio.Event()
        context.set_interrupt_event(event)
        # Should not raise
        context.check_user_interrupt()

    def test_check_user_interrupt_raises_when_interrupted(self):
        """check_user_interrupt should raise UserInterrupt when interrupted."""
        context = Context()
        event = asyncio.Event()
        context.set_interrupt_event(event)
        event.set()

        with pytest.raises(UserInterrupt):
            context.check_user_interrupt()

    def test_clear_interrupt(self):
        """clear_interrupt should reset the interrupt event."""
        context = Context()
        event = asyncio.Event()
        context.set_interrupt_event(event)
        event.set()
        assert context.is_interrupted() is True

        context.clear_interrupt()
        assert context.is_interrupted() is False


class TestWaitReason:
    """Tests for WaitReason enum."""

    def test_wait_reason_values(self):
        """WaitReason should have expected values."""
        assert WaitReason.TOOL_REQUEST.value == "tool_request"
        assert WaitReason.USER_INTERRUPT.value == "user_interrupt"

    def test_wait_reason_from_string(self):
        """WaitReason should be constructible from string."""
        assert WaitReason("tool_request") == WaitReason.TOOL_REQUEST
        assert WaitReason("user_interrupt") == WaitReason.USER_INTERRUPT


class TestExecutionFrameWaitReason:
    """Tests for ExecutionFrame wait_reason field."""

    def test_frame_default_wait_reason_none(self):
        """ExecutionFrame should have None wait_reason by default."""
        frame = ExecutionFrame(frame_id="test-frame")
        assert frame.wait_reason is None

    def test_frame_with_wait_reason(self):
        """ExecutionFrame should accept wait_reason."""
        frame = ExecutionFrame(
            frame_id="test-frame",
            status=FrameStatus.WAITING_FOR_INTERVENTION,
            wait_reason=WaitReason.USER_INTERRUPT,
        )
        assert frame.wait_reason == WaitReason.USER_INTERRUPT

    def test_is_waiting_for_user_input_true(self):
        """is_waiting_for_user_input should return True for user interrupt."""
        frame = ExecutionFrame(
            frame_id="test-frame",
            status=FrameStatus.WAITING_FOR_INTERVENTION,
            wait_reason=WaitReason.USER_INTERRUPT,
        )
        assert frame.is_waiting_for_user_input() is True

    def test_is_waiting_for_user_input_false_for_tool(self):
        """is_waiting_for_user_input should return False for tool request."""
        frame = ExecutionFrame(
            frame_id="test-frame",
            status=FrameStatus.WAITING_FOR_INTERVENTION,
            wait_reason=WaitReason.TOOL_REQUEST,
        )
        assert frame.is_waiting_for_user_input() is False

    def test_is_waiting_for_user_input_false_when_not_waiting(self):
        """is_waiting_for_user_input should return False when not waiting."""
        frame = ExecutionFrame(
            frame_id="test-frame",
            status=FrameStatus.RUNNING,
            wait_reason=WaitReason.USER_INTERRUPT,
        )
        assert frame.is_waiting_for_user_input() is False

    def test_frame_to_dict_includes_wait_reason(self):
        """to_dict should include wait_reason."""
        frame = ExecutionFrame(
            frame_id="test-frame",
            wait_reason=WaitReason.USER_INTERRUPT,
        )
        data = frame.to_dict()
        assert data["wait_reason"] == "user_interrupt"

    def test_frame_to_dict_wait_reason_none(self):
        """to_dict should handle None wait_reason."""
        frame = ExecutionFrame(frame_id="test-frame")
        data = frame.to_dict()
        assert data["wait_reason"] is None

    def test_frame_from_dict_with_wait_reason(self):
        """from_dict should restore wait_reason."""
        data = {
            "frame_id": "test-frame",
            "parent_id": None,
            "agent_id": None,
            "block_pointer": 0,
            "block_stack": [],
            "status": "waiting_for_intervention",
            "context_snapshot_id": "",
            "children": [],
            "created_at": None,
            "updated_at": None,
            "original_content": "",
            "error": None,
            "wait_reason": "user_interrupt",
        }
        frame = ExecutionFrame.from_dict(data)
        assert frame.wait_reason == WaitReason.USER_INTERRUPT

    def test_frame_from_dict_backward_compatible(self):
        """from_dict should handle missing wait_reason (backward compatibility)."""
        data = {
            "frame_id": "test-frame",
            "parent_id": None,
            "agent_id": None,
            "block_pointer": 0,
            "block_stack": [],
            "status": "running",
            "context_snapshot_id": "",
            "children": [],
            "created_at": None,
            "updated_at": None,
            "original_content": "",
            "error": None,
        }
        frame = ExecutionFrame.from_dict(data)
        assert frame.wait_reason is None


class TestStepResultUserInterrupt:
    """Tests for StepResult user interrupt support."""

    def test_is_user_interrupted_property(self):
        """is_user_interrupted should return True for user_interrupted status."""
        result = StepResult(status="user_interrupted")
        assert result.is_user_interrupted is True
        assert result.is_tool_interrupted is False

    def test_is_tool_interrupted_property(self):
        """is_tool_interrupted should return True for interrupted status."""
        result = StepResult(status="interrupted")
        assert result.is_tool_interrupted is True
        assert result.is_user_interrupted is False

    def test_is_interrupted_covers_both(self):
        """is_interrupted should return True for both interrupt types."""
        tool_result = StepResult(status="interrupted")
        user_result = StepResult(status="user_interrupted")
        running_result = StepResult(status="running")

        assert tool_result.is_interrupted is True
        assert user_result.is_interrupted is True
        assert running_result.is_interrupted is False

    def test_user_interrupted_factory(self):
        """StepResult.user_interrupted() should create correct result."""
        handle = ResumeHandle.create_handle("frame-1", "snapshot-1")
        result = StepResult.user_interrupted(
            resume_handle=handle,
            result={"partial_output": "test"},
        )

        assert result.status == "user_interrupted"
        assert result.is_user_interrupted is True
        assert result.resume_handle is handle
        assert result.result == {"partial_output": "test"}

    def test_bool_false_for_user_interrupted(self):
        """bool(StepResult) should be False for user_interrupted."""
        result = StepResult(status="user_interrupted")
        assert bool(result) is False


class TestResumeHandleUserInterrupt:
    """Tests for ResumeHandle user interrupt support."""

    def test_default_interrupt_type(self):
        """Default interrupt_type should be tool_interrupt."""
        handle = ResumeHandle.create_handle("frame-1", "snapshot-1")
        assert handle.interrupt_type == "tool_interrupt"
        assert handle.restart_block is False

    def test_create_user_interrupt_handle(self):
        """create_user_interrupt_handle should set correct fields."""
        handle = ResumeHandle.create_user_interrupt_handle(
            frame_id="frame-1",
            snapshot_id="snapshot-1",
            current_block=5,
        )

        assert handle.interrupt_type == "user_interrupt"
        assert handle.current_block == 5
        assert handle.restart_block is True
        assert handle.is_valid()

    def test_is_user_interrupt_method(self):
        """is_user_interrupt() should return True for user interrupt handles."""
        user_handle = ResumeHandle.create_user_interrupt_handle("f", "s")
        tool_handle = ResumeHandle.create_handle("f", "s")

        assert user_handle.is_user_interrupt() is True
        assert user_handle.is_tool_interrupt() is False
        assert tool_handle.is_user_interrupt() is False
        assert tool_handle.is_tool_interrupt() is True

    def test_to_dict_includes_new_fields(self):
        """to_dict should include interrupt_type and related fields."""
        handle = ResumeHandle.create_user_interrupt_handle(
            frame_id="frame-1",
            snapshot_id="snapshot-1",
            current_block=3,
        )
        data = handle.to_dict()

        assert data["interrupt_type"] == "user_interrupt"
        assert data["current_block"] == 3
        assert data["restart_block"] is True

    def test_from_dict_with_new_fields(self):
        """from_dict should restore new fields."""
        data = {
            "frame_id": "frame-1",
            "snapshot_id": "snapshot-1",
            "resume_token": "token-123",
            "interrupt_type": "user_interrupt",
            "current_block": 5,
            "restart_block": True,
        }
        handle = ResumeHandle.from_dict(data)

        assert handle.interrupt_type == "user_interrupt"
        assert handle.current_block == 5
        assert handle.restart_block is True

    def test_from_dict_backward_compatible(self):
        """from_dict should handle old data without new fields."""
        data = {
            "frame_id": "frame-1",
            "snapshot_id": "snapshot-1",
            "resume_token": "token-123",
        }
        handle = ResumeHandle.from_dict(data)

        # Should default to tool_interrupt behavior
        assert handle.interrupt_type == "tool_interrupt"
        assert handle.current_block is None
        assert handle.restart_block is False


class MockInterruptAgent(BaseAgent):
    """Mock agent for testing interrupt functionality."""

    def __init__(self, name: str = "test_agent"):
        super().__init__(name)
        self.step_count = 0
        self.max_steps = 100  # More steps to allow time for interrupt
        self.step_delay = 0.02  # Add delay between steps

    async def _on_initialize(self):
        pass

    async def _on_execute(self, **kwargs):
        pass

    async def _on_pause(self):
        pass

    async def _on_resume(self):
        pass

    async def _on_terminate(self):
        pass

    async def _on_start_coroutine(self, **kwargs):
        self.step_count = 0
        return "mock_frame"

    async def _on_step_coroutine(self):
        await asyncio.sleep(self.step_delay)  # Add delay
        self.step_count += 1
        if self.step_count >= self.max_steps:
            return StepResult.completed(result={"steps": self.step_count})
        return StepResult.running(result={"step": self.step_count})

    async def _on_pause_coroutine(self):
        pass

    async def _on_resume_coroutine(self, updates: Optional[dict[str, Any]] = None):
        pass

    async def _on_terminate_coroutine(self):
        pass


class TestBaseAgentInterrupt:
    """Tests for BaseAgent interrupt() and resume_with_input() methods."""

    @pytest.mark.asyncio
    async def test_interrupt_from_running_state(self):
        """interrupt() should succeed from RUNNING state."""
        agent = MockInterruptAgent()
        await agent.initialize()

        # Start running in background
        async def run_agent():
            async for _ in agent.arun():
                pass

        task = asyncio.create_task(run_agent())
        await asyncio.sleep(0.05)  # Let it start

        # Should be running
        assert agent.state == AgentState.RUNNING

        # Interrupt should succeed
        result = await agent.interrupt()
        assert result is True
        assert agent._interrupt_event.is_set()

        # Cleanup
        await agent.terminate()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_interrupt_from_non_running_state_succeeds(self):
        """interrupt() should succeed from non-RUNNING state (sets event for later)."""
        agent = MockInterruptAgent()
        await agent.initialize()

        # Should be INITIALIZED, not RUNNING
        assert agent.state == AgentState.INITIALIZED

        # interrupt() now works from any state to support interrupt signals
        # arriving during state transitions
        result = await agent.interrupt()
        assert result is True
        assert agent._interrupt_event.is_set()

    @pytest.mark.asyncio
    async def test_get_interrupt_event(self):
        """get_interrupt_event() should return the event."""
        agent = MockInterruptAgent()
        event = agent.get_interrupt_event()

        assert event is not None
        assert isinstance(event, asyncio.Event)
        assert event is agent._interrupt_event

    @pytest.mark.asyncio
    async def test_resume_with_input_requires_paused_state(self):
        """resume_with_input() should require PAUSED state."""
        agent = MockInterruptAgent()
        await agent.initialize()

        with pytest.raises(AgentLifecycleException) as exc_info:
            await agent.resume_with_input("new input")
        assert "INVALID_STATE" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resume_with_input_requires_user_interrupt_pause_type(self):
        """resume_with_input() should require pause_type='user_interrupt'."""
        agent = MockInterruptAgent()
        await agent.initialize()

        # Go through proper state transitions: initialized -> running -> paused
        await agent._change_state(AgentState.RUNNING, "starting")
        await agent._change_state(AgentState.PAUSED, "test pause")
        agent._pause_type = PauseType.TOOL_INTERRUPT

        with pytest.raises(AgentLifecycleException) as exc_info:
            await agent.resume_with_input("new input")
        assert "INVALID_PAUSE_TYPE" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resume_with_input_success(self):
        """resume_with_input() should succeed with correct state."""
        agent = MockInterruptAgent()
        await agent.initialize()

        # Go through proper state transitions: initialized -> running -> paused
        await agent._change_state(AgentState.RUNNING, "starting")
        await agent._change_state(AgentState.PAUSED, "user interrupt pause")
        agent._pause_type = PauseType.USER_INTERRUPT
        agent._interrupt_event.set()

        result = await agent.resume_with_input("new instruction")

        assert result is True
        assert agent._pending_user_input == "new instruction"
        assert agent._interrupt_event.is_set() is False  # Should be cleared
        # Note: resume_with_input() does NOT change state to RUNNING.
        # The state transition to RUNNING happens when arun() is called.
        assert agent.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_resume_with_input_none(self):
        """resume_with_input(None) should work without new input."""
        agent = MockInterruptAgent()
        await agent.initialize()

        # Go through proper state transitions: initialized -> running -> paused
        await agent._change_state(AgentState.RUNNING, "starting")
        await agent._change_state(AgentState.PAUSED, "user interrupt pause")
        agent._pause_type = PauseType.USER_INTERRUPT

        result = await agent.resume_with_input(None)

        assert result is True
        assert agent._pending_user_input is None

    @pytest.mark.asyncio
    async def test_mark_user_interrupted_from_running(self):
        """mark_user_interrupted() should transition RUNNING -> PAUSED."""
        agent = MockInterruptAgent()
        await agent.initialize()
        await agent._change_state(AgentState.RUNNING, "starting")

        await agent.mark_user_interrupted("manual interrupt")

        assert agent.state == AgentState.PAUSED
        assert agent._pause_type == PauseType.USER_INTERRUPT

    @pytest.mark.asyncio
    async def test_mark_user_interrupted_from_paused_overrides_pause_type(self):
        """mark_user_interrupted() should override pause type when already PAUSED."""
        agent = MockInterruptAgent()
        await agent.initialize()
        await agent._change_state(AgentState.RUNNING, "starting")
        await agent._change_state(AgentState.PAUSED, "tool pause")
        agent._pause_type = PauseType.TOOL_INTERRUPT

        await agent.mark_user_interrupted("user interrupted while paused")

        assert agent.state == AgentState.PAUSED
        assert agent._pause_type == PauseType.USER_INTERRUPT

    @pytest.mark.asyncio
    async def test_mark_user_interrupted_invalid_state_does_not_pollute_pause_type(self):
        """mark_user_interrupted() should not mutate pause type on invalid state."""
        agent = MockInterruptAgent()
        await agent.initialize()
        agent._pause_type = PauseType.MANUAL

        with pytest.raises(AgentLifecycleException) as exc_info:
            await agent.mark_user_interrupted("invalid transition")

        assert exc_info.value.code == "INVALID_STATE"
        assert agent.state == AgentState.INITIALIZED
        assert agent._pause_type == PauseType.MANUAL

    @pytest.mark.asyncio
    async def test_mark_user_interrupted_rolls_back_pause_type_on_transition_failure(self):
        """mark_user_interrupted() should roll back pause type when transition fails."""
        agent = MockInterruptAgent()
        await agent.initialize()
        await agent._change_state(AgentState.RUNNING, "starting")

        async def _mock_change_state(*args, **kwargs):
            raise RuntimeError("mock transition failure")

        with patch.object(agent, "_change_state", side_effect=_mock_change_state):
            with pytest.raises(RuntimeError):
                await agent.mark_user_interrupted("failing transition")

        assert agent.state == AgentState.RUNNING
        assert agent._pause_type is None
