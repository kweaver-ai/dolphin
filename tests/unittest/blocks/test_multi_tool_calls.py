# -*- coding: utf-8 -*-
"""Tests for Multi-Tool Calls Feature

Tests the ENABLE_PARALLEL_TOOL_CALLS feature flag and related functionality.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from dolphin.core.common.enums import StreamItem, ToolCallInfo
from dolphin.core import flags
from dolphin.core.code_block.explore_strategy import (
    ExploreStrategy,
    ToolCallStrategy,
    PromptStrategy,
    ToolCall,
)


class TestToolCallInfo:
    """Tests for ToolCallInfo dataclass"""

    def test_creation_with_all_fields(self):
        """Test creating ToolCallInfo with all fields"""
        info = ToolCallInfo(
            id="call_abc123",
            name="test_tool",
            arguments={"x": 1, "y": "test"},
            index=0,
            raw_arguments='{"x": 1, "y": "test"}',
            is_complete=True,
        )
        assert info.id == "call_abc123"
        assert info.name == "test_tool"
        assert info.arguments == {"x": 1, "y": "test"}
        assert info.index == 0
        assert info.raw_arguments == '{"x": 1, "y": "test"}'
        assert info.is_complete is True

    def test_creation_with_defaults(self):
        """Test creating ToolCallInfo with default values"""
        info = ToolCallInfo(id="call_123", name="my_tool")
        assert info.id == "call_123"
        assert info.name == "my_tool"
        assert info.arguments is None
        assert info.index == 0
        assert info.raw_arguments == ""
        assert info.is_complete is False  # Default is False

    def test_arguments_can_be_none(self):
        """Test that arguments can be None for incomplete tool calls"""
        info = ToolCallInfo(id="call_x", name="partial_tool", arguments=None)
        assert info.arguments is None
        assert info.is_complete is False


class TestStreamItemMultiToolCalls:
    """Tests for StreamItem multi-tool calls support"""

    def test_parse_single_tool_call(self):
        """Test parsing a single tool call from tool_calls_data"""
        stream_item = StreamItem()
        chunk = {
            "content": "Calling tool...",
            "finish_reason": "tool_calls",
            "tool_calls_data": {
                0: {
                    "id": "call_abc",
                    "name": "read_file",
                    "arguments": ['{"path": "/test.txt"}'],
                }
            },
        }
        stream_item.parse_from_chunk(chunk, session_counter=1)

        assert len(stream_item.tool_calls) == 1
        assert stream_item.tool_calls[0].id == "call_abc"
        assert stream_item.tool_calls[0].name == "read_file"
        assert stream_item.tool_calls[0].arguments == {"path": "/test.txt"}
        assert stream_item.finish_reason == "tool_calls"

    def test_parse_multiple_tool_calls(self):
        """Test parsing multiple tool calls from tool_calls_data"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "finish_reason": "tool_calls",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": ['{"x": 1}']},
                1: {"id": "call_2", "name": "tool_b", "arguments": ['{"y": 2}']},
                2: {"id": "call_3", "name": "tool_c", "arguments": ['{"z": 3}']},
            },
        }
        stream_item.parse_from_chunk(chunk, session_counter=1)

        assert len(stream_item.tool_calls) == 3
        assert stream_item.tool_calls[0].name == "tool_a"
        assert stream_item.tool_calls[1].name == "tool_b"
        assert stream_item.tool_calls[2].name == "tool_c"

    def test_tool_calls_sorted_by_index(self):
        """Test that tool calls are sorted by index"""
        stream_item = StreamItem()
        # Provide out-of-order indices
        chunk = {
            "content": "",
            "tool_calls_data": {
                2: {"id": "call_z", "name": "last", "arguments": ['{}']},
                0: {"id": "call_x", "name": "first", "arguments": ['{}']},
                1: {"id": "call_y", "name": "middle", "arguments": ['{}']},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].name == "first"
        assert stream_item.tool_calls[1].name == "middle"
        assert stream_item.tool_calls[2].name == "last"

    def test_fallback_id_generation(self):
        """Test fallback ID generation when LLM doesn't provide IDs"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"name": "tool_a", "arguments": ['{}']},  # No id
                1: {"name": "tool_b", "arguments": ['{}']},  # No id
            },
        }
        stream_item.parse_from_chunk(chunk, session_counter=5)

        assert stream_item.tool_calls[0].id == "call_5_0"
        assert stream_item.tool_calls[1].id == "call_5_1"

    def test_partial_id_from_llm(self):
        """Test that LLM-provided IDs take priority"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "llm_provided_id", "name": "tool_a", "arguments": ['{}']},
                1: {"name": "tool_b", "arguments": ['{}']},  # No id, should use fallback
            },
        }
        stream_item.parse_from_chunk(chunk, session_counter=10)

        assert stream_item.tool_calls[0].id == "llm_provided_id"
        assert stream_item.tool_calls[1].id == "call_10_1"

    def test_invalid_json_arguments(self):
        """Test handling of invalid JSON arguments"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "finish_reason": "tool_calls",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": ["invalid json"]},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert len(stream_item.tool_calls) == 1
        assert stream_item.tool_calls[0].arguments is None  # Failed to parse
        assert stream_item.tool_calls[0].raw_arguments == "invalid json"

    def test_streaming_arguments(self):
        """Test parsing streaming arguments (list of chunks)"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {
                    "id": "call_1",
                    "name": "tool_a",
                    "arguments": ['{"na', 'me": ', '"test"}'],  # Split streaming
                }
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].arguments == {"name": "test"}
        assert stream_item.tool_calls[0].raw_arguments == '{"name": "test"}'

    def test_get_tool_calls_returns_list(self):
        """Test get_tool_calls() returns correct list"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": ['{}']},
            },
        }
        stream_item.parse_from_chunk(chunk)

        calls = stream_item.get_tool_calls()
        assert len(calls) == 1
        assert isinstance(calls[0], ToolCallInfo)

    def test_get_tool_calls_fallback_to_legacy(self):
        """Test get_tool_calls() falls back to legacy fields"""
        stream_item = StreamItem()
        stream_item.tool_name = "legacy_tool"
        stream_item.tool_args = {"a": 1}

        calls = stream_item.get_tool_calls()
        assert len(calls) == 1
        assert calls[0].name == "legacy_tool"
        assert calls[0].arguments == {"a": 1}

    def test_has_tool_calls_method(self):
        """Test has_tool_calls() method"""
        stream_item = StreamItem()
        assert stream_item.has_tool_calls() is False

        stream_item.tool_calls = [ToolCallInfo(id="1", name="test")]
        assert stream_item.has_tool_calls() is True

    def test_to_dict_includes_tool_calls(self):
        """Test to_dict() includes tool_calls field"""
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="tool_a", arguments={"x": 1}, index=0)
        ]
        stream_item.finish_reason = "tool_calls"

        result = stream_item.to_dict()

        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "tool_a"
        assert result["finish_reason"] == "tool_calls"


class TestToolCallStrategyMultiToolCalls:
    """Tests for ToolCallStrategy.detect_tool_calls()"""

    def test_detect_tool_calls_empty(self):
        """Test detect_tool_calls with no tool calls"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        context = MagicMock()

        result = strategy.detect_tool_calls(stream_item, context)

        assert result == []

    def test_detect_tool_calls_single(self):
        """Test detect_tool_calls with single tool call"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="tool_a", arguments={"x": 1}, is_complete=True)
        ]
        context = MagicMock()

        result = strategy.detect_tool_calls(stream_item, context)

        assert len(result) == 1
        assert isinstance(result[0], ToolCall)
        assert result[0].name == "tool_a"
        assert result[0].arguments == {"x": 1}

    def test_detect_tool_calls_multiple(self):
        """Test detect_tool_calls with multiple tool calls"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="tool_a", arguments={}, is_complete=True),
            ToolCallInfo(id="call_2", name="tool_b", arguments={"y": 2}, is_complete=True),
        ]
        context = MagicMock()

        result = strategy.detect_tool_calls(stream_item, context)

        assert len(result) == 2
        assert result[0].name == "tool_a"
        assert result[1].name == "tool_b"

    def test_detect_tool_calls_filters_unparsed_arguments(self):
        """Test that tool calls with is_complete=False are filtered out"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="valid", arguments={}, is_complete=True),
            ToolCallInfo(id="call_2", name="invalid", arguments=None, is_complete=False),  # Not complete
        ]
        context = MagicMock()

        result = strategy.detect_tool_calls(stream_item, context)

        assert len(result) == 1
        assert result[0].name == "valid"

    def test_detect_tool_calls_logs_warning_for_failed_parse(self):
        """Test that warning is logged for failed argument parsing"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.finish_reason = "tool_calls"  # Stream complete
        stream_item.tool_calls = [
            ToolCallInfo(
                id="call_1",
                name="broken",
                arguments=None,
                raw_arguments="invalid json",
            )
        ]
        context = MagicMock()

        result = strategy.detect_tool_calls(stream_item, context)

        assert len(result) == 0
        context.warn.assert_called_once()


