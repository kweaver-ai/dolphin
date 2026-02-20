#!/usr/bin/env python3
"""
Unit tests for MessageCompressor and compression strategies.

These tests focus on regression prevention for the GLM 1214 error:
When system messages consume the entire token budget, the compressor
must still preserve at least one user message to satisfy GLM's
requirement that the first non-system message must be "user".

Run with: uv run python tests/unittest/message/test_compressor.py
"""

from dolphin.core.common.enums import Messages, MessageRole
from dolphin.core.message.compressor import TruncationStrategy
from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig, ContextConstraints


def create_test_context():
    """Create a context for testing."""
    cfg = GlobalConfig()
    return Context(config=cfg, verbose=False, is_cli=False)


def test_preserves_user_message_when_system_exceeds_budget():
    """
    Regression test for GLM 1214 error.
    
    When system messages consume the entire token budget (remaining_tokens <= 0),
    the compressor must still preserve at least one user message.
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    # Create messages with a very large system message
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 100000)  # ~130k tokens
    msgs.add_message(role=MessageRole.USER, content="User question here")
    msgs.add_message(role=MessageRole.ASSISTANT, content="Assistant reply")
    msgs.add_message(role=MessageRole.USER, content="Follow up question")
    
    # Very small token budget (smaller than system message)
    constraints = ContextConstraints(
        max_input_tokens=5000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # CRITICAL: Must have at least one user message
    roles = [m.role for m in result.compressed_messages]
    assert MessageRole.USER in roles, (
        "Compressor must preserve at least one user message to avoid GLM 1214 error"
    )
    
    # Should have at least 2 messages (system + user)
    assert len(result.compressed_messages) >= 2, (
        "Should have at least system + user messages"
    )
    print("  PASS: test_preserves_user_message_when_system_exceeds_budget")


def test_preserves_last_user_message():
    """Ensure both first and latest user messages are preserved when truncating.
    
    The compressor should preserve:
    - first user message: required by GLM API
    - latest user message: current task anchor in long sessions
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 50000)
    msgs.add_message(role=MessageRole.USER, content="FIRST_USER_MESSAGE")
    msgs.add_message(role=MessageRole.ASSISTANT, content="First answer")
    msgs.add_message(role=MessageRole.USER, content="LAST_USER_MESSAGE")
    
    constraints = ContextConstraints(
        max_input_tokens=3000,
        reserve_output_tokens=500,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # Find user messages in result
    user_messages = [m for m in result.compressed_messages if m.role == MessageRole.USER]
    
    assert len(user_messages) >= 1, "Should have at least one user message"
    
    # The FIRST user message should always be preserved (required by GLM API)
    assert any("FIRST_USER_MESSAGE" in m.content for m in user_messages), (
        "First user message should be preserved (required by GLM API)"
    )
    assert any("LAST_USER_MESSAGE" in m.content for m in user_messages), (
        "Latest user message should be preserved as task anchor"
    )
    print("  PASS: test_preserves_last_user_message")


def test_no_compression_when_under_budget():
    """Messages under budget should not be modified."""
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="Short system")
    msgs.add_message(role=MessageRole.USER, content="Short user")
    msgs.add_message(role=MessageRole.ASSISTANT, content="Short assistant")
    
    constraints = ContextConstraints(
        max_input_tokens=100000,
        reserve_output_tokens=10000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # All messages should be preserved
    assert len(result.compressed_messages) == 3
    assert result.compression_ratio == 1.0
    print("  PASS: test_no_compression_when_under_budget")


def test_empty_messages():
    """Empty message list should return empty result."""
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    
    constraints = ContextConstraints(
        max_input_tokens=10000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    assert len(result.compressed_messages) == 0
    assert result.compression_ratio == 1.0
    print("  PASS: test_empty_messages")


def test_only_system_and_user_messages():
    """Test with only system and user messages (no assistant)."""
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 80000)
    msgs.add_message(role=MessageRole.USER, content="Only user message")
    
    constraints = ContextConstraints(
        max_input_tokens=5000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # Must have user message
    roles = [m.role for m in result.compressed_messages]
    assert MessageRole.USER in roles
    print("  PASS: test_only_system_and_user_messages")


def test_tool_messages_handled_correctly():
    """Test compression with tool call messages."""
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 50000)
    msgs.add_message(role=MessageRole.USER, content="Use a tool")
    msgs.add_message(
        role=MessageRole.ASSISTANT, 
        content="",
        tool_calls=[{"id": "call_1", "function": {"name": "test_tool"}}]
    )
    msgs.add_message(
        role=MessageRole.TOOL,
        content="Tool result",
        tool_call_id="call_1",
        metadata={"name": "test_tool"}
    )
    msgs.add_message(role=MessageRole.USER, content="Thanks for using the tool")
    
    constraints = ContextConstraints(
        max_input_tokens=5000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # Must have at least one user message
    roles = [m.role for m in result.compressed_messages]
    assert MessageRole.USER in roles, (
        "Must preserve user message even with tool messages"
    )
    print("  PASS: test_tool_messages_handled_correctly")


def test_user_only_at_beginning_with_many_tool_calls():
    """
    Regression test for GLM 1214 error - edge case NOT covered by existing tests.
    
    Scenario: system -> user -> (assistant/tool)* pattern
    where user message is ONLY at the beginning (position 1), followed by
    many assistant/tool call pairs.
    
    When truncating from the end, the only user message at the beginning
    gets dropped, leaving only assistant/tool messages. This causes GLM
    to reject with 1214 error because the first non-system message must be "user".
    
    This is a common pattern in agent execution where:
    1. User gives initial instruction
    2. Agent executes many tool calls without further user interaction
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    # Create messages: system, user, then many assistant/tool pairs
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 5000)  # ~6k tokens
    msgs.add_message(role=MessageRole.USER, content="Initial user request that should be preserved")
    
    # Add 20 assistant/tool pairs with substantial content
    for i in range(20):
        msgs.add_message(
            role=MessageRole.ASSISTANT,
            content=f"Assistant response {i}" if i % 3 == 0 else "",
            tool_calls=[{"id": f"call_tool_{i}", "function": {"name": "_bash", "arguments": "{}"}}]
        )
        msgs.add_message(
            role=MessageRole.TOOL,
            content=f"Tool result {i}: " + "X" * 2000,  # ~2.5k tokens each
            tool_call_id=f"call_tool_{i}",
        )
    
    # Small token budget that forces aggressive truncation
    constraints = ContextConstraints(
        max_input_tokens=30000,
        reserve_output_tokens=8000,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # CRITICAL: First non-system message MUST be user
    first_non_system_idx = None
    for i, m in enumerate(result.compressed_messages):
        if m.role != MessageRole.SYSTEM:
            first_non_system_idx = i
            break
    
    assert first_non_system_idx is not None, "Should have non-system messages"
    
    first_non_system_role = result.compressed_messages[first_non_system_idx].role
    assert first_non_system_role == MessageRole.USER, (
        f"First non-system message must be 'user', got '{first_non_system_role.value}'. "
        f"GLM will reject this with 1214 error. "
        f"Roles: {[m.role.value for m in result.compressed_messages]}"
    )
    
    # Also verify user is in result at all
    assert any(m.role == MessageRole.USER for m in result.compressed_messages), (
        "Must have at least one user message in compressed result"
    )
    
    print("  PASS: test_user_only_at_beginning_with_many_tool_calls")


def test_date_and_knowledge_check_with_none_content():
    """_date_in_system_message / _knowledge_in_system_message must not crash on content=None."""
    from dolphin.core.common.enums import SingleMessage

    strategy = TruncationStrategy()

    # Bypass add_message assertion by constructing SingleMessage directly
    msgs = Messages()
    msg = SingleMessage(role=MessageRole.SYSTEM, content="")
    msg.content = None  # Simulate corrupted message
    msgs.messages.append(msg)

    # Should not raise TypeError: argument of type 'NoneType' is not iterable
    assert strategy._date_in_system_message(msgs) is False
    assert strategy._knowledge_in_system_message(msgs) is False


def validate_tool_pairing(messages: Messages) -> None:
    """
    Validate that every 'tool' message has a preceding 'assistant' message 
    with matching tool_calls.
    
    This validation prevents the API error:
    "messages with role 'tool' must be a response to a preceeding message with 'tool_calls'"
    
    Raises:
        AssertionError: If validation fails
    """
    # Build a set of valid tool_call_ids from assistant messages
    valid_tool_call_ids = set()
    last_assistant_with_tool_calls_idx = -1
    
    for i, msg in enumerate(messages):
        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    valid_tool_call_ids.add(tc_id)
            last_assistant_with_tool_calls_idx = i
        
        if msg.role == MessageRole.TOOL:
            tool_call_id = msg.tool_call_id
            # Check 1: tool message must have a tool_call_id
            assert tool_call_id, f"Tool message at index {i} has no tool_call_id"
            
            # Check 2: there must have been a preceding assistant with tool_calls
            assert last_assistant_with_tool_calls_idx >= 0, (
                f"Tool message at index {i} has no preceding assistant with tool_calls. "
                f"This will cause API error: 'messages with role \"tool\" must be a response "
                f"to a preceeding message with \"tool_calls\"'"
            )
            
            # Check 3: the tool_call_id must match one from assistant's tool_calls
            # Note: After truncation, the matching assistant might be removed, 
            # which is the bug we're testing for
            assert tool_call_id in valid_tool_call_ids, (
                f"Tool message at index {i} has tool_call_id='{tool_call_id}' which doesn't "
                f"match any preceding assistant's tool_calls. Valid IDs: {valid_tool_call_ids}"
            )


def test_tool_calls_pairing_preserved_after_truncation():
    """
    Regression test for tool_calls/tool pairing bug.
    
    Bug description (from error log):
    When truncating messages, the compressor may keep a 'tool' message but drop
    its corresponding 'assistant' message that contains tool_calls.
    
    This test uses large Assistant and Tool messages to maximize the probability
    of the truncation boundary falling BETWEEN them.
    
    We set Assistant size ~ Tool size ~ 1000 chars.
    If remaining space is ~1500, Tool (1000) fits, but Assistant (1000) doesn't.
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()
    
    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="System")
    msgs.add_message(role=MessageRole.USER, content="User")
    
    # Add 10 assistant/tool pairs
    # Use balanced sizes to make probability of splitting high (50%)
    # Assistant: ~1000 chars
    # Tool: ~1000 chars
    # Total pair: ~2000 chars
    for i in range(10):
        msgs.add_message(
            role=MessageRole.ASSISTANT,
            content="A" * 1000, 
            tool_calls=[{
                "id": f"call_{i}", 
                "type": "function",
                "function": {"name": "_bash", "arguments": "{}"}
            }]
        )
        msgs.add_message(
            role=MessageRole.TOOL,
            content="T" * 1000,
            tool_call_id=f"call_{i}",
        )
    
    # Constraints
    # We want to cut somewhere in the middle.
    # Total messages ~ 20000 chars.
    # Set limit to 11000 chars (approx).
    # This should leave us with ~5.5 pairs.
    # .5 pair means we get a Tool but no Assistant.
    
    # Note: estimate_tokens_from_chars might not be 1:1, but assuming linearity.
    # We use a value that is likely to not be a multiple of pair size.
    constraints = ContextConstraints(
        max_input_tokens=5000, # Approx 5000 tokens.
        # If 1 char = 0.3 tokens (latin), 2000 chars = 600 tokens.
        # 10 pairs = 6000 tokens.
        # Limit 5000 is likely to cut deep.
        reserve_output_tokens=0,
        preserve_system=True,
    )
    
    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)
    
    # Debug info
    print(f"Compressed from {len(msgs)} to {len(result.compressed_messages)} messages")
    
    # This validation should FAIL if the bug exists
    try:
        validate_tool_pairing(result.compressed_messages)
        print("  PASS: test_tool_calls_pairing_preserved_after_truncation")
    except AssertionError as e:
        # Re-raise with more context
        roles = [m.role.value for m in result.compressed_messages]
        # Count tool and assistant
        n_tool = roles.count("tool")
        n_assist = roles.count("assistant")
        print(f"  FAIL: Found {n_tool} tools and {n_assist} assistants. Pairing broken.")
        raise AssertionError(
            f"Tool/tool_calls pairing broken after truncation!\n"
            f"Compressed message roles: {roles}\n"
            f"Original error: {e}"
        )




