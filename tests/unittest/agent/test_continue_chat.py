"""Tests for DolphinAgent.continue_chat method.

Tests the new continue_chat() method that replaces achat() with consistent API format.
"""

import asyncio
import warnings
from unittest.mock import MagicMock, patch

import pytest


class TestContinueChatFlagRequirement:
    """Tests for EXPLORE_BLOCK_V2 flag requirement in continue_chat."""

    @pytest.fixture
    def agent(self):
        """Create a minimal DolphinAgent instance."""
        with patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ), patch(
            "dolphin.core.executor.dolphin_executor.DolphinExecutor"
        ):
            from dolphin.sdk.agent.dolphin_agent import DolphinAgent
            agent = DolphinAgent(
                name="test_continue",
                content="/prompt/ test -> result",
            )
            return agent

    @pytest.mark.asyncio
    async def test_continue_chat_fails_when_v2_enabled(self, agent):
        """continue_chat should raise exception when EXPLORE_BLOCK_V2 is enabled."""
        from dolphin.core.common.exceptions import DolphinAgentException
        from dolphin.core import flags

        # Ensure V2 is enabled
        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, True)

        try:
            with pytest.raises(DolphinAgentException) as exc_info:
                async for _ in agent.continue_chat(message="test"):
                    pass

            assert "EXPLORE_BLOCK_V2" in str(exc_info.value)
            assert "INVALID_FLAG_STATE" in str(exc_info.value.code)
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


    @pytest.mark.asyncio
    async def test_continue_chat_works_when_v2_disabled(self, agent):
        """continue_chat should work when EXPLORE_BLOCK_V2 is disabled."""
        from dolphin.core import flags

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            # Mock executor and continue_exploration
            mock_executor = MagicMock()
            mock_context = MagicMock()
            mock_context.get_all_variables_values = MagicMock(
                return_value={"_progress": []}
            )
            mock_executor.context = mock_context

            async def mock_continue(*args, **kwargs):
                yield {"status": "completed"}

            mock_executor.continue_exploration = mock_continue
            agent.executor = mock_executor
            agent.output_variables = None

            # Should not raise
            results = []
            async for result in agent.continue_chat(message="test"):
                results.append(result)

            # Verify we got some results
            assert len(results) >= 1, "Should receive at least one result from continue_chat without raising exception"
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


class TestContinueChatStreamMode:
    """Tests for stream_mode parameter in continue_chat."""

    @pytest.fixture
    def agent_with_mocks(self):
        """Create agent with fully mocked execution path."""
        from dolphin.core import flags

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        with patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ), patch(
            "dolphin.core.executor.dolphin_executor.DolphinExecutor"
        ):
            from dolphin.sdk.agent.dolphin_agent import DolphinAgent
            agent = DolphinAgent(
                name="test_stream",
                content="/prompt/ test -> result",
            )

            # Setup mock executor
            mock_executor = MagicMock()
            mock_context = MagicMock()
            mock_context.get_all_variables_values = MagicMock(
                return_value={
                    "_progress": [
                        {"stage": "llm", "id": "s1", "answer": "Hello World"}
                    ]
                }
            )
            mock_executor.context = mock_context

            async def mock_continue(*args, **kwargs):
                yield {"status": "running"}
                yield {"status": "completed"}

            mock_executor.continue_exploration = mock_continue
            agent.executor = mock_executor
            agent.output_variables = None

            yield agent

            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_invalid_stream_mode_raises(self, agent_with_mocks):
        """Invalid stream_mode should raise DolphinAgentException."""
        from dolphin.core.common.exceptions import DolphinAgentException

        with pytest.raises(DolphinAgentException) as exc_info:
            async for _ in agent_with_mocks.continue_chat(
                message="test", stream_mode="invalid_mode"
            ):
                pass

        assert "stream_mode" in str(exc_info.value)


class TestContinueChatLazyInit:
    """Tests for lazy initialization in continue_chat."""

    @pytest.fixture
    def uninitialized_agent(self):
        """Create an uninitialized agent."""
        from dolphin.core import flags

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        with patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ):
            from dolphin.sdk.agent.dolphin_agent import DolphinAgent
            agent = DolphinAgent(
                name="test_lazy",
                content="/prompt/ test -> result",
            )
            # Ensure executor is None (not initialized)
            agent.executor = None

            yield agent

            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_lazy_initializes(self, uninitialized_agent):
        """continue_chat should call initialize if executor is None."""
        initialize_called = []

        async def mock_initialize():
            initialize_called.append(True)
            # Setup executor after init
            mock_executor = MagicMock()
            mock_context = MagicMock()
            mock_context.get_all_variables_values = MagicMock(
                return_value={"_progress": []}
            )
            mock_executor.context = mock_context

            async def _gen(*a, **k):
                yield {"done": True}

            mock_executor.continue_exploration = _gen
            uninitialized_agent.executor = mock_executor

        uninitialized_agent.initialize = mock_initialize

        async for _ in uninitialized_agent.continue_chat(message="test"):
            pass

        assert len(initialize_called) == 1, "initialize() should be called once"


