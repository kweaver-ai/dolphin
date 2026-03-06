"""Integration test: HISTORY bucket compression at turn boundaries.

Verifies that ContextManager.compress_all() is effective when called at
turn boundaries, preventing HISTORY from growing unbounded across turns.
This test reproduces the production issue where compress was never called.
"""

from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.context_engineer.config.settings import (
    BuildInBucket,
    ContextConfig,
)
from dolphin.core.common.enums import MessageRole, Messages


def _make_config(history_max_tokens: int = 16384) -> ContextConfig:
    """Create a config with a specific HISTORY token budget."""
    return ContextConfig.from_dict(
        {
            "model": {
                "name": "test-model",
                "context_limit": 32768,
                "output_target": 2048,
            },
            "buckets": {
                "_system": {
                    "name": "_system",
                    "min_tokens": 100,
                    "max_tokens": 1024,
                    "weight": 2.0,
                    "message_role": "system",
                },
                "_history": {
                    "name": "_history",
                    "min_tokens": 100,
                    "max_tokens": history_max_tokens,
                    "weight": 0.8,
                    "message_role": "user",
                },
                "_query": {
                    "name": "_query",
                    "min_tokens": 100,
                    "max_tokens": 1024,
                    "weight": 0.8,
                    "message_role": "user",
                },
                "_scratchpad": {
                    "name": "_scratchpad",
                    "min_tokens": 0,
                    "max_tokens": 4096,
                    "weight": 1.2,
                    "message_role": "user",
                },
            },
            "policies": {
                "default": {
                    "drop_order": [],
                    "bucket_order": [
                        "_system",
                        "_history",
                        "_query",
                        "_scratchpad",
                    ],
                }
            },
        }
    )


def _simulate_turn_history(turn_count: int) -> Messages:
    """Build a Messages object that simulates `turn_count` turns of history.

    Each turn has a user message (~50 tokens) and an assistant reply (~200 tokens),
    so total grows roughly linearly with turn_count.
    """
    msgs = Messages()
    for i in range(turn_count):
        msgs.add_message(
            content=f"User question for turn {i}: " + "context " * 20,
            role=MessageRole.USER,
        )
        msgs.add_message(
            content=f"Assistant answer for turn {i}: " + "detailed response " * 80,
            role=MessageRole.ASSISTANT,
        )
    return msgs


class TestHistoryCompressionAtTurnBoundary:
    """Test that compression is effective at turn boundaries."""

    def test_history_exceeds_budget_without_compression(self):
        """Without calling compress, HISTORY bucket grows beyond allocated_tokens.

        This reproduces the production bug: history is set but compress is never called,
        so token_count can far exceed allocated_tokens.
        """
        cm = ContextManager(context_config=_make_config(history_max_tokens=2048))
        cm.set_layout_policy("default")

        # Simulate 20 turns of history — well over 2048 tokens
        history = _simulate_turn_history(20)
        cm.add_bucket(
            BuildInBucket.HISTORY.value,
            history,
            message_role=MessageRole.USER,
        )

        # The bucket should need compression
        assert cm.needs_compression(), (
            "HISTORY bucket should need compression after 20 turns, "
            f"but token_count={cm.state.buckets[BuildInBucket.HISTORY.value].token_count}, "
            f"allocated={cm.state.buckets[BuildInBucket.HISTORY.value].allocated_tokens}"
        )

        # BUG REPRODUCTION: without compress_all(), the assembled context
        # contains unbounded history
        bucket = cm.state.buckets[BuildInBucket.HISTORY.value]
        assert bucket.token_count > bucket.allocated_tokens

    def test_compress_all_brings_history_within_budget(self):
        """After calling compress_all(), HISTORY token_count <= allocated_tokens."""
        cm = ContextManager(context_config=_make_config(history_max_tokens=2048))
        cm.set_layout_policy("default")

        history = _simulate_turn_history(20)
        cm.add_bucket(
            BuildInBucket.HISTORY.value,
            history,
            message_role=MessageRole.USER,
        )

        assert cm.needs_compression()

        # FIX: calling compress_all at turn boundary
        cm.compress_all()

        bucket = cm.state.buckets[BuildInBucket.HISTORY.value]
        assert bucket.token_count <= bucket.allocated_tokens, (
            f"After compress_all(), HISTORY should be within budget: "
            f"token_count={bucket.token_count}, allocated={bucket.allocated_tokens}"
        )
        assert not cm.needs_compression()

    def test_multi_turn_accumulation_stays_within_budget_with_compression(self):
        """Simulate multiple continue_exploration turns, calling compress at each boundary.

        This is the end-to-end scenario: each turn adds history, and compress_all()
        is called before assembling context for the LLM.
        """
        budget = 4096
        cm = ContextManager(context_config=_make_config(history_max_tokens=budget))
        cm.set_layout_policy("default")

        cm.add_bucket(
            BuildInBucket.SYSTEM.value,
            "You are a helpful assistant.",
            message_role=MessageRole.SYSTEM,
        )

        accumulated_history = Messages()

        for turn in range(15):
            # Each turn adds user + assistant messages to history
            accumulated_history.add_message(
                content=f"Turn {turn} question: " + "elaborate context " * 30,
                role=MessageRole.USER,
            )
            accumulated_history.add_message(
                content=f"Turn {turn} answer: " + "detailed explanation " * 60,
                role=MessageRole.ASSISTANT,
            )

            # Replace HISTORY bucket with accumulated history (like set_history_bucket does)
            if cm.has_bucket(BuildInBucket.HISTORY.value):
                cm.replace_bucket_content(
                    BuildInBucket.HISTORY.value, accumulated_history
                )
            else:
                cm.add_bucket(
                    BuildInBucket.HISTORY.value,
                    accumulated_history,
                    message_role=MessageRole.USER,
                )

            # Turn boundary: compress before assembling
            if cm.needs_compression():
                cm.compress_all()

            # Assemble and verify budget
            history_bucket = cm.state.buckets[BuildInBucket.HISTORY.value]
            assert history_bucket.token_count <= budget, (
                f"Turn {turn}: HISTORY exceeded budget after compression: "
                f"token_count={history_bucket.token_count}, budget={budget}"
            )

    def test_default_config_history_max_tokens_is_sufficient(self):
        """Default HISTORY max_tokens should be at least 8192 to support real sessions."""
        from dolphin.core.context_engineer.config.settings import get_default_config

        config = get_default_config()
        history_config = config.buckets.get("_history")
        assert history_config is not None, "_history bucket not in default config"
        assert history_config.max_tokens >= 8192, (
            f"Default _history max_tokens={history_config.max_tokens} is too small, "
            f"should be >= 8192 for multi-turn sessions"
        )
