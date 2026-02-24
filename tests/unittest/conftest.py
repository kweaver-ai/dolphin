"""Unit test conftest.py — shared fixtures for unit tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_executor():
    """Create a fully mocked DolphinExecutor instance."""
    executor = MagicMock()
    executor.executor_init = AsyncMock()
    executor.start_coroutine = AsyncMock()
    executor.step_coroutine = AsyncMock()
    executor.run_coroutine = AsyncMock()
    executor.resume_coroutine = AsyncMock()
    executor.is_waiting_for_intervention = MagicMock(return_value=False)

    context = MagicMock()
    context.get_all_variables_values = MagicMock(return_value={"_progress": []})
    context.get_all_variables = MagicMock(return_value={})
    executor.context = context

    return executor


@pytest.fixture
def mock_context():
    """Create a mocked Context instance."""
    context = MagicMock()
    context.get_all_variables_values = MagicMock(return_value={"_progress": []})
    context.get_all_variables = MagicMock(return_value={})
    context.set_variable = MagicMock()
    context.get_variable = MagicMock(return_value=None)
    return context


@pytest.fixture
def dolphin_agent(mock_executor):
    """Factory fixture that creates a DolphinAgent with patched internals.

    Usage::

        def test_something(dolphin_agent):
            agent = dolphin_agent(content="/prompt/ hello -> result", name="my_agent")
    """

    def _factory(content="/prompt/ test -> result", name="test_agent", **kwargs):
        with patch(
            "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax",
            return_value=None,
        ), patch(
            "dolphin.sdk.agent.dolphin_agent.dolphin_language.DolphinExecutor",
            return_value=mock_executor,
        ):
            from dolphin.sdk.agent.dolphin_agent import DolphinAgent

            agent = DolphinAgent(content=content, name=name, **kwargs)
        return agent

    return _factory