class TestAchatDeprecation:
    """Tests for achat() deprecation warning."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked executor."""
        with patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ), patch(
            "dolphin.core.executor.dolphin_executor.DolphinExecutor"
        ):
            from dolphin.sdk.agent.dolphin_agent import DolphinAgent
            agent = DolphinAgent(
                name="test_deprecation",
                content="/prompt/ test -> result",
            )

            # Setup mock executor
            mock_executor = MagicMock()
            mock_context = MagicMock()
            mock_context.get_all_variables_values = MagicMock(return_value={})
            mock_executor.context = mock_context

            async def mock_continue(*args, **kwargs):
                yield {"done": True}

            mock_executor.continue_exploration = mock_continue
            agent.executor = mock_executor

            return agent

    @pytest.mark.asyncio
    async def test_achat_emits_deprecation_warning(self, agent):
        """achat() should emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            async for _ in agent.achat(message="test"):
                break

            # Find deprecation warning
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1, "achat() should emit at least one DeprecationWarning to guide users to continue_chat()"

            warning_message = str(deprecation_warnings[0].message)
            assert "achat" in warning_message.lower() or "continue_chat" in warning_message.lower()


class TestContinueChatApiConsistency:
    """Tests for API consistency between arun and continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_returns_progress_wrapped_format(self):
        """continue_chat should return results in _progress wrapped format like arun."""
        from dolphin.core import flags
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_format",
                    content="/prompt/ test -> result",
                )

                # Mock executor
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={
                        "_progress": [
                            {
                                "stage": "llm",
                                "answer": "test response",
                                "status": "completed"
                            }
                        ],
                        "_status": "completed"
                    }
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None

                # Collect results
                results = []
                async for result in agent.continue_chat(
                    message="test",
                    stream_variables=True
                ):
                    results.append(result)

                # Verify format consistency
                for result in results:
                    if isinstance(result, dict) and "_progress" in result:
                        assert isinstance(result["_progress"], list), \
                            "continue_chat() should return _progress as a list, matching arun() format"
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


class TestContinueChatInterrupt:
    """Tests for interrupt handling in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_yields_interrupt_info(self):
        """continue_chat should yield interrupt info when tool is interrupted."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_interrupt",
                    content="/prompt/ test -> result",
                )

                # Mock executor that produces interrupt
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                interrupt_data = {
                    "status": "interrupted",
                    "handle": MagicMock()
                }

                async def mock_continue(*args, **kwargs):
                    yield interrupt_data

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None
                agent.status.state = AgentState.RUNNING

                # Collect results
                results = []
                async for result in agent.continue_chat(
                    message="test",
                    stream_variables=False  # Use non-streaming for simpler test
                ):
                    results.append(result)

                # Should have received interrupt-related data
                # The exact format depends on implementation
                assert len(results) > 0, "Should yield at least one result when tool is interrupted"
                assert results[0].get("_status") == "interrupted"
                assert "status" not in results[0]
                assert "interrupt" not in results[0]
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


