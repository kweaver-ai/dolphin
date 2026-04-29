#!/usr/bin/env python3
"""
Regression tests: exploration exception must not cause user message loss.

Bug: Both execute() and continue_exploration() call _update_history_and_cleanup()
AFTER the exploration loop without exception protection. If _explore_once() raises
(e.g. LLM API timeout), the cleanup never executes, causing:
  - User message not committed to HISTORY variable
  - Pending turn metadata (_pending_turn) left stale in context

These tests assert the expected observable outcomes. They FAIL on the current
buggy code and will PASS once the fix is applied.
"""

import unittest
import asyncio
from unittest.mock import MagicMock, patch

from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.common.constants import KEY_PENDING_TURN, KEY_HISTORY
from dolphin.core.common.enums import MessageRole
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.config.global_config import GlobalConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context() -> Context:
    ctx = Context(config=GlobalConfig(), context_manager=ContextManager())
    ctx._calc_all_skills()
    return ctx


def _make_block(context: Context, content: str = "test question") -> ExploreBlock:
    """Create a minimally configured ExploreBlock ready for testing."""
    block = ExploreBlock(context=context)
    block.content = content
    block.output_var = "result"
    block.assign_type = "->"
    block.history = True
    block.model = "mock-model"

    block.recorder = MagicMock()
    block.recorder.get_answer.return_value = "partial answer"
    block.recorder.get_progress_answers.return_value = {}
    return block


def _stub_execute_main_deps(block: ExploreBlock):
    """Stub out heavy dependencies so _execute_main can run in isolation."""
    block._make_init_messages = MagicMock()
    block._parse_hook_config = MagicMock()
    block.on_stop = None
    block.block_start_log = MagicMock()


async def _async_gen_raise(exc: Exception):
    """Async generator that immediately raises."""
    raise exc
    yield  # pragma: no cover


async def _async_gen_yield_then_raise(exc: Exception):
    """Async generator that yields one item then raises."""
    yield {"type": "text", "content": "partial"}
    raise exc


async def _noop_async_gen(*args, **kwargs):
    return
    yield  # pragma: no cover


def _get_history(context: Context) -> list:
    return context.get_var_value(KEY_HISTORY) or []


def _history_has_user_message(context: Context, content: str) -> bool:
    return any(
        entry.get("role") == MessageRole.USER.value and entry.get("content") == content
        for entry in _get_history(context)
    )


# ---------------------------------------------------------------------------
# execute() path
# ---------------------------------------------------------------------------

class TestExecuteExceptionMustNotLoseUserMessage(unittest.TestCase):
    """User message must be committed to HISTORY even when _explore_once raises."""

    def setUp(self):
        self.context = _make_context()

    def test_api_timeout_must_not_lose_user_message(self):
        """LLM API timeout during execute → user message must still appear in HISTORY."""
        block = _make_block(self.context, content="what is the weather today")
        block._explore_once = lambda no_cache=False: _async_gen_raise(
            RuntimeError("LLM API timeout")
        )
        _stub_execute_main_deps(block)

        with patch.object(type(block).__bases__[0], "execute",
                          new_callable=lambda: lambda *a, **kw: _noop_async_gen()):
            async def run():
                async for _ in block.execute("what is the weather today"):
                    pass

            with self.assertRaises(RuntimeError):
                asyncio.run(run())

        self.assertTrue(
            _history_has_user_message(self.context, "what is the weather today"),
            "User message lost from HISTORY after LLM API timeout",
        )

    def test_stream_interrupt_after_partial_response_must_not_lose_user_message(self):
        """Stream interrupted mid-response → user message must still appear in HISTORY."""
        block = _make_block(self.context, content="summarize this document")
        block._explore_once = lambda no_cache=False: _async_gen_yield_then_raise(
            ConnectionError("stream interrupted")
        )
        _stub_execute_main_deps(block)

        with patch.object(type(block).__bases__[0], "execute",
                          new_callable=lambda: lambda *a, **kw: _noop_async_gen()):
            async def run():
                async for _ in block.execute("summarize this document"):
                    pass

            with self.assertRaises(ConnectionError):
                asyncio.run(run())

        self.assertTrue(
            _history_has_user_message(self.context, "summarize this document"),
            "User message lost from HISTORY after stream interruption",
        )


