"""Tests for DolphinAgent.continue_chat method.

Tests the new continue_chat() method that replaces achat() with consistent API format.
"""

import asyncio
import warnings
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_mock_executor(continue_gen=None, progress=None):
    """Build a mock executor with sensible defaults.

    Args:
        continue_gen: async-generator factory for ``continue_exploration``.
        progress: value returned by ``context.get_all_variables_values``.
    """
    if progress is None:
        progress = {"_progress": []}

    mock_executor = MagicMock()
    mock_context = MagicMock()
    mock_context.get_all_variables_values = MagicMock(return_value=progress)
    mock_executor.context = mock_context

    if continue_gen is not None:
        mock_executor.continue_exploration = continue_gen

    return mock_executor


def _completed_gen():
    """Default async generator that yields a single completed event."""
    async def _gen(*args, **kwargs):
        yield {"status": "completed"}
    return _gen


def _capturing_gen(captured: dict):
    """Async generator that captures kwargs passed to continue_exploration."""
    async def _gen(*args, **kwargs):
        captured.update(kwargs)
        yield {"status": "completed"}
    return _gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContinueChatFlagRequirement:
    """Tests for EXPLORE_BLOCK_V2 flag requirement in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_fails_when_v2_enabled(self, enable_explore_v2, dolphin_agent):
        """continue_chat should raise exception when EXPLORE_BLOCK_V2 is enabled."""
        from dolphin.core.common.exceptions import DolphinAgentException

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_continue")

        with pytest.raises(DolphinAgentException) as exc_info:
            async for _ in agent.continue_chat(message="test"):
                pass

        assert "EXPLORE_BLOCK_V2" in str(exc_info.value)
        assert "INVALID_FLAG_STATE" in str(exc_info.value.code)

    @pytest.mark.asyncio
    async def test_continue_chat_works_when_v2_disabled(self, disable_explore_v2, dolphin_agent):
        """continue_chat should work when EXPLORE_BLOCK_V2 is disabled."""
        agent = dolphin_agent(content="/prompt/ test -> result", name="test_continue")

        executor = _make_mock_executor(continue_gen=_completed_gen())
        agent.executor = executor
        agent.output_variables = None

        results = []
        async for result in agent.continue_chat(message="test"):
            results.append(result)

        assert len(results) >= 1, "Should receive at least one result"


class TestContinueChatStreamMode:
    """Tests for stream_mode parameter in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_invalid_stream_mode_raises(self, disable_explore_v2, dolphin_agent):
        """Invalid stream_mode should raise DolphinAgentException."""
        from dolphin.core.common.exceptions import DolphinAgentException

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_stream")

        executor = _make_mock_executor(continue_gen=_completed_gen(), progress={
            "_progress": [{"stage": "llm", "id": "s1", "answer": "Hello World"}]
        })
        agent.executor = executor
        agent.output_variables = None

        with pytest.raises(DolphinAgentException) as exc_info:
            async for _ in agent.continue_chat(message="test", stream_mode="invalid_mode"):
                pass

        assert "stream_mode" in str(exc_info.value)


class TestContinueChatLazyInit:
    """Tests for lazy initialization in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_lazy_initializes(self, disable_explore_v2, dolphin_agent):
        """continue_chat should call initialize if executor is None."""
        agent = dolphin_agent(content="/prompt/ test -> result", name="test_lazy")
        agent.executor = None

        initialize_called = []

        async def mock_initialize():
            initialize_called.append(True)
            executor = _make_mock_executor()

            async def _gen(*a, **k):
                yield {"done": True}

            executor.continue_exploration = _gen
            agent.executor = executor

        agent.initialize = mock_initialize

        async for _ in agent.continue_chat(message="test"):
            pass

        assert len(initialize_called) == 1, "initialize() should be called once"


class TestAchatDeprecation:
    """Tests for achat() deprecation warning."""

    @pytest.mark.asyncio
    async def test_achat_emits_deprecation_warning(self, disable_explore_v2, dolphin_agent):
        """achat() should emit DeprecationWarning."""
        agent = dolphin_agent(content="/prompt/ test -> result", name="test_deprecation")

        executor = _make_mock_executor(continue_gen=_completed_gen())
        agent.executor = executor

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            async for _ in agent.achat(message="test"):
                break

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1, (
                "achat() should emit at least one DeprecationWarning"
            )

            warning_message = str(deprecation_warnings[0].message)
            assert "achat" in warning_message.lower() or "continue_chat" in warning_message.lower()


class TestContinueChatApiConsistency:
    """Tests for API consistency between arun and continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_returns_progress_wrapped_format(self, disable_explore_v2, dolphin_agent):
        """continue_chat should return results in _progress wrapped format like arun."""
        agent = dolphin_agent(content="/prompt/ test -> result", name="test_format")

        executor = _make_mock_executor(continue_gen=_completed_gen(), progress={
            "_progress": [
                {"stage": "llm", "answer": "test response", "status": "completed"}
            ],
            "_status": "completed",
        })
        agent.executor = executor
        agent.output_variables = None

        results = []
        async for result in agent.continue_chat(message="test", stream_variables=True):
            results.append(result)

        for result in results:
            if isinstance(result, dict) and "_progress" in result:
                assert isinstance(result["_progress"], list), (
                    "continue_chat() should return _progress as a list, matching arun() format"
                )