def test_token_estimation_includes_tool_metadata_overhead():
    """Fast estimation should include tool_calls/tool_call_id structural overhead."""
    strategy = TruncationStrategy()

    with_tools = Messages()
    with_tools.add_message(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[{
            "id": "call_1234567890",
            "type": "function",
            "function": {"name": "_bash", "arguments": "{\"cmd\":\"echo hello\"}"},
        }],
    )
    with_tools.add_message(
        role=MessageRole.TOOL,
        content="ok",
        tool_call_id="call_1234567890",
        metadata={"name": "_bash"},
    )

    without_tools = Messages()
    without_tools.add_message(role=MessageRole.ASSISTANT, content="")
    without_tools.add_message(role=MessageRole.TOOL, content="ok")

    tokens_with_tools = strategy.estimate_tokens(with_tools)
    tokens_without_tools = strategy.estimate_tokens(without_tools)

    assert tokens_with_tools > tokens_without_tools, (
        "Token estimation should account for tool metadata overhead"
    )
    print("  PASS: test_token_estimation_includes_tool_metadata_overhead")


def test_message_ordering_multi_turn_no_compression():
    """
    Regression test for off-by-one bug in message assembly order.

    Bug: preparation() extracts latest_user_message, but compress() reassembles as:
        system → first_user → latest_user → other_messages
    This puts the current query BEFORE history, so LLM answers the previous question.

    Correct order: system → first_user → other_messages → latest_user

    This test covers the NO-compression path (under budget).
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()

    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="You are a helpful assistant.")
    msgs.add_message(role=MessageRole.USER, content="Q1: What is 1+1?")
    msgs.add_message(role=MessageRole.ASSISTANT, content="A1: 2")
    msgs.add_message(role=MessageRole.USER, content="Q2: What is 2+2?")

    constraints = ContextConstraints(
        max_input_tokens=100000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )

    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)

    # Extract non-system messages
    non_system = [m for m in result.compressed_messages if m.role != MessageRole.SYSTEM]

    # The last message MUST be the current user query
    assert non_system[-1].role == MessageRole.USER, (
        f"Last non-system message should be USER, got {non_system[-1].role.value}"
    )
    assert "Q2" in non_system[-1].content, (
        f"Last message should be the current query 'Q2', got: {non_system[-1].content}"
    )

    # Verify chronological order: Q1 → A1 → Q2
    contents = [m.content for m in non_system]
    q1_idx = next(i for i, c in enumerate(contents) if "Q1" in c)
    a1_idx = next(i for i, c in enumerate(contents) if "A1" in c)
    q2_idx = next(i for i, c in enumerate(contents) if "Q2" in c)

    assert q1_idx < a1_idx < q2_idx, (
        f"Messages must be in chronological order: Q1({q1_idx}) < A1({a1_idx}) < Q2({q2_idx}). "
        f"Got contents: {contents}"
    )
    print("  PASS: test_message_ordering_multi_turn_no_compression")


def test_message_ordering_multi_turn_with_compression():
    """
    Same off-by-one test but in the compression path (over budget, truncation kicks in).
    """
    ctx = create_test_context()
    strategy = TruncationStrategy()

    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 5000)
    msgs.add_message(role=MessageRole.USER, content="Q1: first question")
    msgs.add_message(role=MessageRole.ASSISTANT, content="A1: " + "x" * 3000)
    msgs.add_message(role=MessageRole.USER, content="Q2: second question")
    msgs.add_message(role=MessageRole.ASSISTANT, content="A2: " + "y" * 3000)
    msgs.add_message(role=MessageRole.USER, content="Q3_CURRENT: what is the answer?")

    # Budget tight enough to force truncation of some history
    constraints = ContextConstraints(
        max_input_tokens=6000,
        reserve_output_tokens=500,
        preserve_system=True,
    )

    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)

    non_system = [m for m in result.compressed_messages if m.role != MessageRole.SYSTEM]

    # The last message MUST be the current user query
    assert non_system[-1].role == MessageRole.USER, (
        f"Last non-system message should be USER, got {non_system[-1].role.value}"
    )
    assert "Q3_CURRENT" in non_system[-1].content, (
        f"Last message should be current query 'Q3_CURRENT', got: {non_system[-1].content}"
    )
    print("  PASS: test_message_ordering_multi_turn_with_compression")


def test_message_ordering_level_strategy():
    """
    Off-by-one test for LevelStrategy.
    """
    from dolphin.core.message.compressor import LevelStrategy

    ctx = create_test_context()
    strategy = LevelStrategy()

    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="System prompt")
    msgs.add_message(role=MessageRole.USER, content="Q1: hello")
    msgs.add_message(role=MessageRole.ASSISTANT, content="A1: hi there")
    msgs.add_message(role=MessageRole.USER, content="Q2_CURRENT: how are you?")

    constraints = ContextConstraints(
        max_input_tokens=100000,
        reserve_output_tokens=1000,
        preserve_system=True,
    )

    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)

    non_system = [m for m in result.compressed_messages if m.role != MessageRole.SYSTEM]

    assert non_system[-1].role == MessageRole.USER, (
        f"Last non-system message should be USER, got {non_system[-1].role.value}"
    )
    assert "Q2_CURRENT" in non_system[-1].content, (
        f"Last message should be current query, got: {non_system[-1].content}"
    )

    # Verify order
    contents = [m.content for m in non_system]
    q1_idx = next(i for i, c in enumerate(contents) if "Q1" in c)
    a1_idx = next(i for i, c in enumerate(contents) if "A1" in str(c))
    q2_idx = next(i for i, c in enumerate(contents) if "Q2_CURRENT" in c)

    assert q1_idx < a1_idx < q2_idx, (
        f"Messages must be in chronological order: Q1({q1_idx}) < A1({a1_idx}) < Q2({q2_idx}). "
        f"Got contents: {contents}"
    )
    print("  PASS: test_message_ordering_level_strategy")


def test_precise_count_used_near_budget_boundary():
    """Near budget boundary should use precise count and avoid unnecessary compression."""

    class BoundaryAwareTruncationStrategy(TruncationStrategy):
        def __init__(self):
            self.precise_count_calls = 0

        def _should_use_precise_count(self, estimated_tokens, budget_tokens):
            return True

        def _count_tokens_precise(self, context, messages):
            self.precise_count_calls += 1
            return 880

    ctx = create_test_context()
    strategy = BoundaryAwareTruncationStrategy()

    msgs = Messages()
    msgs.add_message(role=MessageRole.SYSTEM, content="S" * 400)
    msgs.add_message(role=MessageRole.USER, content="U" * 300)
    msgs.add_message(role=MessageRole.ASSISTANT, content="A" * 40)

    constraints = ContextConstraints(
        max_input_tokens=1000,
        reserve_output_tokens=100,
        preserve_system=True,
    )

    result = strategy.compress(context=ctx, constraints=constraints, messages=msgs)

    assert strategy.precise_count_calls == 1, "Precise counting should be triggered near boundary"
    assert len(result.compressed_messages) == len(msgs), "Messages should stay uncompressed"
    assert result.original_token_count == 880, "Result should use precise token count"
    assert result.compression_ratio == 1.0
    print("  PASS: test_precise_count_used_near_budget_boundary")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Running TruncationStrategy tests")
    print("=" * 60)
    
    tests = [
        test_preserves_user_message_when_system_exceeds_budget,
        test_preserves_last_user_message,
        test_no_compression_when_under_budget,
        test_empty_messages,
        test_only_system_and_user_messages,
        test_tool_messages_handled_correctly,
        test_user_only_at_beginning_with_many_tool_calls,
        test_tool_calls_pairing_preserved_after_truncation,
        test_token_estimation_includes_tool_metadata_overhead,
        test_precise_count_used_near_budget_boundary,
        test_message_ordering_multi_turn_no_compression,
        test_message_ordering_multi_turn_with_compression,
        test_message_ordering_level_strategy,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test.__name__}: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