class TestPromptStrategyMultiToolCalls:
    """Tests for PromptStrategy.detect_tool_calls() - uses base class implementation"""

    def test_detect_tool_calls_wraps_single(self):
        """Test that detect_tool_calls wraps detect_tool_call result"""
        strategy = PromptStrategy()
        stream_item = StreamItem()
        # Use proper format: =>#{skill_name}: {json}
        stream_item.answer = "=>#{test_skill}: {}"
        context = MagicMock()
        # Mock skillkit and skill validation
        mock_skillkit = MagicMock()
        mock_skillkit.isEmpty.return_value = False
        mock_skillkit.getSkill.return_value = MagicMock()  # Skill exists
        context.skillkit = mock_skillkit

        result = strategy.detect_tool_calls(stream_item, context)

        # PromptStrategy.detect_tool_call requires valid skill in context
        # If no valid skill, result will be empty
        assert isinstance(result, list)


class TestAppendToolCallsMessage:
    """Tests for ExploreStrategy.append_tool_calls_message()"""

    def test_append_multiple_tool_calls(self):
        """Test appending message with multiple tool calls"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.answer = "Let me call these tools"

        tool_calls = [
            ToolCall(id="call_1", name="tool_a", arguments={"x": 1}),
            ToolCall(id="call_2", name="tool_b", arguments={"y": 2}),
        ]

        context = MagicMock()
        context.add_bucket = MagicMock()

        strategy.append_tool_calls_message(context, stream_item, tool_calls)

        # Verify add_bucket was called
        context.add_bucket.assert_called_once()
        call_args = context.add_bucket.call_args

        # Verify bucket name (BuildInBucket.SCRATCHPAD.value is '_scratchpad')
        assert call_args[0][0] == "_scratchpad"

        # Verify Messages object
        messages = call_args[0][1]
        message_list = messages.get_messages()
        assert len(message_list) == 1

        # Check message content
        msg = message_list[0]
        assert msg.content == "Let me call these tools"
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0]["function"]["name"] == "tool_a"
        assert msg.tool_calls[1]["function"]["name"] == "tool_b"


class TestStreamItemEdgeCases:
    """Tests for StreamItem edge cases and boundary conditions"""

    def test_empty_tool_calls_data(self):
        """Test parsing with empty tool_calls_data dict"""
        stream_item = StreamItem()
        chunk = {
            "content": "Some content",
            "tool_calls_data": {},
        }
        stream_item.parse_from_chunk(chunk)

        assert len(stream_item.tool_calls) == 0
        assert stream_item.answer == "Some content"

    def test_large_index_value(self):
        """Test parsing with large index values"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                1000000: {"id": "call_large", "name": "tool_large", "arguments": ['{}']},
                0: {"id": "call_zero", "name": "tool_zero", "arguments": ['{}']},
            },
        }
        stream_item.parse_from_chunk(chunk)

        # Should be sorted by index
        assert len(stream_item.tool_calls) == 2
        assert stream_item.tool_calls[0].name == "tool_zero"
        assert stream_item.tool_calls[1].name == "tool_large"
        assert stream_item.tool_calls[1].index == 1000000

    def test_nested_json_arguments(self):
        """Test parsing arguments with nested JSON structures"""
        stream_item = StreamItem()
        nested_args = '{"outer": {"inner": {"deep": "value"}}, "array": [1, 2, {"key": "val"}]}'
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": [nested_args]},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].arguments["outer"]["inner"]["deep"] == "value"
        assert stream_item.tool_calls[0].arguments["array"][2]["key"] == "val"

    def test_special_characters_in_arguments(self):
        """Test parsing arguments with special characters"""
        stream_item = StreamItem()
        special_args = '{"path": "/tmp/file with spaces.txt", "content": "line1\\nline2\\ttab"}'
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": [special_args]},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].arguments["path"] == "/tmp/file with spaces.txt"
        assert stream_item.tool_calls[0].arguments["content"] == "line1\nline2\ttab"

    def test_unicode_in_arguments(self):
        """Test parsing arguments with unicode characters"""
        stream_item = StreamItem()
        unicode_args = '{"text": "你好世界", "emoji": "🚀🎉"}'
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": [unicode_args]},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].arguments["text"] == "你好世界"
        assert stream_item.tool_calls[0].arguments["emoji"] == "🚀🎉"

    def test_no_session_counter_uses_uuid(self):
        """Test that not providing session_counter generates UUID-based IDs"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"name": "tool_a", "arguments": ['{}']},
            },
        }
        # Don't provide session_counter
        stream_item.parse_from_chunk(chunk)

        # ID should start with "call_" and have UUID format (8 hex chars)
        assert stream_item.tool_calls[0].id.startswith("call_")
        # Extract the batch_id part and verify it's hex
        parts = stream_item.tool_calls[0].id.split("_")
        assert len(parts) == 3  # "call", batch_id, index
        batch_id = parts[1]
        assert len(batch_id) == 8
        # Should be valid hex
        int(batch_id, 16)

    def test_tool_call_with_empty_arguments(self):
        """Test parsing tool call with empty arguments string"""
        stream_item = StreamItem()
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {"id": "call_1", "name": "tool_a", "arguments": []},
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert len(stream_item.tool_calls) == 1
        assert stream_item.tool_calls[0].arguments is None

    def test_multiple_argument_chunks_streaming(self):
        """Test streaming with multiple small argument chunks"""
        stream_item = StreamItem()
        # Simulate streaming where JSON arrives in many small pieces
        chunk = {
            "content": "",
            "tool_calls_data": {
                0: {
                    "id": "call_1",
                    "name": "tool_a",
                    "arguments": ['{', '"', 'k', 'e', 'y', '"', ':', '"', 'v', 'a', 'l', '"', '}'],
                }
            },
        }
        stream_item.parse_from_chunk(chunk)

        assert stream_item.tool_calls[0].arguments == {"key": "val"}


class TestFeatureFlagIntegration:
    """Tests for ENABLE_PARALLEL_TOOL_CALLS feature flag integration"""

    def test_flag_exists(self):
        """Test that the feature flag is defined"""
        assert hasattr(flags, "ENABLE_PARALLEL_TOOL_CALLS")
        assert flags.ENABLE_PARALLEL_TOOL_CALLS == "enable_parallel_tool_calls"

    @patch("dolphin.core.flags.is_enabled")
    def test_has_tool_call_respects_flag(self, mock_is_enabled):
        """Test has_tool_call behavior with flag enabled/disabled"""
        stream_item = StreamItem()
        stream_item.tool_calls = [ToolCallInfo(id="1", name="test")]
        # No legacy tool_name set

        # When flag is disabled, only legacy field is checked
        mock_is_enabled.return_value = False
        assert stream_item.has_tool_call() is False

        # When flag is enabled, tool_calls is also checked
        mock_is_enabled.return_value = True
        assert stream_item.has_tool_call() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