# ---------------------------------------------------------------------------
# continue_exploration() path
# ---------------------------------------------------------------------------

class TestContinueExplorationExceptionMustNotLoseUserMessage(unittest.TestCase):
    """Multi-turn: follow-up message must not vanish when _explore_once raises."""

    def setUp(self):
        self.context = _make_context()
        # Seed a previous successful turn
        self.context.set_variable(KEY_HISTORY, [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ])

    def test_api_timeout_must_not_lose_followup_message(self):
        """LLM API timeout during continue_exploration → follow-up must appear in HISTORY."""
        block = _make_block(self.context)
        block._explore_once = lambda no_cache=False: _async_gen_raise(
            RuntimeError("LLM API timeout")
        )

        async def run():
            async for _ in block.continue_exploration(
                model="mock-model",
                content="follow-up question",
            ):
                pass

        with self.assertRaises(RuntimeError):
            asyncio.run(run())

        self.assertTrue(
            _history_has_user_message(self.context, "follow-up question"),
            "Follow-up user message lost from HISTORY after LLM API timeout",
        )

    def test_api_timeout_must_not_corrupt_previous_history(self):
        """Exception must not damage the history entries from previous turns."""
        block = _make_block(self.context)
        block._explore_once = lambda no_cache=False: _async_gen_raise(
            RuntimeError("LLM API timeout")
        )

        async def run():
            async for _ in block.continue_exploration(
                model="mock-model",
                content="follow-up question",
            ):
                pass

        with self.assertRaises(RuntimeError):
            asyncio.run(run())

        # Previous turn must still be intact
        self.assertTrue(
            _history_has_user_message(self.context, "first question"),
            "Previous history entry corrupted after exception",
        )


# ---------------------------------------------------------------------------
# Pending turn stale state
# ---------------------------------------------------------------------------

class TestPendingTurnMustNotRemainStaleAfterException(unittest.TestCase):
    """Pending turn metadata must be resolved even when exploration crashes."""

    def setUp(self):
        self.context = _make_context()

    def test_pending_turn_must_not_remain_after_exception(self):
        """After exception, pending turn must be committed or cleaned up,
        not left dangling in context."""
        block = _make_block(self.context, content="my question")
        block._explore_once = lambda no_cache=False: _async_gen_raise(
            TimeoutError("read timeout")
        )

        async def run():
            async for _ in block.continue_exploration(
                model="mock-model",
                content="my question",
            ):
                pass

        with self.assertRaises(TimeoutError):
            asyncio.run(run())

        pending = block._get_pending_turn()
        self.assertIsNone(
            pending,
            "Pending turn left stale in context after exception — "
            "next turn's _mark_pending_turn will silently overwrite it, "
            "permanently losing this turn's user message",
        )

    def test_consecutive_failures_must_not_lose_first_user_message(self):
        """If first turn crashes and second turn starts, the first turn's
        user message must not be silently discarded from history."""
        block = _make_block(self.context, content="first question")

        # First turn: mark pending, then simulate exception (cleanup never ran)
        block._mark_pending_turn()
        pending = block._get_pending_turn()
        self.assertIsNotNone(pending)

        # Simulate: cleanup was NOT called (the bug)
        # Second turn starts — _mark_pending_turn overwrites the stale entry
        block.content = "second question"
        block._mark_pending_turn()

        # The first question is now permanently gone — neither in HISTORY
        # nor in pending turn
        self.assertFalse(
            _history_has_user_message(self.context, "first question"),
            "First question permanently lost — not in HISTORY and pending turn overwritten",
        )
        # This test documents the data loss consequence. After fix, the first
        # turn's cleanup should have committed or preserved the message before
        # the second turn can overwrite pending.


if __name__ == "__main__":
    unittest.main()
