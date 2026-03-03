#!/usr/bin/env python3
"""
Regression tests for context compression in agentic (multi-tool-call) loops.

Reproduces the scenario observed in production on 2026-02-25:
- Session: tg_session_demo_agent__8576399597
- User request: "帮我修复" (4 chars) after 34 messages of prior conversation
- Agent executed 33 tool calls (read_file, bash, grep, python, write_file)
- Context compressed 22 times in 3 minutes (19:20 ~ 19:23)
- Original context grew from 147K to 259K tokens despite repeated compression
- Compression ratio degraded from 0.81 → 0.45

Key bugs identified:
1. latest_user_message only preserved when it's the LAST non-system message
   (idx == last_non_system_index), but in agentic loops the last message is
   always assistant/tool — so the user's query gets treated as droppable history.
2. Tool outputs accumulate without bound in each agentic turn, causing
   context to grow faster than compression can shrink it.

Run with: uv run pytest tests/unittest/message/test_compressor_agentic_loop.py -v
"""

import hashlib
import pytest
from dolphin.core.common.enums import Messages, MessageRole
from dolphin.core.message.compressor import TruncationStrategy
from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig, ContextConstraints


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

def create_test_context():
    """Create a minimal Context for testing."""
    cfg = GlobalConfig()
    return Context(config=cfg, verbose=False, is_cli=False)


def _make_filler(char_count: int, seed: str = "filler") -> str:
    """Generate filler text of approximately `char_count` chars.

    The text is composed of space-separated 8-char hex "words" to ensure:
    1. Consistent token estimation between char-based and word-based counters
       (SimpleTokenizer.count_tokens uses regex word splitting — continuous
       strings without spaces are counted as 1 token regardless of length)
    2. Deterministic, varied content that resists BPE merging
    """
    words = []
    total = 0
    idx = 0
    while total < char_count:
        h = hashlib.md5(f"{seed}_{idx}".encode()).hexdigest()
        # Split 32-char hex into 4 x 8-char words separated by spaces
        for j in range(0, 32, 8):
            words.append(h[j:j+8])
            total += 9  # 8 chars + 1 space
            if total >= char_count:
                break
        idx += 1
    return " ".join(words)[:char_count]


# Production config: deepseek-chat model with 128K context
PROD_CONSTRAINTS = ContextConstraints(
    max_input_tokens=128000,
    reserve_output_tokens=16384,
    preserve_system=True,
)


def _build_system_prompt(char_count: int = 9500) -> str:
    """Build a system prompt similar to the production demo_agent.

    The real system prompt is ~9500 chars and includes:
    - Tool descriptions (~3000 chars)
    - Available resource skills listing (~1500 chars)
    - Agent behavior rules, MEMORY, HEARTBEAT config (~5000 chars)
    """
    return _make_filler(char_count, seed="system_prompt")


def _build_prior_history(num_pairs: int = 17) -> list:
    """Build prior conversation history (before "帮我修复").

    In production, there were 34 messages (17 assistant/tool pairs) from
    a prior coding-master analyze task totaling ~40K chars. Several tool
    responses were large (12K+ chars from read_file of factory.py and
    coding-master SKILL.md).

    Returns list of (role, content, tool_calls, tool_call_id) tuples.
    """
    history = []
    # First user message (the initial request)
    history.append({
        "role": MessageRole.USER,
        "content": "用 coding master 帮我看下 alfred 测试 case 的情况",
    })

    # Simulate 17 rounds of tool calls with realistic content sizes:
    # Sizes based on actual session data (content_len values)
    tool_content_sizes = [
        242, 12316, 389, 150, 942, 11, 1101, 395, 1096, 2,
        1096, 1096, 6933, 7314, 1096, 4440, 1217,
    ]
    tool_names = [
        "_load_resource_skill", "_load_resource_skill", "_bash", "_bash",
        "_bash", "_bash", "_bash", "_bash", "_bash", "_bash",
        "_bash", "_bash", "_read_file", "_read_file", "_bash",
        "_bash", None,  # last one is final answer (no tool call)
    ]

    for i in range(num_pairs):
        tool_id = f"call_prior_{i}"
        tool_name = tool_names[i] if i < len(tool_names) else "_bash"
        content_size = tool_content_sizes[i] if i < len(tool_content_sizes) else 500

        if tool_name is None:
            # Final answer from assistant (no tool call)
            history.append({
                "role": MessageRole.ASSISTANT,
                "content": _make_filler(content_size, seed=f"prior_asst_{i}"),
            })
        else:
            # Assistant with tool_call
            history.append({
                "role": MessageRole.ASSISTANT,
                "content": "",
                "tool_calls": [{
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }],
            })
            # Tool response
            history.append({
                "role": MessageRole.TOOL,
                "content": _make_filler(content_size, seed=f"prior_tool_{i}"),
                "tool_call_id": tool_id,
            })

    return history


