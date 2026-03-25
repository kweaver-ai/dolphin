"""Unit tests for strip_think_tags utility function."""

import pytest

from dolphin.core.utils.tools import strip_think_tags


class TestStripThinkTagsBasic:
    def test_no_tags_returns_unchanged(self):
        assert strip_think_tags("hello world") == "hello world"

    def test_single_think_block_removed(self):
        assert strip_think_tags("<think>reasoning</think>result") == "result"

    def test_multiple_think_blocks_all_removed(self):
        val = "<think>first</think>middle<think>second</think>end"
        assert strip_think_tags(val) == "middleend"

    def test_multiline_chinese_content_removed(self):
        val = "<think>这是推理过程，包含全角标点\n第二行，还有更多</think>'actual_value'"
        assert strip_think_tags(val) == "'actual_value'"

    def test_leading_trailing_whitespace_stripped_when_tags_present(self):
        # When think tags ARE present, surrounding whitespace is stripped too.
        assert strip_think_tags("  <think>x</think>  value  ") == "value"

    def test_whitespace_preserved_when_no_tags(self):
        # When no think tags exist, whitespace must NOT be altered.
        # strip_think_tags purpose is tag removal, not whitespace normalisation.
        assert strip_think_tags("  hello world  ") == "  hello world  "

    def test_empty_string_returns_empty(self):
        assert strip_think_tags("") == ""

    def test_think_tags_only_returns_empty(self):
        assert strip_think_tags("<think>everything is here</think>") == ""

    def test_think_tag_with_chinese_full_width_comma(self):
        # This is the exact production scenario from the bug report
        val = "<think>推理过程，包含全角逗号</think>actual_value"
        assert strip_think_tags(val) == "actual_value"


class TestStripThinkTagsNonStringPassthrough:
    def test_int_returned_unchanged(self):
        assert strip_think_tags(42) == 42

    def test_none_returned_unchanged(self):
        assert strip_think_tags(None) is None

    def test_list_returned_unchanged(self):
        val = ["<think>x</think>", "real"]
        result = strip_think_tags(val)
        assert result is val

    def test_dict_returned_unchanged(self):
        val = {"key": "<think>reason</think>value"}
        result = strip_think_tags(val)
        assert result is val

    def test_float_returned_unchanged(self):
        assert strip_think_tags(3.14) == 3.14

    def test_bool_returned_unchanged(self):
        assert strip_think_tags(True) is True


class TestStripThinkTagsEdgeCases:
    def test_unclosed_tag_returns_input_unchanged(self):
        """Truncated streaming response: no closing tag → input returned as-is.

        The non-greedy regex does not match without a closing </think>, so
        the content passes through unmodified. This is intentional — a greedy
        fallback that consumed everything from <think> to end-of-string would
        silently destroy valid content.
        """
        val = "<think>这是推理过程，还没结束"
        assert strip_think_tags(val) == "<think>这是推理过程，还没结束"

    def test_unclosed_tag_no_hang(self):
        """Confirm the regex does not catastrophically backtrack on a long unclosed tag."""
        long_content = "x" * 10000
        val = f"<think>{long_content}"
        # Should return quickly without hanging
        result = strip_think_tags(val)
        assert val in result  # unchanged

    def test_only_closing_tag_no_match(self):
        val = "some content </think> more content"
        assert strip_think_tags(val) == "some content </think> more content"

    def test_nested_think_tags_non_greedy(self):
        # Non-greedy: removes first valid pair; orphan outer may remain
        val = "<think>outer<think>inner</think>still outer</think>end"
        result = strip_think_tags(val)
        # The first valid pair <think>outer<think>inner</think> is removed
        assert "inner" not in result
        assert "end" in result