class TestContinueChatInterrupt:
    """Tests for interrupt handling in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_yields_interrupt_info(self, disable_explore_v2, dolphin_agent):
        """continue_chat should yield interrupt info when tool is interrupted."""
        from dolphin.core.agent.agent_state import AgentState

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_interrupt")

        interrupt_data = {"status": "interrupted", "handle": MagicMock()}

        async def mock_continue(*args, **kwargs):
            yield interrupt_data

        executor = _make_mock_executor(continue_gen=mock_continue)
        agent.executor = executor
        agent.output_variables = None
        agent.status.state = AgentState.RUNNING

        results = []
        async for result in agent.continue_chat(message="test", stream_variables=False):
            results.append(result)

        assert len(results) > 0, "Should yield at least one result when tool is interrupted"
        assert results[0].get("_status") == "interrupted"
        assert "status" not in results[0]
        assert "interrupt" not in results[0]


class TestContinueChatPauseSemantics:
    """Tests for state-aware pause semantics in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_defaults_to_preserve_context_true(
        self, disable_explore_v2, dolphin_agent
    ):
        """PAUSED + USER_INTERRUPT should default preserve_context=True."""
        from dolphin.core.agent.agent_state import AgentState, PauseType

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_pause_user_interrupt")

        captured_kwargs = {}
        executor = _make_mock_executor(continue_gen=_capturing_gen(captured_kwargs))
        agent.executor = executor
        agent.output_variables = None

        agent.status.state = AgentState.PAUSED
        agent._pause_type = PauseType.USER_INTERRUPT
        agent._resume_handle = MagicMock()

        async for _ in agent.continue_chat(message="continue"):
            pass

        assert captured_kwargs.get("preserve_context") is True
        assert agent.state == AgentState.RUNNING
        assert agent._pause_type is None
        assert agent._resume_handle is None

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_respects_explicit_preserve_context(
        self, disable_explore_v2, dolphin_agent
    ):
        """Explicit preserve_context should not be overridden in USER_INTERRUPT path."""
        from dolphin.core.agent.agent_state import AgentState, PauseType

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_pause_user_explicit")

        captured_kwargs = {}
        executor = _make_mock_executor(continue_gen=_capturing_gen(captured_kwargs))
        agent.executor = executor
        agent.output_variables = None

        agent.status.state = AgentState.PAUSED
        agent._pause_type = PauseType.USER_INTERRUPT

        async for _ in agent.continue_chat(message="continue", preserve_context=False):
            pass

        assert captured_kwargs.get("preserve_context") is False

    @pytest.mark.asyncio
    async def test_continue_chat_tool_interrupt_requires_resume(self, disable_explore_v2, dolphin_agent):
        """PAUSED + TOOL_INTERRUPT should fail-fast with NEED_RESUME."""
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.core.common.exceptions import DolphinAgentException

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_pause_tool_interrupt")

        continue_called = {"value": False}

        async def mock_continue(*args, **kwargs):
            continue_called["value"] = True
            yield {"status": "completed"}

        executor = _make_mock_executor(continue_gen=mock_continue)
        agent.executor = executor

        agent.status.state = AgentState.PAUSED
        agent._pause_type = PauseType.TOOL_INTERRUPT

        with pytest.raises(DolphinAgentException) as exc_info:
            async for _ in agent.continue_chat(message="continue"):
                pass

        assert exc_info.value.code == "NEED_RESUME"
        assert "resume" in str(exc_info.value).lower()
        assert continue_called["value"] is False

    @pytest.mark.asyncio
    async def test_continue_chat_non_paused_does_not_inject_preserve_context(
        self, disable_explore_v2, dolphin_agent
    ):
        """Non-paused states should keep preserve_context unset by default."""
        from dolphin.core.agent.agent_state import AgentState

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_non_paused_default")

        captured_kwargs = {}
        executor = _make_mock_executor(continue_gen=_capturing_gen(captured_kwargs))
        agent.executor = executor
        agent.output_variables = None
        agent.status.state = AgentState.RUNNING

        async for _ in agent.continue_chat(message="continue"):
            pass

        assert "preserve_context" not in captured_kwargs

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_yields_interrupted_event_and_pauses(
        self, disable_explore_v2, dolphin_agent
    ):
        """UserInterrupt in continue_chat should yield interrupted event and pause agent."""
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.core.common.exceptions import UserInterrupt

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_user_interrupt_state_sync")

        async def mock_continue(*args, **kwargs):
            raise UserInterrupt("manual interrupt in continue_chat")
            yield

        executor = _make_mock_executor(continue_gen=mock_continue)
        agent.executor = executor
        agent.output_variables = None
        agent.status.state = AgentState.RUNNING

        with patch.object(agent, "clear_interrupt", wraps=agent.clear_interrupt) as mock_clear_interrupt:
            results = []
            async for item in agent.continue_chat(message="continue"):
                results.append(item)

        assert agent.state == AgentState.PAUSED
        assert agent._pause_type == PauseType.USER_INTERRUPT
        assert len(results) == 1
        assert results[0].get("_status") == "interrupted"
        assert results[0].get("_interrupt", {}).get("interrupt_type") == "user_interrupt"
        assert "type" not in results[0].get("_interrupt", {})
        assert mock_clear_interrupt.called

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_result_clears_interrupt_event(
        self, disable_explore_v2, dolphin_agent
    ):
        """User interrupt result payload should clear interrupt event and pause agent."""
        from dolphin.core.agent.agent_state import AgentState, PauseType

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_user_interrupt_payload_path")

        async def mock_continue(*args, **kwargs):
            yield {"status": "interrupted", "interrupt_type": "user_interrupt"}

        executor = _make_mock_executor(continue_gen=mock_continue)
        agent.executor = executor
        agent.output_variables = None
        agent.status.state = AgentState.RUNNING
        agent.get_interrupt_event().set()

        with patch.object(agent, "clear_interrupt", wraps=agent.clear_interrupt) as mock_clear_interrupt:
            results = []
            async for item in agent.continue_chat(message="continue"):
                results.append(item)

        assert len(results) == 1
        assert results[0].get("_status") == "interrupted"
        assert results[0].get("_interrupt", {}).get("interrupt_type") == "user_interrupt"
        assert agent.state == AgentState.PAUSED
        assert agent._pause_type == PauseType.USER_INTERRUPT
        assert mock_clear_interrupt.called
        assert agent.get_interrupt_event().is_set() is False

    @pytest.mark.asyncio
    async def test_continue_chat_clears_pending_user_input_after_resume(
        self, disable_explore_v2, dolphin_agent
    ):
        """continue_chat should consume pending user input when resuming from USER_INTERRUPT."""
        from dolphin.core.agent.agent_state import AgentState, PauseType

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_pending_user_input_cleanup")

        captured_kwargs = {}
        executor = _make_mock_executor(continue_gen=_capturing_gen(captured_kwargs))
        agent.executor = executor
        agent.output_variables = None

        agent.status.state = AgentState.PAUSED
        agent._pause_type = PauseType.USER_INTERRUPT
        agent._resume_handle = MagicMock()

        await agent.resume_with_input("resume-with-input message")
        assert agent._pending_user_input == "resume-with-input message"

        async for _ in agent.continue_chat(message="continue"):
            pass

        assert agent._pending_user_input is None
        assert captured_kwargs.get("preserve_context") is True

    @pytest.mark.asyncio
    async def test_continue_chat_from_completed_state_user_interrupt_causes_lifecycle_exception(
        self, disable_explore_v2, dolphin_agent
    ):
        """BUG REPRO (P1): continue_chat from COMPLETED state + user_interrupt.

        After arun() completes normally the agent is in COMPLETED state.
        Calling continue_chat() skips the PAUSED branch and never transitions
        to RUNNING.  If a UserInterrupt is raised during execution,
        mark_user_interrupted() attempts COMPLETED->PAUSED which is illegal,
        raising AgentLifecycleException instead of yielding _status="interrupted".
        """
        from dolphin.core.agent.agent_state import AgentState
        from dolphin.core.common.exceptions import UserInterrupt

        agent = dolphin_agent(content="/prompt/ test -> result", name="test_completed_then_interrupt")

        async def mock_continue(*args, **kwargs):
            raise UserInterrupt("user pressed ctrl-c")
            yield

        executor = _make_mock_executor(continue_gen=mock_continue)
        agent.executor = executor
        agent.output_variables = None

        agent.status.state = AgentState.COMPLETED

        results = []
        async for item in agent.continue_chat(message="new question"):
            results.append(item)

        assert len(results) == 1
        assert results[0].get("_status") == "interrupted"


