#!/usr/bin/env python3
"""
Unit tests for LLM duplicate output detection logic.

Tests the duplicate pattern detection algorithm used in LLMClient.stream_generate_with_compression
to ensure it correctly identifies repetitive patterns (overlapping matches) in streaming responses.

Key requirement: Must support overlapping matches to avoid false positives with legitimate
repeated content (e.g., 10 SVG cards with identical CSS).
"""

import unittest
import time
import re

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


class TestDuplicateDetectionAlgorithm(unittest.TestCase):
    """
    Test the duplicate detection algorithm with OVERLAPPING match semantics.

    Critical: The algorithm must use overlapping matches to accurately detect
    loops while avoiding false positives on legitimate repeated CSS/templates.
    """

    def test_regex_vs_loop_correctness(self):
        """Verify that regex lookahead gives identical results to the original loop."""
        # Test pattern
        pattern = "X" * 50

        # Test various texts
        test_cases = [
            ("X" * 1000, "all same char"),
            ("ABCD" * 250, "repeating sequence"),
            ("X" * 50 + "Y" * 50 + "X" * 50, "pattern with gap"),
            ("unique content here" * 50, "unique repeated text"),
        ]

        for text, description in test_cases:
            with self.subTest(case=description):
                recent = text[-50:]
                previous = text[:-50]

                count_loop = count_overlapping_loop(previous, recent)
                count_regex = count_overlapping_regex(previous, recent)

                self.assertEqual(count_loop, count_regex,
                    f"{description}: regex must match loop (got {count_regex} vs {count_loop})")

    def test_svg_cards_scenario(self):
        """
        Test the real-world scenario: 10 SVG cards with identical CSS.

        This should NOT trigger false positive if CSS appears ~10 times.
        Should ONLY trigger if the entire card repeats 100+ times (infinite loop).
        """
        # Simulate a typical SVG card (avoid format() conflicts)
        css_block = "<style>.card{width:100%;padding:20px;background:#fff;}</style>"

        # Generate 10 legitimate cards with unique data
        cards = []
        for i in range(10):
            card = css_block + f"<content>Data for card {i}</content>\n"
            cards.append(card)
        legitimate_output = "".join(cards)

        # Check if CSS block appears in output
        recent = css_block[:50]  # First 50 chars of CSS
        previous = legitimate_output

        count = count_overlapping_regex(previous, recent)

        # CSS appears ~10 times (once per card) - should NOT trigger (threshold=100)
        self.assertLess(count, 100,
            f"Legitimate 10 cards should not trigger detection (got {count} matches)")
        self.assertGreaterEqual(count, 8,
            f"CSS should appear ~10 times in 10 cards (got {count})")

    def test_infinite_loop_detection(self):
        """
        Test detection of infinite loop: same card repeated 150+ times.

        This SHOULD trigger detection (count > 100).
        """
        # Simulate infinite loop: same card repeated
        card = "<style>.card{padding:20px;}</style><content>Same card</content>\n"
        infinite_output = card * 150  # Repeated 150 times

        recent = card[:50]
        previous = infinite_output

        count = count_overlapping_regex(previous, recent)

        # Should detect massive repetition
        self.assertGreater(count, 100,
            f"Infinite loop should trigger detection (got {count} matches, threshold=100)")

    def test_performance_comparison(self):
        """Verify regex lookahead is significantly faster than loop."""
        pattern = "test_pattern_" + "x" * 37  # 50 chars total
        large_text = pattern * 1300  # 65,000 chars (65KB)

        recent = large_text[-50:]
        previous = large_text[:-50]

        # Benchmark regex
        start = time.perf_counter()
        for _ in range(10):
            count_fast = count_overlapping_regex(previous, recent)
        time_fast = (time.perf_counter() - start) / 10

        # Benchmark loop (fewer iterations as it's slower)
        start = time.perf_counter()
        for _ in range(2):
            count_slow = count_overlapping_loop(previous, recent)
        time_slow = (time.perf_counter() - start) / 2

        # Results must match
        self.assertEqual(count_fast, count_slow)

        # Speed comparison
        speedup = time_slow / time_fast if time_fast > 0 else float('inf')

        print(f"\n  Performance on 65KB text (pattern matches={count_fast}):")
        print(f"    Regex lookahead: {time_fast*1000:.3f}ms")
        print(f"    Original loop:   {time_slow*1000:.3f}ms")
        print(f"    Speedup:         {speedup:.1f}x")

        # Regex should be at least 3x faster (conservative threshold)
        self.assertGreater(speedup, 3,
            f"Regex should be >3x faster than loop, got {speedup:.1f}x")

    def test_edge_case_all_same_char(self):
        """Test worst case: all same character (maximum overlapping matches)."""
        all_x = "X" * 10000
        pattern = "X" * 50

        recent = all_x[-50:]
        previous = all_x[:-50]

        count_loop = count_overlapping_loop(previous, pattern)
        count_regex = count_overlapping_regex(previous, pattern)

        # Both should give same result
        self.assertEqual(count_loop, count_regex)

        # Expected: len(previous) - len(pattern) + 1 = 9950 - 50 + 1 = 9901
        expected = len(previous) - len(pattern) + 1
        self.assertEqual(count_regex, expected,
            f"Expected {expected} overlapping matches, got {count_regex}")

    def test_no_false_positives_unique_content(self):
        """Ensure unique content doesn't trigger false positives."""
        # Generate truly unique content (no 50-char repetitions)
        unique_lines = [
            f"Line {i:05d}: unique content with random data {i*12345} and more text here\n"
            for i in range(100)  # Generate enough to exceed MIN_LENGTH threshold
        ]
        unique_content = "".join(unique_lines)

        # Ensure it's long enough to be checked
        self.assertGreater(len(unique_content), MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT)

        recent = unique_content[-50:]
        previous = unique_content[:-50]
        count = count_overlapping_occurrences(previous, recent)

        # Should find 0 or 1 match (the last 50 chars may appear once earlier if unlucky)
        self.assertLessEqual(count, 1,
            f"Unique content should have ≤1 match, got {count}")

    def test_threshold_values(self):
        """Test that threshold constants are reasonable for SVG use cases."""
        # MIN_LENGTH should be positive and reasonable
        self.assertGreater(MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT, 0)
        self.assertGreaterEqual(MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT, 1024,
            "Minimum length should be >= 1KB for early detection")
        self.assertLessEqual(MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT, 8192,
            "Minimum length should be <= 8KB to catch loops early")
        
        # COUNT should allow legitimate repetitions but catch loops
        # 30 SVG cards with same CSS = 30 repetitions, so threshold should be > 30
        self.assertGreater(COUNT_TO_PROVE_DUPLICATE_OUTPUT, 30,
            "Count threshold should be > 30 to allow 30 SVG cards")
        self.assertLessEqual(COUNT_TO_PROVE_DUPLICATE_OUTPUT, 100,
            "Count threshold should be <= 100 to catch loops reasonably")


    def test_get_msg_duplicate_output(self):
        """Test that duplicate output message generator works."""
        msg = get_msg_duplicate_output()

        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 5, "Message should be meaningful")

        # Should return different messages (randomized)
        messages = [get_msg_duplicate_output() for _ in range(20)]
        unique_messages = set(messages)

        self.assertGreater(len(unique_messages), 1,
            "Should have multiple message variants")