def _build_fix_turn_messages(num_rounds: int = 33) -> list:
    """Build the "帮我修复" turn messages.

    In production, the agent made 33 tool calls to fix test failures.
    Multiple read_file calls returned the same 12K+ char file (factory.py).
    Tool outputs included bash results (~1K), grep results, file contents.

    Returns list of message dicts.
    """
    messages = []

    # The user query
    messages.append({
        "role": MessageRole.USER,
        "content": "帮我修复",
    })

    # Tool call sizes based on actual session data (content_len from [35]-[98])
    tool_sizes = [
        989, 12322, 88, 3324, 1084, 23, 105, 12322, 69, 152,
        192, 77, 990, 1101, 1096, 1096, 3038, 11, 12322, 11,
        1096, 989, 1096, 595, 989, 12322, 449, 298, 12322, 77,
        989, 1097, 551,
    ]
    tool_names = [
        "_bash", "_read_file", "_grep", "_read_file", "_bash",
        "_bash", "_bash", "_read_file", "_bash", "_bash",
        "_bash", "_write_file", "_bash", "_bash", "_bash",
        "_bash", "_get_cached_result_detail", "_bash", "_read_file", "_bash",
        "_bash", "_bash", "_bash", "_bash", "_bash",
        "_read_file", "_python", "_bash", "_read_file", "_write_file",
        "_bash", "_bash", None,  # last is final answer
    ]

    for i in range(num_rounds):
        tool_id = f"call_fix_{i}"
        tool_name = tool_names[i] if i < len(tool_names) else "_bash"
        content_size = tool_sizes[i] if i < len(tool_sizes) else 500

        if tool_name is None:
            # Final answer
            messages.append({
                "role": MessageRole.ASSISTANT,
                "content": _make_filler(content_size, seed=f"fix_final_{i}"),
            })
        else:
            # Some assistant messages had content (progress reports)
            assistant_content = ""
            if i == 28:
                assistant_content = _make_filler(90, seed="fix_progress_28")
            elif i == 30:
                assistant_content = _make_filler(44, seed="fix_progress_30")

            messages.append({
                "role": MessageRole.ASSISTANT,
                "content": assistant_content,
                "tool_calls": [{
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }],
            })
            messages.append({
                "role": MessageRole.TOOL,
                "content": _make_filler(content_size, seed=f"fix_tool_{i}"),
                "tool_call_id": tool_id,
            })

    return messages