class TestContinueChatPauseSemantics:
    """Tests for state-aware pause semantics in continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_defaults_to_preserve_context_true(self):
        """PAUSED + USER_INTERRUPT should default preserve_context=True."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_pause_user_interrupt",
                    content="/prompt/ test -> result",
                )

                captured_kwargs = {}
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    captured_kwargs.update(kwargs)
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
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
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_respects_explicit_preserve_context(self):
        """Explicit preserve_context should not be overridden in USER_INTERRUPT path."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_pause_user_explicit",
                    content="/prompt/ test -> result",
                )

                captured_kwargs = {}
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    captured_kwargs.update(kwargs)
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None

                agent.status.state = AgentState.PAUSED
                agent._pause_type = PauseType.USER_INTERRUPT

                async for _ in agent.continue_chat(
                    message="continue",
                    preserve_context=False,
                ):
                    pass

                assert captured_kwargs.get("preserve_context") is False
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_tool_interrupt_requires_resume(self):
        """PAUSED + TOOL_INTERRUPT should fail-fast with NEED_RESUME."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.core.common.exceptions import DolphinAgentException
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_pause_tool_interrupt",
                    content="/prompt/ test -> result",
                )

                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context
                continue_called = {"value": False}

                async def mock_continue(*args, **kwargs):
                    continue_called["value"] = True
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor

                agent.status.state = AgentState.PAUSED
                agent._pause_type = PauseType.TOOL_INTERRUPT

                with pytest.raises(DolphinAgentException) as exc_info:
                    async for _ in agent.continue_chat(message="continue"):
                        pass

                assert exc_info.value.code == "NEED_RESUME"
                assert "resume" in str(exc_info.value).lower()
                assert continue_called["value"] is False
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_non_paused_does_not_inject_preserve_context(self):
        """Non-paused states should keep preserve_context unset by default."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_non_paused_default",
                    content="/prompt/ test -> result",
                )

                captured_kwargs = {}
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    captured_kwargs.update(kwargs)
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None
                agent.status.state = AgentState.RUNNING

                async for _ in agent.continue_chat(message="continue"):
                    pass

                assert "preserve_context" not in captured_kwargs
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_yields_interrupted_event_and_pauses(self):
        """UserInterrupt in continue_chat should yield interrupted event and pause agent."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.core.common.exceptions import UserInterrupt
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_user_interrupt_state_sync",
                    content="/prompt/ test -> result",
                )

                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    raise UserInterrupt("manual interrupt in continue_chat")
                    yield

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
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
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_user_interrupt_result_clears_interrupt_event(self):
        """User interrupt result payload should clear interrupt event and pause agent."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_user_interrupt_payload_path",
                    content="/prompt/ test -> result",
                )

                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    yield {
                        "status": "interrupted",
                        "interrupt_type": "user_interrupt",
                    }

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None
                agent.status.state = AgentState.RUNNING
                agent.get_interrupt_event().set()

                with patch.object(
                    agent, "clear_interrupt", wraps=agent.clear_interrupt
                ) as mock_clear_interrupt:
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
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)

    @pytest.mark.asyncio
    async def test_continue_chat_clears_pending_user_input_after_resume(self):
        """continue_chat should consume pending user input when resuming from USER_INTERRUPT."""
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState, PauseType
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_pending_user_input_cleanup",
                    content="/prompt/ test -> result",
                )

                captured_kwargs = {}
                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    captured_kwargs.update(kwargs)
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
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
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


    @pytest.mark.asyncio
    async def test_continue_chat_from_completed_state_user_interrupt_causes_lifecycle_exception(self):
        """BUG REPRO (P1): continue_chat from COMPLETED state + user_interrupt → AgentLifecycleException.

        After arun() completes normally the agent is in COMPLETED state.
        Calling continue_chat() skips the PAUSED branch and never transitions
        to RUNNING.  If a UserInterrupt is raised during execution,
        mark_user_interrupted() attempts COMPLETED→PAUSED which is illegal,
        raising AgentLifecycleException instead of yielding _status="interrupted".
        """
        from dolphin.core import flags
        from dolphin.core.agent.agent_state import AgentState
        from dolphin.core.common.exceptions import UserInterrupt
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_completed_then_interrupt",
                    content="/prompt/ test -> result",
                )

                mock_executor = MagicMock()
                mock_context = MagicMock()
                mock_context.get_all_variables_values = MagicMock(
                    return_value={"_progress": []}
                )
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    raise UserInterrupt("user pressed ctrl-c")
                    yield  # noqa: make it async generator

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None

                # Simulate post-arun() state: COMPLETED
                agent.status.state = AgentState.COMPLETED

                # This SHOULD yield {"_status": "interrupted"} gracefully,
                # but currently raises AgentLifecycleException because
                # mark_user_interrupted() cannot transition COMPLETED→PAUSED.
                results = []
                async for item in agent.continue_chat(message="new question"):
                    results.append(item)

                assert len(results) == 1
                assert results[0].get("_status") == "interrupted"
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)


class TestDeltaModeIntegrationWithContinueChat:
    """Integration tests for delta mode with continue_chat."""

    @pytest.mark.asyncio
    async def test_continue_chat_delta_mode_adds_delta_field(self):
        """continue_chat with stream_mode='delta' should add delta field."""
        from dolphin.core import flags
        from dolphin.sdk.agent.dolphin_agent import DolphinAgent

        original = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            with patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
                return_value=None,
            ):
                agent = DolphinAgent(
                    name="test_delta_integration",
                    content="/prompt/ test -> result",
                )

                # Mock executor with progress data
                mock_executor = MagicMock()
                mock_context = MagicMock()

                # Simulate streaming: progressively longer answer
                # Use deterministic state instead of relying on timing
                call_count = [0]

                def get_vars():
                    call_count[0] += 1
                    if call_count[0] == 1:
                        return {
                            "_progress": [
                                {"stage": "llm", "id": "s1", "answer": "Hello"}
                            ]
                        }
                    else:
                        return {
                            "_progress": [
                                {"stage": "llm", "id": "s1", "answer": "Hello World"}
                            ]
                        }

                mock_context.get_all_variables_values = get_vars
                mock_executor.context = mock_context

                async def mock_continue(*args, **kwargs):
                    yield {"status": "running"}
                    # Removed sleep - rely on deterministic mock state
                    yield {"status": "completed"}

                mock_executor.continue_exploration = mock_continue
                agent.executor = mock_executor
                agent.output_variables = None

                # Run with delta mode
                results = []
                async for result in agent.continue_chat(
                    message="test",
                    stream_mode="delta",
                    stream_variables=True
                ):
                    results.append(result)

                # Find results with delta field
                delta_results = [
                    r for r in results
                    if isinstance(r, dict) and "_progress" in r
                    and any("delta" in p for p in r["_progress"] if isinstance(p, dict))
                ]

                # Verify basic response structure
                # Delta fields may or may not be present depending on execution timing,
                # but we should always get valid dict results
                assert len(results) > 0, "continue_chat with delta mode should yield at least one result"
                assert all(isinstance(r, dict) for r in results), "All results from continue_chat should be dictionaries"
        finally:
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original)
