#!/usr/bin/env python3
"""
BasicCodeBlock 类的单元测试
"""

import unittest
from unittest.mock import MagicMock


from dolphin.lib.skill_results.result_reference import ResultReference
from dolphin.lib.skill_results.cache_backend import CacheBackend
from dolphin.lib.skill_results.strategy_registry import StrategyRegistry
from dolphin.lib.skill_results.strategies import BaseStrategy
from dolphin.lib.skill_results.skillkit_hook import SkillkitHook


class TestResultReference(unittest.TestCase):
    """ResultReference 的单元测试类"""

    def setUp(self):
        """测试前的设置"""
        mock_cache_backend = MagicMock(spec=CacheBackend)
        strategy_registry = StrategyRegistry()
        test_strategy = TestStrategy()
        strategy_registry.register(
            "test_category", test_strategy, category="test_category_strategy"
        )
        self.skillkit_hook = SkillkitHook(strategy_registry=strategy_registry)

        print("Registered strategies:", strategy_registry.list_strategies())

        self.block = ResultReference(
            reference_id="1",
            cache_backend=mock_cache_backend,
            strategy_registry=strategy_registry,
        )

    def test_get_for_category(self):
        rt = self.block.get_for_category(category="llm", strategy_name="xxxx")
        self.assertEqual(rt, None)

    def test_custom_category(self):
        result_ref = self.skillkit_hook.process_result(
            tool_name="test_tool", result="test_data", metadata={}
        )
        print("ref:", result_ref.reference_id)
        processed = self.skillkit_hook.get_for_category(
            reference_id=result_ref.reference_id,
            category="test_category_strategy",
            strategy_name="test_category",
        )

        print("Processed result:", processed)  # 调试日志
        assert processed == "Processed: test_data"


class TestStrategy(BaseStrategy):
    category = "test_category_strategy"

    def process(self, result_reference, **kwargs):
        print("XXX")
        full_result = result_reference.get_full_result()
        print(f"Processing result: {full_result}")  # 调试日志
        return f"Processed: {full_result}"


if __name__ == "__main__":
    # 设置详细的测试输出
    unittest.main(verbosity=2)
