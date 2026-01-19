#!/usr/bin/env python3
"""
Unit tests for LLM duplicate output detection logic.

Tests the duplicate pattern detection algorithm used in LLMClient.stream_generate_with_compression
to ensure it correctly identifies repetitive patterns (overlapping matches) in streaming responses.

Key requirement: Must support overlapping matches to avoid false positives with legitimate
repeated content (e.g., 10 SVG cards with identical CSS).
"""

import time

import pytest

from dolphin.core.common.constants import (
    COUNT_TO_PROVE_DUPLICATE_OUTPUT,
    MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT,
    count_overlapping_occurrences,
    get_msg_duplicate_output,
)

# Alias the centralized function for test compatibility
count_overlapping_regex = count_overlapping_occurrences


def count_overlapping_loop(text, pattern):
    """Original O(n²) loop-based counting (for comparison)."""
    return sum(
        1
        for i in range(len(text) - len(pattern) + 1)
        if text[i : i + len(pattern)] == pattern
    )


@pytest.mark.parametrize(
    ("text", "description"),
    [
        ("X" * 1000, "all same char"),
        ("ABCD" * 250, "repeating sequence"),
        ("X" * 50 + "Y" * 50 + "X" * 50, "pattern with gap"),
        ("unique content here" * 50, "unique repeated text"),
    ],
)
def test_regex_vs_loop_correctness(text, description):
    """
    Verify that regex lookahead gives identical results to the original loop.
    """
    recent = text[-50:]
    previous = text[:-50]

    count_loop = count_overlapping_loop(previous, recent)
    count_regex = count_overlapping_regex(previous, recent)

    assert (
        count_loop == count_regex
    ), f"{description}: regex must match loop (got {count_regex} vs {count_loop})"


def test_svg_cards_scenario():
    """
    Test the real-world scenario: 10 SVG cards with identical CSS.

    This should NOT trigger false positive if CSS appears ~10 times.
    Should ONLY trigger if the entire card repeats 100+ times (infinite loop).
    """
    css_block = "<style>.card{width:100%;padding:20px;background:#fff;}</style>"

    cards = []
    for i in range(10):
        cards.append(css_block + f"<content>Data for card {i}</content>\n")
    legitimate_output = "".join(cards)

    recent = css_block[:50]
    previous = legitimate_output

    count = count_overlapping_regex(previous, recent)

    assert count < 100, f"Legitimate 10 cards should not trigger detection (got {count} matches)"
    assert count >= 8, f"CSS should appear ~10 times in 10 cards (got {count})"


def test_infinite_loop_detection():
    """
    Test detection of infinite loop: same card repeated 150+ times.

    This SHOULD trigger detection (count > 100).
    """
    card = "<style>.card{padding:20px;}</style><content>Same card</content>\n"
    infinite_output = card * 150

    recent = card[:50]
    previous = infinite_output

    count = count_overlapping_regex(previous, recent)

    assert count > 100, f"Infinite loop should trigger detection (got {count} matches, threshold=100)"


def test_performance_comparison():
    """Verify regex lookahead is significantly faster than loop."""
    pattern = "test_pattern_" + "x" * 37  # 50 chars total
    large_text = pattern * 1300  # 65,000 chars (65KB)

    recent = large_text[-50:]
    previous = large_text[:-50]

    start = time.perf_counter()
    for _ in range(10):
        count_fast = count_overlapping_regex(previous, recent)
    time_fast = (time.perf_counter() - start) / 10

    start = time.perf_counter()
    for _ in range(2):
        count_slow = count_overlapping_loop(previous, recent)
    time_slow = (time.perf_counter() - start) / 2

    assert count_fast == count_slow

    speedup = time_slow / time_fast if time_fast > 0 else float("inf")

    print(f"\n  Performance on 65KB text (pattern matches={count_fast}):")
    print(f"    Regex lookahead: {time_fast*1000:.3f}ms")
    print(f"    Original loop:   {time_slow*1000:.3f}ms")
    print(f"    Speedup:         {speedup:.1f}x")

    assert speedup > 3, f"Regex should be >3x faster than loop, got {speedup:.1f}x"


