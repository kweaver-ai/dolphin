#!/usr/bin/env python3
"""ExploreBlockV2 相关的单元测试"""

import unittest
import asyncio
from unittest.mock import MagicMock, patch

from dolphin.core import flags
from dolphin.core.code_block.explore_block_v2 import (
    ExploreBlockV2,
    DeduplicatorSkillCall,
)
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import (
    ContextManager,
)
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.common.enums import StreamItem, MessageRole


class TestExploreBlockV2(unittest.TestCase):
    """ExploreBlockV2 的单元测试"""

    def test_make_init_messages_history_none_with_context_manager(self):
        """
        当 history 未在 Context 中设置，且启用了 context engineer 时，
        _make_init_messages 当前会因为 history_messages 为 None 而触发 AttributeError。
        该测试复现问题，期望未来修复后不再抛出异常。
        """
        context_manager = ContextManager()
        global_config = GlobalConfig()
        context = Context(config=global_config, context_manager=context_manager)
        context._calc_all_skills()

        block = ExploreBlockV2(context=context)
        block.history = "true"  # 强制启用 history 分支
        block.content = "test question"
        block.system_prompt = ""
        block.skills = None

        try:
            block._make_init_messages()
        except AttributeError as exc:  # pragma: no cover - 捕获当前的异常以复现问题
            self.fail(
                f"_make_init_messages should handle missing history gracefully, but raised: {exc}"
                )

    def test_should_continue_explore_stops_on_duplicates_when_enabled(self):
        """
        当启用去重器时，重复调用次数达到阈值应终止探索
        """
        context_manager = ContextManager()
        global_config = GlobalConfig()
        context = Context(config=global_config, context_manager=context_manager)
        context._calc_all_skills()

        block = ExploreBlockV2(context=context)
        block.times = 0
        block.should_stop_exploration = False
        # 模拟重复调用已达到阈值
        block.deduplicator_skillcall.skillcalls = {
            "mock_call": DeduplicatorSkillCall.MAX_DUPLICATE_COUNT
        }
        block.enable_skill_deduplicator = True

        self.assertFalse(block._should_continue_explore())

    def test_should_continue_explore_ignores_duplicates_when_disabled(self):
        """
        当关闭去重器时，即使重复调用计数达到阈值也不应因此终止探索
        """
        context_manager = ContextManager()
        global_config = GlobalConfig()
        context = Context(config=global_config, context_manager=context_manager)
        context._calc_all_skills()

        block = ExploreBlockV2(context=context)
        block.times = 0
        block.should_stop_exploration = False
        # 模拟重复调用已达到阈值
        block.deduplicator_skillcall.skillcalls = {
            "mock_call": DeduplicatorSkillCall.MAX_DUPLICATE_COUNT
        }
        block.enable_skill_deduplicator = False

        self.assertTrue(block._should_continue_explore())

    def test_execute_tool_call_adds_error_message_on_exception(self):
        """
        测试当 skill_run 抛出异常时，_execute_tool_call 应该：
        1. 调用 context.error
        2. 添加包含错误信息的 tool response message
        """
        context_manager = ContextManager()
        global_config = GlobalConfig()
        context = Context(config=global_config, context_manager=context_manager)
        context._calc_all_skills()
        context.error = MagicMock()
        
        # Mock bucket operations
        bucket_messages = []
        def add_bucket(name, content, **kwargs):
            bucket_messages.append(content)
        
        block = ExploreBlockV2(context=context)
        
        # Mock skill_run to raise exception
        async def mock_skill_run(*args, **kwargs):
            raise Exception("Browser timeout")
            yield # make it a generator
        block.skill_run = mock_skill_run
        
        # Mock stream item with tool call
        stream_item = MagicMock(spec=StreamItem)
        stream_item.tool_name = "browser_tool"
        stream_item.tool_args = {}
        stream_item.answer = "Calling browser..."
        stream_item.get_tool_call.return_value = {
            "name": "browser_tool",
            "arguments": {}
        }
        
        # Run _execute_tool_call with patched add_bucket
        async def run_test():
            with patch.object(context, 'add_bucket', side_effect=add_bucket):
                async for _ in block._execute_tool_call(stream_item, "call_123"):
                    pass
                
        asyncio.run(run_test())
        
        # Verify context.error was called
        context.error.assert_called()
        
        # Verify tool response message was added
        tool_responses = [
            m for m in bucket_messages
            if hasattr(m, 'messages') and any(msg.role == MessageRole.TOOL for msg in m.messages)
        ]
        
        self.assertTrue(len(tool_responses) > 0, "Should add tool response message after exception")
        found_error = False
        for tr in tool_responses:
            for msg in tr.messages:
                if msg.role == MessageRole.TOOL and "Browser timeout" in msg.content:
                    found_error = True
                    break
        self.assertTrue(found_error, "Tool response should contain the error message")

if __name__ == "__main__":
    unittest.main()