def _build_full_session_messages() -> Messages:
    """Build a Messages object mimicking the full production session.

    Structure:
    - 1 system prompt (~9500 chars)
    - 34 prior history messages (~40K chars)
    - 1 user "帮我修复" (4 chars)
    - 65 fix-turn messages (33 tool calls, ~83K chars)

    Total: ~123K chars ≈ 150K+ tokens (Chinese + English mix)
    """
    msgs = Messages()

    # System prompt
    msgs.add_message(role=MessageRole.SYSTEM, content=_build_system_prompt())

    # Prior history
    for m in _build_prior_history():
        kwargs = {"role": m["role"], "content": m["content"]}
        if "tool_calls" in m:
            kwargs["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            kwargs["tool_call_id"] = m["tool_call_id"]
        msgs.add_message(**kwargs)

    # Fix turn messages
    for m in _build_fix_turn_messages():
        kwargs = {"role": m["role"], "content": m["content"]}
        if "tool_calls" in m:
            kwargs["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            kwargs["tool_call_id"] = m["tool_call_id"]
        msgs.add_message(**kwargs)

    return msgs


def _build_mid_turn_messages(num_completed_rounds: int = 10) -> Messages:
    """Build messages as they would appear MID-TURN in the agentic loop.

    During the agentic loop, each _explore_once() call sends ALL messages
    (system + history + query + scratchpad) to the LLM. The SCRATCHPAD
    bucket accumulates assistant+tool messages from prior rounds.

    This simulates the message state at round N where:
    - System prompt is present
    - Full prior history (34 messages) is in HISTORY bucket
    - User "帮我修复" is in QUERY bucket
    - N rounds of assistant+tool are in SCRATCHPAD bucket

    The key issue: "帮我修复" is NOT the last message — the last message
    is the tool response from the previous round.
    """
    msgs = Messages()

    # System prompt
    msgs.add_message(role=MessageRole.SYSTEM, content=_build_system_prompt())

    # Prior history (HISTORY bucket)
    for m in _build_prior_history():
        kwargs = {"role": m["role"], "content": m["content"]}
        if "tool_calls" in m:
            kwargs["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            kwargs["tool_call_id"] = m["tool_call_id"]
        msgs.add_message(**kwargs)

    # User query (QUERY bucket)
    msgs.add_message(role=MessageRole.USER, content="帮我修复")

    # Completed tool call rounds (SCRATCHPAD bucket)
    fix_msgs = _build_fix_turn_messages(num_rounds=num_completed_rounds)
    # Skip the first user message (already added above), start from tool calls
    for m in fix_msgs[1:]:
        kwargs = {"role": m["role"], "content": m["content"]}
        if "tool_calls" in m:
            kwargs["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            kwargs["tool_call_id"] = m["tool_call_id"]
        msgs.add_message(**kwargs)

    return msgs


# ---------------------------------------------------------------------------
# Bug 1: latest_user_message not preserved in agentic loops
# ---------------------------------------------------------------------------

class TestLatestUserMessagePreservation:
    """Tests for Bug 1: latest_user_message only preserved when it's the
    LAST non-system message.

    In agentic loops, the last message is always assistant (with tool_calls)
    or tool (response), so the condition `idx == last_non_system_index`
    never matches for the user message. This means the current user query
    is treated as ordinary droppable history and may be truncated away.
    """

    def test_user_query_preserved_when_followed_by_tool_calls(self):
        """Core reproduction: user query followed by many tool call pairs.

        This is the EXACT pattern in the production bug:
        system → [prior history...] → user("帮我修复") → assistant+tool × N

        The user message is not the last message, so preparation() puts it
        into other_messages instead of latest_user_message.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=10)

        # Use production constraints
        result = strategy.compress(
            context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
        )

        # Find the user "帮我修复" in compressed output
        user_messages = [
            m for m in result.compressed_messages
            if m.role == MessageRole.USER
        ]

        # The current query MUST be preserved
        query_preserved = any("帮我修复" in (m.content or "") for m in user_messages)
        assert query_preserved, (
            "Bug: User query '帮我修复' was truncated during compression. "
            "In agentic loops, the latest user message is not the last "
            "non-system message (tool responses come after), so "
            "preparation() fails to extract it as latest_user_message."
        )

    def test_preparation_extracts_latest_user_even_when_not_last(self):
        """Directly test preparation() to show the bug in latest_user_message extraction.

        In the current code:
            elif (msg.role == USER and idx == latest_user_index
                  and idx == last_non_system_index):
                latest_user_message.add_message(content=msg)

        The condition `idx == last_non_system_index` requires the user message
        to be the absolute last non-system message. In agentic loops this is
        never true.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = Messages()
        msgs.add_message(role=MessageRole.SYSTEM, content="System prompt")
        msgs.add_message(role=MessageRole.USER, content="FIRST_QUERY")
        msgs.add_message(role=MessageRole.ASSISTANT, content="reply1")
        msgs.add_message(role=MessageRole.USER, content="CURRENT_QUERY")
        # After current query, agent makes tool calls:
        msgs.add_message(
            role=MessageRole.ASSISTANT, content="",
            tool_calls=[{"id": "tc1", "function": {"name": "_bash", "arguments": "{}"}}],
        )
        msgs.add_message(
            role=MessageRole.TOOL, content="tool output",
            tool_call_id="tc1",
        )

        constraints = ContextConstraints(
            max_input_tokens=100000,
            reserve_output_tokens=1000,
            preserve_system=True,
        )

        system_msgs, first_user, latest_user, other_msgs = strategy.preparation(
            ctx, msgs, constraints,
        )

        # first_user should be FIRST_QUERY
        assert len(first_user) == 1
        assert "FIRST_QUERY" in first_user[0].content

        # Bug: latest_user will be EMPTY because CURRENT_QUERY is not the
        # last non-system message (the tool message is).
        # This test documents the bug — it will fail once the fix is applied.
        latest_user_contents = [m.content for m in latest_user]
        has_current_query = any("CURRENT_QUERY" in c for c in latest_user_contents)

        # After fix: latest_user_message should contain CURRENT_QUERY
        # even when it's not the last non-system message.
        assert has_current_query, (
            "latest_user_message should contain the current query "
            "even when tool call messages follow it."
        )

    def test_user_query_not_lost_under_aggressive_compression(self):
        """With tight budget, verify user query survives compression.

        Even if all prior history and early tool calls are truncated,
        the current user query must remain to anchor the task.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=20)

        # Very tight budget — forces aggressive truncation
        tight_constraints = ContextConstraints(
            max_input_tokens=30000,
            reserve_output_tokens=8000,
            preserve_system=True,
        )

        result = strategy.compress(
            context=ctx, constraints=tight_constraints, messages=msgs,
        )

        user_messages = [
            m for m in result.compressed_messages
            if m.role == MessageRole.USER
        ]

        query_preserved = any("帮我修复" in (m.content or "") for m in user_messages)
        assert query_preserved, (
            "User query '帮我修复' lost under aggressive compression. "
            "The compressor should always preserve the current task query "
            "regardless of how many tool calls follow it."
        )


# ---------------------------------------------------------------------------
# Bug 2: Context growth outpaces compression in agentic loops
# ---------------------------------------------------------------------------

class TestContextGrowthPattern:
    """Tests for the context growth pattern observed in production.

    Production observation:
    - 22 compression events in 3 minutes
    - Pre-compression size grew: 147K → 259K tokens
    - Post-compression target: ~117K tokens (budget)
    - Each round adds assistant+tool messages to SCRATCHPAD
    - Compression only drops oldest messages, but new ones keep coming

    KEY INSIGHT: In production, compression happens inside _chat_stream()
    and the result is used ONLY for the current LLM API call. The next
    _explore_once() round re-assembles messages from context_manager BUCKETS
    (SYSTEM + HISTORY + QUERY + SCRATCHPAD). The HISTORY bucket is never
    modified by compression — only the assembled message list is compressed.
    Meanwhile SCRATCHPAD grows with each tool call round.

    This "compress-then-reassemble" pattern means:
    - Pre-compression size grows MONOTONICALLY (bucket content only grows)
    - Compression becomes a Sisyphean task (compress → reassemble → bigger)
    - Ratio degrades as the preserved tail (recent tool calls) grows
    """

    def test_bucket_reassembly_causes_monotonic_growth(self):
        """Reproduce the exact production pattern: compress-then-reassemble.

        In production, messages are reassembled from buckets each round:
        assembled = SYSTEM + HISTORY + QUERY + SCRATCHPAD(growing)

        Compression only affects the assembled snapshot for the API call,
        not the underlying buckets. So next round's pre-compression size
        is always: previous_pre + new_round_content.

        Production data showed 21 consecutive rounds where pre-compression
        size grew monotonically from 147K to 259K tokens.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()
        # Disable precise token counting to avoid SimpleTokenizer word-count
        # vs char-estimate mismatch (word count is ~10x lower than char estimate,
        # causing the compressor to incorrectly skip compression near the budget
        # boundary — a separate bug, not the one we're testing here).
        strategy.PRECISE_ESTIMATION_LOWER_RATIO = 0
        strategy.PRECISE_ESTIMATION_UPPER_RATIO = 0

        # Base messages (simulating SYSTEM + HISTORY + QUERY buckets)
        base_msgs_data = []
        # System prompt
        base_msgs_data.append({
            "role": MessageRole.SYSTEM,
            "content": _build_system_prompt(),
        })
        # Prior history
        for m in _build_prior_history():
            base_msgs_data.append(m)
        # User query
        base_msgs_data.append({
            "role": MessageRole.USER,
            "content": "帮我修复",
        })

        # SCRATCHPAD: accumulates tool call rounds
        scratchpad_msgs_data = []

        compression_log = []

        # Tool output sizes from production (content_len of tool messages)
        tool_sizes = [
            989, 12322, 88, 3324, 1084, 23, 105, 12322, 69, 152,
            192, 77, 990, 1101, 1096, 1096, 3038, 11, 12322, 11,
        ]

        for round_num in range(20):
            # === Simulate bucket reassembly ===
            # Each round, messages are built from scratch:
            # SYSTEM + HISTORY + QUERY + SCRATCHPAD
            msgs = Messages()
            for m in base_msgs_data:
                kwargs = {"role": m["role"], "content": m["content"]}
                if "tool_calls" in m:
                    kwargs["tool_calls"] = m["tool_calls"]
                if "tool_call_id" in m:
                    kwargs["tool_call_id"] = m["tool_call_id"]
                msgs.add_message(**kwargs)

            for m in scratchpad_msgs_data:
                kwargs = {"role": m["role"], "content": m["content"]}
                if "tool_calls" in m:
                    kwargs["tool_calls"] = m["tool_calls"]
                if "tool_call_id" in m:
                    kwargs["tool_call_id"] = m["tool_call_id"]
                msgs.add_message(**kwargs)

            # === Compress (as _chat_stream does) ===
            result = strategy.compress(
                context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
            )

            compression_log.append({
                "round": round_num,
                "original_tokens": result.original_token_count,
                "compressed_tokens": result.compressed_token_count,
                "ratio": result.compression_ratio,
            })

            # === Simulate LLM response + tool execution ===
            # New assistant + tool messages go into SCRATCHPAD (not compressed)
            tool_id = f"call_round_{round_num}"
            output_size = tool_sizes[round_num] if round_num < len(tool_sizes) else 500

            scratchpad_msgs_data.append({
                "role": MessageRole.ASSISTANT,
                "content": "",
                "tool_calls": [{
                    "id": tool_id, "type": "function",
                    "function": {"name": "_bash", "arguments": "{}"},
                }],
            })
            scratchpad_msgs_data.append({
                "role": MessageRole.TOOL,
                "content": _make_filler(output_size, seed=f"bucket_tool_{round_num}"),
                "tool_call_id": tool_id,
            })

        # === Verify production pattern ===
        compressions = [e for e in compression_log if e["ratio"] < 1.0]

        print(f"\n  Total rounds: {len(compression_log)}")
        print(f"  Compression events: {len(compressions)}")

        # 1. Pre-compression sizes must be monotonically increasing
        pre_sizes = [e["original_tokens"] for e in compression_log]
        monotonic_violations = sum(
            1 for i in range(1, len(pre_sizes)) if pre_sizes[i] <= pre_sizes[i-1]
        )
        print(f"  Pre-compression monotonic: {monotonic_violations == 0} "
              f"(violations: {monotonic_violations})")
        print(f"  Pre-compression range: {pre_sizes[0]} -> {pre_sizes[-1]}")
        assert monotonic_violations == 0, (
            f"Pre-compression sizes must grow monotonically in bucket-reassembly "
            f"pattern, but had {monotonic_violations} violations. "
            f"Sizes: {pre_sizes}"
        )

        # 2. Post-compression "越压越大" pattern (compressed output grows)
        if len(compressions) >= 2:
            post_sizes = [e["compressed_tokens"] for e in compressions]
            grow_count = sum(
                1 for i in range(1, len(post_sizes))
                if post_sizes[i] > post_sizes[i-1]
            )
            print(f"  Post-compression growth: {grow_count}/{len(compressions)-1} rounds")
            for i, e in enumerate(compressions):
                prev = compressions[i-1]["compressed_tokens"] if i > 0 else 0
                delta = e["compressed_tokens"] - prev if i > 0 else 0
                marker = "↑" if delta > 0 else "↓" if delta < 0 else "="
                print(f"    Round {e['round']:2d}: {e['original_tokens']:>7d} -> "
                      f"{e['compressed_tokens']:>7d} (ratio={e['ratio']:.3f}) {marker}")

        # 3. Should have multiple compression events (production had 22)
        assert len(compressions) >= 5, (
            f"Expected at least 5 compression events (production had 22), "
            f"got {len(compressions)}. Pre-compression sizes: {pre_sizes}"
        )

    def test_compression_should_reduce_next_round_pre_size(self):
        """Bug 3: compression result must be persisted back to buckets so that
        the next round assembles from the compressed base.

        Expected: when compression happens at round N, the pre-compression
        size at round N+1 should be ≤ round N's compressed size + new content.

        Uses MessageCompressor (not TruncationStrategy directly) so that the
        _persist_compressed_history() hook fires after compression.
        """
        from dolphin.core.message.compressor import MessageCompressor
        from dolphin.core.config.global_config import ContextEngineerConfig

        ctx = create_test_context()
        ce_config = ContextEngineerConfig(
            default_strategy="truncation",
            constraints=PROD_CONSTRAINTS,
        )
        compressor = MessageCompressor(config=ce_config, context=ctx)
        # Disable precise counting to avoid SimpleTokenizer ratio mismatch
        for s in compressor.strategies.values():
            s.PRECISE_ESTIMATION_LOWER_RATIO = 0
            s.PRECISE_ESTIMATION_UPPER_RATIO = 0

        # --- Set up buckets to mimic production ---
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        # SYSTEM bucket
        sys_msgs = Messages()
        sys_msgs.add_message(role=MessageRole.SYSTEM, content=_build_system_prompt())
        ctx.context_manager.add_bucket(BuildInBucket.SYSTEM.value, sys_msgs)

        # HISTORY bucket (prior conversation)
        hist_msgs = Messages()
        for m in _build_prior_history():
            kwargs = {"role": m["role"], "content": m["content"]}
            if "tool_calls" in m: kwargs["tool_calls"] = m["tool_calls"]
            if "tool_call_id" in m: kwargs["tool_call_id"] = m["tool_call_id"]
            hist_msgs.add_message(**kwargs)
        ctx.context_manager.add_bucket(BuildInBucket.HISTORY.value, hist_msgs)

        # QUERY bucket
        query_msgs = Messages()
        query_msgs.add_message(role=MessageRole.USER, content="帮我修复")
        ctx.context_manager.add_bucket(BuildInBucket.QUERY.value, query_msgs)

        # SCRATCHPAD bucket (starts empty)
        scratch_msgs = Messages()
        ctx.context_manager.add_bucket(BuildInBucket.SCRATCHPAD.value, scratch_msgs)

        compression_log = []
        tool_sizes = [
            989, 12322, 88, 3324, 1084, 23, 105, 12322, 69, 152,
            192, 77, 990, 1101, 1096, 1096, 3038, 11, 12322, 11,
            1096, 989, 1096, 595, 989, 12322, 449, 298, 12322, 77,
        ]

        for round_num in range(30):
            # Assemble from buckets (like production's to_dph_messages)
            msgs = ctx.context_manager.to_dph_messages()

            # Compress via MessageCompressor (triggers persist-back on ratio<1)
            result = compressor.compress_messages(msgs)
            compression_log.append({
                "round": round_num,
                "original_tokens": result.original_token_count,
                "compressed_tokens": result.compressed_token_count,
                "ratio": result.compression_ratio,
            })

            # Add new tool call to SCRATCHPAD (like explore_block does)
            tid = f"call_persist_{round_num}"
            sz = tool_sizes[round_num] if round_num < len(tool_sizes) else 500
            new_msgs = Messages()
            new_msgs.add_message(
                role=MessageRole.ASSISTANT, content="",
                tool_calls=[{"id": tid, "function": {"name": "_bash", "arguments": "{}"}}],
            )
            new_msgs.add_message(
                role=MessageRole.TOOL,
                content=_make_filler(sz, seed=f"persist_tool_{round_num}"),
                tool_call_id=tid,
            )
            # Append to scratchpad bucket
            scratch_bucket = ctx.context_manager.state.buckets.get(
                BuildInBucket.SCRATCHPAD.value
            )
            if scratch_bucket is not None and isinstance(scratch_bucket.content, Messages):
                for m in new_msgs:
                    scratch_bucket.content.add_message(content=m)
                scratch_bucket.is_dirty = True
            else:
                ctx.context_manager.add_bucket(
                    BuildInBucket.SCRATCHPAD.value, new_msgs
                )

        # Verify: with persist-back, pre-compression sizes should be bounded
        # near the budget, not growing without limit.
        #
        # Without the fix: pre-compression sizes grow monotonically (e.g. 113K → 214K)
        # because uncompressed history is re-assembled every round.
        #
        # With the fix: after first compression, the persisted compressed
        # history keeps pre-compression size near budget + 1 round of new content.
        budget = PROD_CONSTRAINTS.max_input_tokens - PROD_CONSTRAINTS.reserve_output_tokens
        # Allow 30% over budget (one large tool output can push it up temporarily)
        max_allowed = budget * 1.30

        compressions = [e for e in compression_log if e["ratio"] < 1.0]
        if compressions:
            # Check all rounds AFTER the first compression
            first_compression_round = compressions[0]["round"]
            post_compression = [
                e for e in compression_log if e["round"] > first_compression_round
            ]
            overflows = [
                e for e in post_compression
                if e["original_tokens"] > max_allowed
            ]

            print(f"\n  Budget: {budget}, max_allowed: {max_allowed:.0f}")
            print(f"  Compression events: {len(compressions)}")
            print(f"  Post-compression rounds: {len(post_compression)}")
            if overflows:
                print(f"  Overflows (pre > 1.3x budget): {len(overflows)}")
                for e in overflows[:5]:
                    print(f"    Round {e['round']}: pre={e['original_tokens']}")

            assert len(overflows) == 0, (
                f"Bug 3: {len(overflows)} rounds where pre-compression size "
                f"exceeded {max_allowed:.0f} (1.3x budget={budget}). "
                f"Without persist-back, pre-compression sizes grow without "
                f"limit. Overflow sizes: "
                f"{[e['original_tokens'] for e in overflows]}"
            )

    def test_compression_ratio_degrades_with_large_tool_outputs(self):
        """Verify ratio degradation when tool outputs keep growing.

        As more tool call groups are preserved (they're newest and kept),
        the compressor has fewer old messages to drop, so ratio worsens.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()
        strategy.PRECISE_ESTIMATION_LOWER_RATIO = 0
        strategy.PRECISE_ESTIMATION_UPPER_RATIO = 0

        # Use smaller budget to trigger more compressions with less content
        tight_constraints = ContextConstraints(
            max_input_tokens=40000,
            reserve_output_tokens=8000,
            preserve_system=True,
        )

        base_msgs_data = []
        base_msgs_data.append({"role": MessageRole.SYSTEM, "content": _build_system_prompt()})
        base_msgs_data.append({"role": MessageRole.USER, "content": "帮我修复"})

        scratchpad_msgs_data = []
        ratios = []

        for round_num in range(15):
            # Reassemble from buckets
            msgs = Messages()
            for m in base_msgs_data:
                msgs.add_message(role=m["role"], content=m["content"])
            for m in scratchpad_msgs_data:
                kwargs = {"role": m["role"], "content": m["content"]}
                if "tool_calls" in m:
                    kwargs["tool_calls"] = m["tool_calls"]
                if "tool_call_id" in m:
                    kwargs["tool_call_id"] = m["tool_call_id"]
                msgs.add_message(**kwargs)

            result = strategy.compress(
                context=ctx, constraints=tight_constraints, messages=msgs,
            )
            if result.compression_ratio < 1.0:
                ratios.append(result.compression_ratio)

            # Add round content
            tool_id = f"call_{round_num}"
            output_size = 12322 if round_num % 4 == 0 else 1000
            scratchpad_msgs_data.append({
                "role": MessageRole.ASSISTANT, "content": "",
                "tool_calls": [{"id": tool_id, "function": {"name": "_bash", "arguments": "{}"}}],
            })
            scratchpad_msgs_data.append({
                "role": MessageRole.TOOL, "content": _make_filler(output_size, seed=f"ratio_tool_{round_num}"),
                "tool_call_id": tool_id,
            })

        if len(ratios) >= 4:
            avg_early = sum(ratios[:len(ratios)//2]) / (len(ratios)//2)
            avg_late = sum(ratios[len(ratios)//2:]) / (len(ratios) - len(ratios)//2)
            print(f"\n  Compression events: {len(ratios)}")
            print(f"  Early avg ratio: {avg_early:.3f}")
            print(f"  Late avg ratio:  {avg_late:.3f}")
            print(f"  All ratios: {[f'{r:.3f}' for r in ratios]}")

    def test_repeated_large_file_reads_dominate_context(self):
        """Reproduce: same file (factory.py, 12322 chars) read 5 times.

        In production, the agent read factory.py 5 times during the fix turn.
        Each read adds 12K chars. With tool_call overhead, 5 reads = ~70K chars
        just for redundant file content.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = Messages()
        msgs.add_message(role=MessageRole.SYSTEM, content=_build_system_prompt())
        msgs.add_message(role=MessageRole.USER, content="帮我修复")

        # Simulate 5 read_file calls returning the same content
        file_content = _make_filler(12322, seed="factory_py")  # factory.py size
        for i in range(5):
            tool_id = f"call_read_{i}"
            msgs.add_message(
                role=MessageRole.ASSISTANT, content="",
                tool_calls=[{"id": tool_id, "function": {"name": "_read_file", "arguments": "{}"}}],
            )
            msgs.add_message(
                role=MessageRole.TOOL, content=file_content,
                tool_call_id=tool_id,
            )

        # The 5 reads alone should be 5 * 12322 = 61610 chars
        total_tool_content = sum(
            len(m.content) for m in msgs if m.role == MessageRole.TOOL
        )
        assert total_tool_content == 5 * 12322

        result = strategy.compress(
            context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
        )

        # With 128K budget and ~61K just in tool outputs, compression
        # should be needed or close to budget
        print(f"\n  Total tool content: {total_tool_content} chars")
        print(f"  Original tokens: {result.original_token_count}")
        print(f"  Compressed tokens: {result.compressed_token_count}")
        print(f"  Ratio: {result.compression_ratio:.3f}")


# ---------------------------------------------------------------------------
# Structural integrity after compression
# ---------------------------------------------------------------------------

class TestStructuralIntegrity:
    """Verify tool_call/tool pairing and message ordering after compression
    in the production-like scenario."""

    def test_tool_pairing_preserved_in_full_session(self):
        """Full session compression must preserve tool_call/tool pairing."""
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_full_session_messages()
        result = strategy.compress(
            context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
        )

        # Validate pairing
        valid_tool_call_ids = set()
        for m in result.compressed_messages:
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                for tc in m.tool_calls:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        valid_tool_call_ids.add(tc_id)

            if m.role == MessageRole.TOOL:
                assert m.tool_call_id in valid_tool_call_ids, (
                    f"Orphan tool message: tool_call_id={m.tool_call_id} "
                    f"has no matching assistant tool_calls. "
                    f"Valid IDs: {valid_tool_call_ids}"
                )

    def test_tool_pairing_preserved_mid_turn(self):
        """Mid-turn compression must preserve tool_call/tool pairing."""
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=20)
        result = strategy.compress(
            context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
        )

        valid_tool_call_ids = set()
        for m in result.compressed_messages:
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                for tc in m.tool_calls:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        valid_tool_call_ids.add(tc_id)

            if m.role == MessageRole.TOOL:
                assert m.tool_call_id in valid_tool_call_ids, (
                    f"Orphan tool message: tool_call_id={m.tool_call_id}"
                )

    def test_message_order_preserved(self):
        """After compression, messages must maintain chronological order.

        Specifically: system → first_user → [history...] → current_user → [tool calls...]
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=5)

        # Force compression
        tight_constraints = ContextConstraints(
            max_input_tokens=40000,
            reserve_output_tokens=8000,
            preserve_system=True,
        )

        result = strategy.compress(
            context=ctx, constraints=tight_constraints, messages=msgs,
        )

        roles = [m.role for m in result.compressed_messages]

        # First message should be system
        assert roles[0] == MessageRole.SYSTEM

        # First non-system should be user
        first_non_system = next(r for r in roles if r != MessageRole.SYSTEM)
        assert first_non_system == MessageRole.USER, (
            f"First non-system message should be USER, got {first_non_system.value}"
        )

    def test_first_user_message_always_preserved(self):
        """The first user message must always be preserved (GLM API requirement)."""
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=20)

        tight_constraints = ContextConstraints(
            max_input_tokens=20000,
            reserve_output_tokens=4000,
            preserve_system=True,
        )

        result = strategy.compress(
            context=ctx, constraints=tight_constraints, messages=msgs,
        )

        non_system = [m for m in result.compressed_messages if m.role != MessageRole.SYSTEM]
        assert len(non_system) > 0, "Must have non-system messages"
        assert non_system[0].role == MessageRole.USER, (
            f"First non-system must be USER, got {non_system[0].role.value}"
        )


# ---------------------------------------------------------------------------
# Simulation: multi-round compression like production
# ---------------------------------------------------------------------------

class TestMultiRoundCompression:
    """Simulate the exact production pattern: repeated compress → add → compress."""

    def test_simulate_production_compression_cascade(self):
        """Simulate the 22-compression cascade observed in production.

        Uses the bucket-reassembly pattern (each round rebuilds from
        uncompressed base + growing scratchpad) to reproduce the exact
        production behavior where pre-compression size grows monotonically.

        Production data:
        - 21 rounds, all with pre-compression size > previous
        - 147K → 259K pre-compression tokens
        - Post-compression "越压越大": 14/20 rounds had larger output
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()
        # Disable precise counting (see test_bucket_reassembly for explanation)
        strategy.PRECISE_ESTIMATION_LOWER_RATIO = 0
        strategy.PRECISE_ESTIMATION_UPPER_RATIO = 0

        # Base messages (SYSTEM + HISTORY + QUERY buckets — never modified)
        base_msgs_data = []
        base_msgs_data.append({
            "role": MessageRole.SYSTEM, "content": _build_system_prompt(),
        })
        for m in _build_prior_history():
            base_msgs_data.append(m)
        base_msgs_data.append({
            "role": MessageRole.USER, "content": "帮我修复",
        })

        # SCRATCHPAD: grows each round, never compressed
        scratchpad_msgs_data = []

        compression_log = []

        tool_sizes = [
            989, 12322, 88, 3324, 1084, 23, 105, 12322, 69, 152,
            192, 77, 990, 1101, 1096, 1096, 3038, 11, 12322, 11,
        ]

        for round_num in range(20):
            # === Reassemble from buckets (production pattern) ===
            msgs = Messages()
            for m in base_msgs_data:
                kwargs = {"role": m["role"], "content": m["content"]}
                if "tool_calls" in m:
                    kwargs["tool_calls"] = m["tool_calls"]
                if "tool_call_id" in m:
                    kwargs["tool_call_id"] = m["tool_call_id"]
                msgs.add_message(**kwargs)
            for m in scratchpad_msgs_data:
                kwargs = {"role": m["role"], "content": m["content"]}
                if "tool_calls" in m:
                    kwargs["tool_calls"] = m["tool_calls"]
                if "tool_call_id" in m:
                    kwargs["tool_call_id"] = m["tool_call_id"]
                msgs.add_message(**kwargs)

            # === Compress (for LLM API call) ===
            result = strategy.compress(
                context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
            )

            compression_log.append({
                "round": round_num,
                "original_tokens": result.original_token_count,
                "compressed_tokens": result.compressed_token_count,
                "ratio": result.compression_ratio,
                "message_count": len(msgs),
            })

            # === Add new tool call to SCRATCHPAD (never compressed) ===
            tool_id = f"call_sim_{round_num}"
            output_size = tool_sizes[round_num] if round_num < len(tool_sizes) else 500

            scratchpad_msgs_data.append({
                "role": MessageRole.ASSISTANT, "content": "",
                "tool_calls": [{"id": tool_id, "function": {"name": "_bash", "arguments": "{}"}}],
            })
            scratchpad_msgs_data.append({
                "role": MessageRole.TOOL, "content": _make_filler(output_size, seed=f"sim_tool_{round_num}"),
                "tool_call_id": tool_id,
            })

        compressions = [e for e in compression_log if e["ratio"] < 1.0]
        print(f"\n  Simulated {len(compression_log)} rounds")
        print(f"  Compression events: {len(compressions)}")
        if compressions:
            print(f"  First compression at round {compressions[0]['round']}")
            print(f"  Worst ratio: {min(c['ratio'] for c in compressions):.3f}")

            # Check "越压越大" pattern
            post_sizes = [e["compressed_tokens"] for e in compressions]
            grow_count = sum(
                1 for i in range(1, len(post_sizes))
                if post_sizes[i] > post_sizes[i-1]
            )
            print(f"  Post-compression growth (越压越大): {grow_count}/{len(compressions)-1}")

        # Verify user query survived all compressions
        # Re-assemble final round to check
        final_msgs = Messages()
        for m in base_msgs_data:
            kwargs = {"role": m["role"], "content": m["content"]}
            if "tool_calls" in m:
                kwargs["tool_calls"] = m["tool_calls"]
            if "tool_call_id" in m:
                kwargs["tool_call_id"] = m["tool_call_id"]
            final_msgs.add_message(**kwargs)
        for m in scratchpad_msgs_data:
            kwargs = {"role": m["role"], "content": m["content"]}
            if "tool_calls" in m:
                kwargs["tool_calls"] = m["tool_calls"]
            if "tool_call_id" in m:
                kwargs["tool_call_id"] = m["tool_call_id"]
            final_msgs.add_message(**kwargs)

        final_result = strategy.compress(
            context=ctx, constraints=PROD_CONSTRAINTS, messages=final_msgs,
        )
        final_user_messages = [
            m for m in final_result.compressed_messages
            if m.role == MessageRole.USER
        ]
        query_survived = any("帮我修复" in (m.content or "") for m in final_user_messages)

        if not query_survived:
            pytest.xfail(
                "Known bug: user query '帮我修复' was lost after "
                f"{len(compressions)} compression rounds. "
                "The latest_user_message preservation logic fails when "
                "the user message is not the last non-system message."
            )

    def test_all_compressions_produce_valid_messages(self):
        """Every compression round must produce structurally valid messages.

        No orphan tool messages, no broken tool_call pairing.
        """
        ctx = create_test_context()
        strategy = TruncationStrategy()

        msgs = _build_mid_turn_messages(num_completed_rounds=5)

        for round_num in range(10):
            result = strategy.compress(
                context=ctx, constraints=PROD_CONSTRAINTS, messages=msgs,
            )
            msgs = result.compressed_messages

            # Validate structure after each compression
            valid_ids = set()
            for m in msgs:
                if m.role == MessageRole.ASSISTANT and m.tool_calls:
                    for tc in m.tool_calls:
                        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                        if tc_id:
                            valid_ids.add(tc_id)
                if m.role == MessageRole.TOOL:
                    assert m.tool_call_id in valid_ids, (
                        f"Round {round_num}: orphan tool message "
                        f"tool_call_id={m.tool_call_id}"
                    )

            # Add next round
            tool_id = f"call_val_{round_num}"
            msgs.add_message(
                role=MessageRole.ASSISTANT, content="",
                tool_calls=[{"id": tool_id, "function": {"name": "_bash", "arguments": "{}"}}],
            )
            msgs.add_message(
                role=MessageRole.TOOL, content=_make_filler(5000, seed=f"val_tool_{round_num}"),
                tool_call_id=tool_id,
            )


# ---------------------------------------------------------------------------
# Bug 4: Single-user session loses scratchpad after compression persist-back
# ---------------------------------------------------------------------------

class TestSingleUserSessionPersistBack:
    """Tests for the single-user session bug in _persist_compressed_history().

    When a session has only ONE user message (first_user == latest_user),
    TruncationStrategy.preparation() does NOT duplicate the user message
    into latest_user_message. After compression the non-system layout is:

        [user(idx=0)] [assistant/tool_1] [assistant/tool_2] ...

    _persist_compressed_history() searches backwards for the latest user
    message, finds it at idx=0, then:
        history = non_system[:0]  → empty
        SCRATCHPAD → cleared

    Result: the surviving assistant/tool messages (idx 1..N) are persisted
    to NEITHER history NOR scratchpad. Next round's assembly
    (SYSTEM + HISTORY + QUERY + SCRATCHPAD) loses all tool execution context.
    """

    def _setup_single_user_session(self, num_tool_rounds: int = 5):
        """Set up a single-user session with context_manager buckets.

        Returns (compressor, context) with buckets configured as:
        - SYSTEM: system prompt
        - HISTORY: empty (no prior conversation)
        - QUERY: the single user message
        - SCRATCHPAD: assistant+tool messages from agentic loop
        """
        from dolphin.core.message.compressor import MessageCompressor
        from dolphin.core.config.global_config import ContextEngineerConfig
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        ctx = create_test_context()
        ce_config = ContextEngineerConfig(
            default_strategy="truncation",
            constraints=ContextConstraints(
                max_input_tokens=20000,
                reserve_output_tokens=4000,
                preserve_system=True,
            ),
        )
        compressor = MessageCompressor(config=ce_config, context=ctx)
        for s in compressor.strategies.values():
            s.PRECISE_ESTIMATION_LOWER_RATIO = 0
            s.PRECISE_ESTIMATION_UPPER_RATIO = 0

        # SYSTEM bucket
        sys_msgs = Messages()
        sys_msgs.add_message(role=MessageRole.SYSTEM, content=_build_system_prompt(2000))
        ctx.context_manager.add_bucket(BuildInBucket.SYSTEM.value, sys_msgs)

        # HISTORY bucket (empty — no prior conversation)
        hist_msgs = Messages()
        ctx.context_manager.add_bucket(BuildInBucket.HISTORY.value, hist_msgs)

        # QUERY bucket (the only user message)
        query_msgs = Messages()
        query_msgs.add_message(role=MessageRole.USER, content="帮我修复这个 bug")
        ctx.context_manager.add_bucket(BuildInBucket.QUERY.value, query_msgs)

        # SCRATCHPAD bucket (tool calls from the agentic loop)
        scratch_msgs = Messages()
        for i in range(num_tool_rounds):
            tid = f"call_single_{i}"
            scratch_msgs.add_message(
                role=MessageRole.ASSISTANT, content="",
                tool_calls=[{"id": tid, "function": {"name": "_bash", "arguments": "{}"}}],
            )
            scratch_msgs.add_message(
                role=MessageRole.TOOL,
                content=_make_filler(3000, seed=f"single_tool_{i}"),
                tool_call_id=tid,
            )
        ctx.context_manager.add_bucket(BuildInBucket.SCRATCHPAD.value, scratch_msgs)

        return compressor, ctx

    def test_single_user_persist_back_preserves_tool_context(self):
        """After compression in a single-user session, the next round must
        still have access to surviving tool execution history.

        Bug: _persist_compressed_history sets history=non_system[:0]=empty
        and clears SCRATCHPAD, so ALL assistant/tool context is lost.
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        compressor, ctx = self._setup_single_user_session(num_tool_rounds=8)

        # Assemble and compress (triggers _persist_compressed_history)
        msgs = ctx.context_manager.to_dph_messages()
        pre_compress_count = len([
            m for m in msgs
            if m.role in (MessageRole.ASSISTANT, MessageRole.TOOL)
        ])
        assert pre_compress_count > 0, "Should have tool messages before compression"

        result = compressor.compress_messages(msgs)
        assert result.compression_ratio < 1.0, (
            "Expected compression to trigger (ratio < 1.0) to test persist-back"
        )

        # Re-assemble from buckets (simulating next agentic loop round)
        next_round_msgs = ctx.context_manager.to_dph_messages()

        # Count surviving assistant/tool messages
        next_round_tool_msgs = [
            m for m in next_round_msgs
            if m.role in (MessageRole.ASSISTANT, MessageRole.TOOL)
        ]

        assert len(next_round_tool_msgs) > 0, (
            "Bug: All assistant/tool context lost after compression persist-back "
            "in single-user session. _persist_compressed_history() sets "
            "history=non_system[:0]=empty and clears SCRATCHPAD, losing all "
            "surviving tool execution history. Next agentic loop round has "
            "no context of what tools were already executed."
        )

    def test_single_user_multi_compression_retains_context(self):
        """Multiple compression rounds in a single-user session should not
        progressively lose all context.

        Without the fix, first compression clears SCRATCHPAD and writes
        nothing to HISTORY, so the initial tool history is entirely lost.
        Subsequent rounds only see newly added messages, not the original ones.
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        compressor, ctx = self._setup_single_user_session(num_tool_rounds=8)

        # Record initial tool call IDs for tracking
        initial_tool_ids = set()
        scratch_bucket = ctx.context_manager.state.buckets.get(
            BuildInBucket.SCRATCHPAD.value
        )
        for m in scratch_bucket.content:
            if m.role == MessageRole.TOOL and m.tool_call_id:
                initial_tool_ids.add(m.tool_call_id)
        assert len(initial_tool_ids) == 8

        # First compression — this is where the bug bites
        msgs = ctx.context_manager.to_dph_messages()
        result = compressor.compress_messages(msgs)
        assert result.compression_ratio < 1.0, "Must trigger compression"

        # Re-assemble and check how many initial tool calls survived
        round1_msgs = ctx.context_manager.to_dph_messages()
        surviving_initial = [
            m for m in round1_msgs
            if m.role == MessageRole.TOOL and m.tool_call_id in initial_tool_ids
        ]

        assert len(surviving_initial) > 0, (
            "Bug: After first compression in single-user session, ALL initial "
            "tool execution history is lost. _persist_compressed_history() "
            "writes history=non_system[:0]=empty and clears SCRATCHPAD. "
            f"Expected some of {len(initial_tool_ids)} tool calls to survive, "
            "got 0."
        )
