#!/usr/bin/env python3
"""ExploreBlockV2 相关的单元测试"""

import unittest

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

if __name__ == "__main__":
    unittest.main()