class TestWindowedDetection(unittest.TestCase):
    """Test the windowed detection optimization strategy (optional)."""

    def test_32kb_window_sufficient_for_svg_cards(self):
        """
        Test that 32KB window is sufficient to detect loops in SVG card generation.

        Assumption: Each SVG card is ~3-5KB, so 32KB window covers 6-10 cards.
        """
        WINDOW_SIZE = 32768  # 32KB

        # Simulate 20 SVG cards (only last 10 fit in window)
        card_size = 3000  # 3KB per card
        card_template = "X" * 50 + "Y" * (card_size - 50)  # 50-char pattern at start

        huge_content = card_template * 20  # 60KB total

        # Full content detection
        recent_full = huge_content[-50:]
        previous_full = huge_content[:-50]
        count_full = count_overlapping_regex(previous_full, recent_full)

        # Windowed detection (last 32KB only)
        check_window = huge_content[-WINDOW_SIZE:]
        recent_window = check_window[-50:]
        previous_window = check_window[:-50]
        count_window = count_overlapping_regex(previous_window, recent_window)

        # Both should detect the pattern
        self.assertGreater(count_full, 15, "Full scan should find ~19 cards")
        self.assertGreater(count_window, 8, "Window should find ~10 cards")

        # If full count exceeds threshold, window should too
        THRESHOLD = 100
        if count_full < THRESHOLD:
            # This is the legitimate case - shouldn't trigger in either mode
            self.assertLess(count_window, THRESHOLD)


class TestRealWorldScenarios(unittest.TestCase):
    """Test real-world edge cases."""

    def test_mixed_content_with_templates(self):
        """Test content mixing unique data with repeated templates."""
        template = "<div class='item' style='padding:10px;'>"  # ~40 chars

        # Generate mixed content: template + unique data
        content_parts = []
        for i in range(50):
            content_parts.append(template)
            content_parts.append(f"<span>Item {i}: Unique data {i*999}</span></div>\n")

        mixed_content = "".join(content_parts)

        recent = template[:50] if len(template) >= 50 else template
        previous = mixed_content

        count = count_overlapping_regex(previous, recent)

        # Template appears ~50 times, but that's legitimate
        self.assertLess(count, 100,
            "Legitimate template usage should not trigger (threshold=100)")

    def test_escape_special_regex_chars(self):
        """Test that special regex characters in content are properly escaped."""
        # Content with regex special chars
        pattern_with_specials = "style='width:100%;' class='item[0]'"
        text = pattern_with_specials * 50

        recent = pattern_with_specials
        previous = text

        # Should not crash due to unescaped regex chars
        count = count_overlapping_regex(previous, recent)

        # Should count correctly (49 non-overlapping in text of 50 repetitions)
        self.assertGreaterEqual(count, 49, "Should handle regex special chars correctly")


if __name__ == "__main__":
    # Run with verbose output to see performance numbers
    unittest.main(verbosity=2)