def test_edge_case_all_same_char():
    """Test worst case: all same character (maximum overlapping matches)."""
    all_x = "X" * 10000
    pattern = "X" * 50

    recent = all_x[-50:]
    previous = all_x[:-50]

    count_loop = count_overlapping_loop(previous, pattern)
    count_regex = count_overlapping_regex(previous, pattern)

    assert count_loop == count_regex

    expected = len(previous) - len(pattern) + 1
    assert count_regex == expected, f"Expected {expected} overlapping matches, got {count_regex}"


def test_no_false_positives_unique_content():
    """Ensure unique content doesn't trigger false positives."""
    prefix = "A" * (MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT + 200)
    recent = "ENDTOKEN-" + ("0123456789" * 4) + "X"  # 50 chars total
    assert len(recent) == 50

    unique_content = prefix + recent
    assert len(unique_content) > MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT

    previous = unique_content[:-50]
    count = count_overlapping_occurrences(previous, recent)

    assert count == 0, f"Unique content should have 0 match, got {count}"


def test_threshold_values():
    """Test that threshold constants are reasonable for SVG use cases."""
    assert MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT > 0
    assert MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT >= 1024, "Minimum length should be >= 1KB for early detection"
    assert MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT <= 8192, "Minimum length should be <= 8KB to catch loops early"

    assert COUNT_TO_PROVE_DUPLICATE_OUTPUT > 30, "Count threshold should be > 30 to allow 30 SVG cards"
    assert COUNT_TO_PROVE_DUPLICATE_OUTPUT <= 100, "Count threshold should be <= 100 to catch loops reasonably"


def test_get_msg_duplicate_output():
    """Test that duplicate output message generator works."""
    msg = get_msg_duplicate_output()

    assert isinstance(msg, str)
    assert len(msg) > 5, "Message should be meaningful"

    messages = [get_msg_duplicate_output() for _ in range(20)]
    unique_messages = set(messages)

    assert len(unique_messages) > 1, "Should have multiple message variants"


def test_32kb_window_sufficient_for_svg_cards():
    """
    Test that 32KB window is sufficient to detect loops in SVG card generation.

    Assumption: Each SVG card is ~3-5KB, so 32KB window covers 6-10 cards.
    """
    WINDOW_SIZE = 32768  # 32KB

    card_size = 3000  # 3KB per card
    card_template = "X" * 50 + "Y" * (card_size - 50)
    huge_content = card_template * 20  # 60KB total

    recent_full = huge_content[-50:]
    previous_full = huge_content[:-50]
    count_full = count_overlapping_regex(previous_full, recent_full)

    check_window = huge_content[-WINDOW_SIZE:]
    recent_window = check_window[-50:]
    previous_window = check_window[:-50]
    count_window = count_overlapping_regex(previous_window, recent_window)

    assert count_full > 15, "Full scan should find ~19 cards"
    assert count_window > 8, "Window should find ~10 cards"

    THRESHOLD = 100
    if count_full < THRESHOLD:
        assert count_window < THRESHOLD


def test_mixed_content_with_templates():
    """Test content mixing unique data with repeated templates."""
    template = "<div class='item' style='padding:10px;'>"

    content_parts = []
    for i in range(50):
        content_parts.append(template)
        content_parts.append(f"<span>Item {i}: Unique data {i*999}</span></div>\n")

    mixed_content = "".join(content_parts)

    recent = template[:50] if len(template) >= 50 else template
    previous = mixed_content

    count = count_overlapping_regex(previous, recent)

    assert count < 100, "Legitimate template usage should not trigger (threshold=100)"


def test_escape_special_regex_chars():
    """Test that special regex characters in content are properly escaped."""
    pattern_with_specials = "style='width:100%;' class='item[0]'"
    text = pattern_with_specials * 50

    recent = pattern_with_specials
    previous = text

    count = count_overlapping_regex(previous, recent)

    assert count >= 49, "Should handle regex special chars correctly"