class TestDeltaModeIntegrationWithContinueChat:
    """Integration tests for delta mode with continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_delta_mode_yields_results(self, disable_explore_v2, dolphin_agent):
        """continue_chat with stream_mode='delta' should yield dict results.

        TODO: add assertions verifying that delta fields are present in results.
        """
        agent = dolphin_agent(content="/prompt/ test -> result", name="test_delta_integration")

        call_count = [0]

        def get_vars():
            call_count[0] += 1
            if call_count[0] == 1:
                return {"_progress": [{"stage": "llm", "id": "s1", "answer": "Hello"}]}
            else:
                return {"_progress": [{"stage": "llm", "id": "s1", "answer": "Hello World"}]}

        mock_executor = MagicMock()
        mock_context = MagicMock()
        mock_context.get_all_variables_values = get_vars
        mock_executor.context = mock_context

        async def mock_continue(*args, **kwargs):
            yield {"status": "running"}
            yield {"status": "completed"}

        mock_executor.continue_exploration = mock_continue
        agent.executor = mock_executor
        agent.output_variables = None

        results = []
        async for result in agent.continue_chat(
            message="test", stream_mode="delta", stream_variables=True
        ):
            results.append(result)

        assert len(results) > 0, "continue_chat with delta mode should yield at least one result"
        assert all(isinstance(r, dict) for r in results), "All results should be dicts"
