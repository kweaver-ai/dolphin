#!/usr/bin/env python3
"""
ExploreBlock 的单元测试

主要测试 mode 参数相关功能：
- mode="prompt"：使用 PromptStrategy
- mode="tool_call"（默认）：使用 ToolCallStrategy
"""

import unittest
import asyncio
from unittest.mock import MagicMock, patch

from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.code_block.explore_strategy import (
    ExploreStrategy,
    PromptStrategy,
    ToolCallStrategy,
    ToolCall,
)
from dolphin.core.code_block.skill_call_deduplicator import (
    DefaultSkillCallDeduplicator,
    NoOpSkillCallDeduplicator,
)
from dolphin.core.common.enums import Messages, StreamItem, MessageRole
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillset import Skillset


def mock_search(query: str, max_results: int = 10):
    """
    Mock search function for testing

    Args:
        query (str): Search query
        max_results (int): Maximum number of results
    """
    return f"Search results for: {query}"


def mock_execute_sql(sql: str, datasource: str):
    """
    Mock SQL execution function

    Args:
        sql (str): SQL query to execute
        datasource (str): Database datasource name
    """
    return f"Executing: {sql} on {datasource}"


class MockSkillkit:
    """模拟的 Skillkit 类"""

    def __init__(self, skills=None):
        self._skills = skills or {}
        self._skill_names = list(self._skills.keys())

    def isEmpty(self):
        return len(self._skills) == 0

    def getSkillNames(self):
        return self._skill_names

    def getSchemas(self):
        return "mock_search: 搜索工具\nmock_execute_sql: SQL执行工具"

    def getFormattedToolsDescription(self, format_type="medium"):
        return f"[{format_type}] mock_search: 搜索工具\nmock_execute_sql: SQL执行工具"

    def getSkillsSchema(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "mock_search",
                    "description": "搜索工具",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]


class TestExploreBlockMode(unittest.TestCase):
    """测试 ExploreBlock 的 mode 默认行为

    Note:
        mode 参数只能通过 DPH 语法指定，不支持从构造函数传入。
        构造函数测试仅验证默认行为，DPH 语法测试见 TestExploreBlockModeFromDPHSyntax。
    """

    def setUp(self):
        """测试前的设置"""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_default_mode_is_tool_call(self):
        """测试默认模式为 tool_call"""
        block = ExploreBlock(context=self.context)
        self.assertEqual(block.mode, "tool_call")
        self.assertIsInstance(block.strategy, ToolCallStrategy)

    def test_tools_format_parameter(self):
        """测试 tools_format 参数"""
        block = ExploreBlock(context=self.context, tools_format="full")
        self.assertEqual(block.tools_format, "full")


class TestDefaultSkillCallDeduplicator(unittest.TestCase):
    """DefaultSkillCallDeduplicator behavior tests."""

    def test_allows_repeated_check_progress_calls(self):
        """_check_progress is a polling tool and should not be treated as duplicate."""
        dedup = DefaultSkillCallDeduplicator()
        call = ("_check_progress", {})

        for _ in range(DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT + 2):
            assert dedup.is_duplicate(call) is False
            dedup.add(call)

    def test_allows_repeated_wait_calls(self):
        """_wait is a polling tool and should not be treated as duplicate."""
        dedup = DefaultSkillCallDeduplicator()
        call = ("_wait", {"seconds": 5})

        for _ in range(DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT + 2):
            assert dedup.is_duplicate(call) is False
            dedup.add(call)


class TestExploreBlockShouldContinueExplore(unittest.TestCase):
    """ExploreBlock._should_continue_explore behavior tests."""

    def test_should_not_stop_on_polling_tool_duplicates(self):
        """Polling tools should not trigger duplicate-based termination."""
        context_manager = ContextManager()
        global_config = GlobalConfig()
        context = Context(config=global_config, context_manager=context_manager)
        context._calc_all_skills()

        block = ExploreBlock(context=context)
        block.times = 0
        block.should_stop_exploration = False

        dedup = block.strategy.get_deduplicator()
        for _ in range(DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT + 1):
            dedup.add(("_check_progress", {}))

        assert asyncio.run(block._should_continue_explore()) is True

        for _ in range(DefaultSkillCallDeduplicator.MAX_DUPLICATE_COUNT + 1):
            dedup.add(("mock_search", {"query": "q"}))

        assert asyncio.run(block._should_continue_explore()) is False


class TestExploreBlockToolResponseOnce(unittest.TestCase):
    """回归测试：ExploreBlock 成功工具调用不应重复追加 tool response"""

    def setUp(self):
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_execute_tool_call_appends_tool_response_once_on_success(self):
        block = ExploreBlock(context=self.context)

        # 伪造 recorder，避免 _execute_tool_call 里访问为空
        block.recorder = MagicMock()
        block.recorder.get_progress_answers.return_value = {}
        block.recorder.get_answer.return_value = "ok"

        # 伪造 skill_run（必须是 async generator）
        async def mock_skill_run(*args, **kwargs):
            if False:  # pragma: no cover
                yield None

        block.skill_run = mock_skill_run

        # 避免依赖 skillkit_hook / raw_output，直接返回固定 tool 输出
        block._process_skill_result_with_hook = MagicMock(return_value=("hello", {}))

        # 截获追加行为，验证只追加一次
        block.strategy.get_deduplicator = MagicMock(return_value=MagicMock())
        block.strategy.append_tool_response_message = MagicMock()

        stream_item = StreamItem()
        stream_item.answer = "call tool"
        tool_call = ToolCall(id="call_test_1", name="_date", arguments={})

        async def run():
            async for _ in block._execute_tool_call(stream_item, tool_call):
                pass

        asyncio.run(run())

        self.assertEqual(
            block.strategy.append_tool_response_message.call_count,
            1,
            "成功路径下不应重复追加 tool response message",
        )


class TestPromptStrategy(unittest.TestCase):
    """测试 PromptStrategy 策略"""

    def setUp(self):
        self.strategy = PromptStrategy()
        self.skillkit = MockSkillkit({"mock_search": True, "mock_execute_sql": True})

    def test_make_system_message_with_skills(self):
        """测试有技能时的系统消息生成"""
        system_msg = self.strategy.make_system_message(
            skillkit=self.skillkit, system_prompt="用户系统提示", tools_format="medium"
        )
        # 应该包含工具说明格式
        self.assertIn("=>#tool_name", system_msg)
        self.assertIn("Goals", system_msg)
        self.assertIn("tools", system_msg.lower())
        self.assertIn("用户系统提示", system_msg)

    def test_make_system_message_without_skills(self):
        """测试无技能时的系统消息生成"""
        empty_skillkit = MockSkillkit()
        system_msg = self.strategy.make_system_message(
            skillkit=empty_skillkit, system_prompt="用户提示", tools_format="medium"
        )
        self.assertIn("用户提示", system_msg)

    def test_make_system_message_empty_system_prompt(self):
        """测试空系统提示时的消息生成"""
        system_msg = self.strategy.make_system_message(
            skillkit=self.skillkit, system_prompt="", tools_format="medium"
        )
        self.assertNotIn("User Demands", system_msg)

    def test_get_llm_params_no_tools(self):
        """测试 Prompt 模式的 LLM 参数不包含 tools"""
        messages = Messages()
        messages.add_message("test", role=MessageRole.USER)
        params = self.strategy.get_llm_params(
            messages=messages,
            model="gpt-4",
            skillkit=self.skillkit,
            no_cache=True,
        )
        self.assertIn("messages", params)
        self.assertIn("model", params)
        self.assertNotIn("tools", params)
        self.assertEqual(params["no_cache"], True)

    def _create_stream_item(self, answer: str) -> StreamItem:
        """辅助方法：创建 StreamItem 并设置 answer"""
        item = StreamItem()
        item.answer = answer
        return item

    def test_detect_tool_call_no_marker(self):
        """测试没有工具调用标记时返回 None"""
        stream_item = self._create_stream_item("这是一个普通回答")
        context = MagicMock()
        result = self.strategy.detect_tool_call(stream_item, context)
        self.assertIsNone(result)

    def test_detect_tool_call_with_marker(self):
        """测试有工具调用标记时的检测"""
        stream_item = self._create_stream_item('我来搜索一下 =>#mock_search: {"query": "test"}')
        context = MagicMock()
        context.get_skillkit.return_value = self.skillkit
        result = self.strategy.detect_tool_call(stream_item, context)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ToolCall)
        self.assertEqual(result.name, "mock_search")
        self.assertEqual(result.arguments, {"query": "test"})

    def test_detect_tool_call_invalid_skill(self):
        """测试工具名不存在时返回 None"""
        stream_item = self._create_stream_item('调用工具 =>#nonexistent_skill: {"param": "value"}')
        context = MagicMock()
        context.get_skillkit.return_value = self.skillkit
        result = self.strategy.detect_tool_call(stream_item, context)
        self.assertIsNone(result)

    def test_has_valid_tool_call_true(self):
        """测试存在有效工具调用时返回 True"""
        stream_item = self._create_stream_item('=>#mock_search: {"query": "test"}')
        context = MagicMock()
        context.get_skillkit.return_value = self.skillkit
        result = self.strategy.has_valid_tool_call(stream_item, context)
        self.assertTrue(result)

    def test_has_valid_tool_call_false_no_marker(self):
        """测试没有标记时返回 False"""
        stream_item = self._create_stream_item("普通文本")
        context = MagicMock()
        result = self.strategy.has_valid_tool_call(stream_item, context)
        self.assertFalse(result)

    def test_has_valid_tool_call_false_invalid_skill(self):
        """测试技能无效时返回 False"""
        stream_item = self._create_stream_item('=>#invalid_skill: {"param": "value"}')
        context = MagicMock()
        context.get_skillkit.return_value = self.skillkit
        result = self.strategy.has_valid_tool_call(stream_item, context)
        self.assertFalse(result)

    def test_get_tool_call_content(self):
        """测试获取工具调用之前的内容"""
        stream_item = self._create_stream_item('前面的内容 =>#mock_search: {"query": "test"}')
        tool_call = ToolCall(id="call_1", name="mock_search", arguments={"query": "test"})
        content = self.strategy.get_tool_call_content(stream_item, tool_call)
        self.assertEqual(content, "前面的内容 ")

    def test_get_tool_call_content_no_marker(self):
        """测试没有标记时返回完整内容"""
        stream_item = self._create_stream_item("完整内容")
        tool_call = ToolCall(id="call_1", name="test", arguments={})
        content = self.strategy.get_tool_call_content(stream_item, tool_call)
        self.assertEqual(content, "完整内容")


class TestToolCallStrategy(unittest.TestCase):
    """测试 ToolCallStrategy 策略"""

    def setUp(self):
        self.strategy = ToolCallStrategy(tools_format="medium")
        self.skillkit = MockSkillkit({"mock_search": True})

    def test_make_system_message_with_skills(self):
        """测试有技能时的系统消息生成"""
        system_msg = self.strategy.make_system_message(
            skillkit=self.skillkit, system_prompt="用户系统提示", tools_format="medium"
        )
        self.assertIn("Goals", system_msg)
        self.assertIn("Available Tools", system_msg)
        self.assertIn("[medium]", system_msg)  # 使用 formatted description
        self.assertIn("用户系统提示", system_msg)

    def test_make_system_message_empty_system_prompt(self):
        """测试空系统提示时的消息生成"""
        system_msg = self.strategy.make_system_message(
            skillkit=self.skillkit, system_prompt="   ", tools_format="medium"
        )
        # 空白系统提示应该被移除
        self.assertNotIn("{system_prompt}", system_msg)

    def _create_stream_item(self, answer: str = "", tool_name: str = "", tool_args: dict = None) -> StreamItem:
        """辅助方法：创建 StreamItem"""
        item = StreamItem()
        item.answer = answer
        item.tool_name = tool_name
        item.tool_args = tool_args
        return item

    def test_get_llm_params_includes_tools(self):
        """测试 Tool Call 模式的 LLM 参数包含 tools"""
        messages = Messages()
        messages.add_message("test", role=MessageRole.USER)
        params = self.strategy.get_llm_params(
            messages=messages,
            model="gpt-4",
            skillkit=self.skillkit,
            no_cache=False,
        )
        self.assertIn("messages", params)
        self.assertIn("model", params)
        self.assertIn("tools", params)
        self.assertEqual(len(params["tools"]), 1)

    def test_get_llm_params_with_tool_choice(self):
        """测试带 tool_choice 参数"""
        messages = Messages()
        params = self.strategy.get_llm_params(
            messages=messages,
            model="gpt-4",
            skillkit=self.skillkit,
            tool_choice="auto",
        )
        self.assertIn("tool_choice", params)
        self.assertEqual(params["tool_choice"], "auto")

    def test_get_llm_params_empty_skillkit(self):
        """测试空 skillkit 时 tools 为空列表"""
        empty_skillkit = MockSkillkit()
        messages = Messages()
        params = self.strategy.get_llm_params(
            messages=messages,
            model="gpt-4",
            skillkit=empty_skillkit,
        )
        self.assertEqual(params["tools"], [])

    def test_detect_tool_call_no_tool_call(self):
        """测试没有工具调用时返回 None"""
        stream_item = self._create_stream_item(answer="普通回答")
        context = MagicMock()
        result = self.strategy.detect_tool_call(stream_item, context)
        self.assertIsNone(result)

    def test_detect_tool_call_with_tool_call(self):
        """测试有工具调用时的检测"""
        stream_item = self._create_stream_item(
            answer="", tool_name="mock_search", tool_args={"query": "test"}
        )
        context = MagicMock()
        result = self.strategy.detect_tool_call(stream_item, context)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ToolCall)
        self.assertEqual(result.name, "mock_search")
        self.assertEqual(result.arguments, {"query": "test"})
        self.assertIsNone(result.raw_text)  # Tool Call 模式没有 raw_text

    def test_has_valid_tool_call_true(self):
        """测试存在工具调用时返回 True"""
        stream_item = self._create_stream_item(tool_name="mock_search")
        context = MagicMock()
        result = self.strategy.has_valid_tool_call(stream_item, context)
        self.assertTrue(result)

    def test_has_valid_tool_call_false(self):
        """测试没有工具调用时返回 False"""
        stream_item = self._create_stream_item(answer="普通回答")
        context = MagicMock()
        result = self.strategy.has_valid_tool_call(stream_item, context)
        self.assertFalse(result)

    def test_get_tool_call_content_returns_answer(self):
        """测试 Tool Call 模式返回完整 answer"""
        stream_item = self._create_stream_item(answer="思考过程...")
        tool_call = ToolCall(id="call_1", name="test", arguments={})
        content = self.strategy.get_tool_call_content(stream_item, tool_call)
        self.assertEqual(content, "思考过程...")

    def test_get_tool_call_content_empty_answer(self):
        """测试空 answer 时返回空字符串"""
        stream_item = self._create_stream_item()
        stream_item.answer = None
        tool_call = ToolCall(id="call_1", name="test", arguments={})
        content = self.strategy.get_tool_call_content(stream_item, tool_call)
        self.assertEqual(content, "")


class TestToolCallDataClass(unittest.TestCase):
    """测试 ToolCall 数据类"""

    def test_tool_call_creation(self):
        """测试 ToolCall 创建"""
        tool_call = ToolCall(
            id="call_123",
            name="mock_search",
            arguments={"query": "test"},
            raw_text='=>#mock_search: {"query": "test"}',
        )
        self.assertEqual(tool_call.id, "call_123")
        self.assertEqual(tool_call.name, "mock_search")
        self.assertEqual(tool_call.arguments, {"query": "test"})
        self.assertEqual(tool_call.raw_text, '=>#mock_search: {"query": "test"}')

    def test_tool_call_default_raw_text(self):
        """测试 ToolCall 默认 raw_text 为 None"""
        tool_call = ToolCall(
            id="call_123", name="mock_search", arguments={"query": "test"}
        )
        self.assertIsNone(tool_call.raw_text)

    def test_tool_call_empty_arguments(self):
        """测试空参数的 ToolCall"""
        tool_call = ToolCall(id="call_123", name="no_args_tool", arguments={})
        self.assertEqual(tool_call.arguments, {})


class TestExploreStrategyDeduplicator(unittest.TestCase):
    """测试策略的重复调用检测器"""

    def test_prompt_strategy_has_deduplicator(self):
        """测试 PromptStrategy 有重复检测器"""
        strategy = PromptStrategy()
        deduplicator = strategy.get_deduplicator()
        self.assertIsNotNone(deduplicator)
        self.assertIsInstance(deduplicator, DefaultSkillCallDeduplicator)

    def test_tool_call_strategy_has_deduplicator(self):
        """测试 ToolCallStrategy 有重复检测器"""
        strategy = ToolCallStrategy()
        deduplicator = strategy.get_deduplicator()
        self.assertIsNotNone(deduplicator)
        self.assertIsInstance(deduplicator, DefaultSkillCallDeduplicator)

    def test_deduplicator_toggle_switches_to_noop(self):
        """测试 set_deduplicator_enabled(False) 使用空实现去重器"""
        strategy = PromptStrategy()

        # 默认使用默认去重器
        deduplicator_default = strategy.get_deduplicator()
        self.assertIsInstance(deduplicator_default, DefaultSkillCallDeduplicator)

        # 关闭去重器后应返回 NoOpSkillCallDeduplicator
        strategy.set_deduplicator_enabled(False)
        deduplicator_noop = strategy.get_deduplicator()
        self.assertIsInstance(deduplicator_noop, NoOpSkillCallDeduplicator)

        # NoOp 实现应永远不判定为重复
        skill_call = ("mock_search", {"query": "test"})
        deduplicator_noop.add(skill_call)
        self.assertFalse(deduplicator_noop.is_duplicate(skill_call))


class TestPromptStrategyHelperMethods(unittest.TestCase):
    """测试 PromptStrategy 的辅助方法"""

    def setUp(self):
        self.strategy = PromptStrategy()

    def test_first_likely_skill_single(self):
        """测试单个技能名提取"""
        result = self.strategy._first_likely_skill('文本 =>#mock_search: {"query": "test"}')
        self.assertEqual(result, "mock_search")

    def test_first_likely_skill_multiple(self):
        """测试多个技能调用时返回最后一个"""
        result = self.strategy._first_likely_skill(
            '=>#skill1: {} 然后 =>#skill2: {"param": "value"}'
        )
        self.assertEqual(result, "skill2")

    def test_first_likely_skill_no_marker(self):
        """测试没有标记时返回 None"""
        result = self.strategy._first_likely_skill("普通文本没有工具调用")
        self.assertIsNone(result)

    def test_first_likely_skill_call(self):
        """测试获取完整技能调用文本"""
        result = self.strategy._first_likely_skill_call(
            '前文 =>#mock_search: {"query": "test"}'
        )
        self.assertEqual(result, '=>#mock_search: {"query": "test"}')

    def test_complete_skill_call_valid(self):
        """测试完整技能调用提取"""
        result = self.strategy._complete_skill_call(
            '=>#mock_search: {"query": "test", "max_results": 5}'
        )
        self.assertIsNotNone(result)
        skill_name, arguments = result
        self.assertEqual(skill_name, "mock_search")
        self.assertEqual(arguments["query"], "test")
        self.assertEqual(arguments["max_results"], 5)

    def test_complete_skill_call_no_colon(self):
        """测试没有冒号时返回 None"""
        result = self.strategy._complete_skill_call("=>#skill_name")
        self.assertIsNone(result)

    def test_complete_skill_call_no_json(self):
        """测试没有 JSON 参数时返回 None"""
        result = self.strategy._complete_skill_call("=>#skill_name: ")
        self.assertIsNone(result)

    def test_complete_skill_call_nested_json(self):
        """测试嵌套 JSON 参数"""
        result = self.strategy._complete_skill_call(
            '=>#tool: {"config": {"nested": "value"}, "list": [1, 2]}'
        )
        self.assertIsNotNone(result)
        skill_name, arguments = result
        self.assertEqual(skill_name, "tool")
        self.assertEqual(arguments["config"], {"nested": "value"})
        self.assertEqual(arguments["list"], [1, 2])


class TestPromptModeToolResponseFormat(unittest.TestCase):
    """
    测试 Prompt 模式下工具响应消息格式

    在 prompt 模式下，LLM 使用 =># 格式调用工具，不使用 OpenAI 原生 tool_call。
    因此消息应该使用纯文本格式，而不是 OpenAI 的 tool_call/tool_response 格式。
    """

    def setUp(self):
        """测试前的设置"""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()
        self.skillkit = MockSkillkit({"_date": True, "_write_file": True})

    def test_prompt_mode_appends_tool_call_message_as_plain_text(self):
        """
        测试 prompt 模式下 append_tool_call_message 使用纯文本格式

        当 LLM 返回 =>#_date: {} 时，assistant 消息应该只包含纯文本内容，
        不应该包含 OpenAI 格式的 tool_calls 数组。
        """
        strategy = PromptStrategy()

        # 模拟 LLM 返回的 =># 格式工具调用
        stream_item = StreamItem()
        stream_item.answer = '=>#_date: {}'

        tool_call = ToolCall(
            id="call__date_1234",
            name="_date",
            arguments={},
            raw_text='=>#_date: {}'
        )

        # 调用 append_tool_call_message
        strategy.append_tool_call_message(self.context, stream_item, tool_call)

        # 检查添加的消息格式
        messages = self.context.get_messages()

        # 找到最后一条 assistant 消息
        assistant_messages = [m for m in messages if m.role == MessageRole.ASSISTANT]
        self.assertTrue(len(assistant_messages) > 0, "应该有 assistant 消息")

        last_assistant_msg = assistant_messages[-1]

        # 修复后：assistant 消息不应该包含 tool_calls
        self.assertFalse(
            last_assistant_msg.has_tool_calls(),
            "prompt 模式下 assistant 消息不应该包含 tool_calls"
        )

        # 消息内容应该是完整的 =># 格式文本
        self.assertEqual(last_assistant_msg.content, '=>#_date: {}')

    def test_prompt_mode_appends_tool_response_as_user_message(self):
        """
        测试 prompt 模式下 append_tool_response_message 使用 user 消息格式

        工具响应应该以 user 消息形式添加，而不是 OpenAI 的 tool role 格式。
        """
        strategy = PromptStrategy()

        # 添加工具响应
        tool_call_id = "call__date_1234"
        tool_response = "2025-12-05"

        strategy.append_tool_response_message(
            self.context, tool_call_id, tool_response
        )

        # 检查添加的消息格式
        messages = self.context.get_messages()

        # 不应该有 tool role 消息
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        self.assertEqual(len(tool_messages), 0, "不应该有 tool role 消息")

        # 应该有 user 消息
        user_messages = [m for m in messages if m.role == MessageRole.USER]
        self.assertTrue(len(user_messages) > 0, "应该有 user 消息")

        last_user_msg = user_messages[-1]
        # 工具响应应该包含在 user 消息中
        self.assertIn(tool_response, last_user_msg.content)
        self.assertIn("工具返回结果", last_user_msg.content)

    def test_prompt_mode_messages_sequence_is_llm_friendly(self):
        """
        测试完整的消息序列对 LLM 友好

        消息序列应该全部使用纯文本格式，不应该包含 OpenAI tool_call 格式。
        """
        strategy = PromptStrategy()

        # Step 1: 构建系统消息
        system_message = strategy.make_system_message(
            skillkit=self.skillkit,
            system_prompt="你是一个助手",
            tools_format="medium"
        )

        # 验证系统消息包含 =># 格式说明
        self.assertIn("=>#tool_name", system_message)
        self.assertIn("=>#someskill", system_message)

        # Step 2: 模拟第一次 LLM 调用后的消息
        stream_item = StreamItem()
        stream_item.answer = '=>#_date: {}'

        tool_call = ToolCall(
            id="call__date_1234",
            name="_date",
            arguments={},
            raw_text='=>#_date: {}'
        )

        # 添加工具调用消息
        strategy.append_tool_call_message(self.context, stream_item, tool_call)

        # Step 3: 添加工具响应
        strategy.append_tool_response_message(
            self.context, "call__date_1234", "2025-12-05"
        )

        # 获取完整消息序列
        messages = self.context.get_messages()
        messages_dict = [m.to_dict() for m in messages]

        # 验证消息序列不包含 OpenAI tool_call 格式
        has_openai_tool_calls = any(
            'tool_calls' in m for m in messages_dict
        )
        has_openai_tool_response = any(
            m.get('role') == 'tool' for m in messages_dict
        )

        # 修复后：prompt 模式不应该使用 OpenAI tool_call 格式
        self.assertFalse(
            has_openai_tool_calls,
            "prompt 模式不应该使用 OpenAI tool_calls 格式"
        )
        self.assertFalse(
            has_openai_tool_response,
            "prompt 模式不应该使用 OpenAI tool response 格式"
        )

        # 验证消息角色序列：assistant -> user
        roles = [m['role'] for m in messages_dict]
        self.assertIn('assistant', roles)
        self.assertIn('user', roles)


class TestExploreBlockModeFromDPHSyntax(unittest.TestCase):
    """
    测试 DPH 语法中 mode 参数的解析

    根据设计文档 docs/design/architecture/explore_block_merge.md:
    - /explore/(mode="tool_call", ...) 应使用 ToolCallStrategy
    - /explore/(mode="prompt", ...) 应使用 PromptStrategy
    - 默认模式为 "tool_call"
    """

    def setUp(self):
        """测试前的设置"""
        from dolphin.core.common.enums import CategoryBlock
        self.CategoryBlock = CategoryBlock

        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_mode_tool_call_from_dph_syntax(self):
        """
        测试 DPH 语法 /explore/(mode="tool_call") 应使用 ToolCallStrategy

        这是设计文档中要求的关键功能：
        /explore/(mode="tool_call", model="gpt-4")
        用户问题
        -> result
        """
        block = ExploreBlock(context=self.context)

        # 模拟解析 DPH 语法
        content = '/explore/(mode="tool_call") 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # 验证 mode 被正确解析
        self.assertEqual(block.mode, "tool_call")
        # 验证策略被正确更新
        self.assertIsInstance(block.strategy, ToolCallStrategy)

    def test_mode_prompt_from_dph_syntax(self):
        """
        测试 DPH 语法 /explore/(mode="prompt") 应使用 PromptStrategy
        """
        block = ExploreBlock(context=self.context)

        content = '/explore/(mode="prompt") 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        self.assertEqual(block.mode, "prompt")
        self.assertIsInstance(block.strategy, PromptStrategy)

    def test_mode_with_other_params_from_dph_syntax(self):
        """
        测试 DPH 语法中 mode 与其他参数一起使用

        /explore/(mode="tool_call", model="gpt-4", history=true)
        用户问题
        -> result
        """
        block = ExploreBlock(context=self.context)

        content = '/explore/(mode="tool_call", model="gpt-4", history=true) 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # 验证 mode 参数
        self.assertEqual(block.mode, "tool_call")
        self.assertIsInstance(block.strategy, ToolCallStrategy)

        # 验证其他参数也正确解析
        self.assertEqual(block.model, "gpt-4")
        self.assertTrue(block.history)

    def test_default_mode_when_not_specified(self):
        """
        测试 DPH 语法中未指定 mode 时使用默认值 "tool_call"
        """
        block = ExploreBlock(context=self.context)

        content = '/explore/(model="gpt-4") 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # 默认应该是 tool_call 模式
        self.assertEqual(block.mode, "tool_call")
        self.assertIsInstance(block.strategy, ToolCallStrategy)

    def test_mode_without_quotes_from_dph_syntax(self):
        """
        测试 DPH 语法中 mode 参数不带引号的情况

        /explore/(mode=tool_call) 应该也能正确解析
        """
        block = ExploreBlock(context=self.context)

        content = '/explore/(mode=tool_call) 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        self.assertEqual(block.mode, "tool_call")
        self.assertIsInstance(block.strategy, ToolCallStrategy)

    def test_invalid_mode_from_dph_syntax_raises_error(self):
        """
        测试 DPH 语法中无效的 mode 值应抛出错误
        """
        block = ExploreBlock(context=self.context)

        content = '/explore/(mode="invalid_mode") 用户问题 -> result'

        with self.assertRaises(ValueError) as cm:
            block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        self.assertIn("Invalid mode", str(cm.exception))
        self.assertIn("invalid_mode", str(cm.exception))

    def test_strategy_updated_after_parse(self):
        """
        测试 parse_block_content() 调用后策略应根据解析的 mode 更新

        这是一个重要的测试：__init__ 时使用默认策略（tool_call），
        parse_block_content() 后应该根据 DPH 语法中的 mode 参数更新策略
        """
        # 创建 block 时默认是 tool_call 模式
        block = ExploreBlock(context=self.context)
        self.assertIsInstance(block.strategy, ToolCallStrategy)

        # DPH 内容指定 prompt 模式
        # 解析后策略应该从 ToolCallStrategy 更新为 PromptStrategy
        content = '/explore/(mode="prompt") 用户问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # 策略应该被更新为 PromptStrategy
        self.assertEqual(block.mode, "prompt")
        self.assertIsInstance(block.strategy, PromptStrategy)


class TestExploreBlockModeConsistency(unittest.TestCase):
    """
    测试 mode 参数在不同场景下的一致性
    """

    def setUp(self):
        """测试前的设置"""
        from dolphin.core.common.enums import CategoryBlock
        self.CategoryBlock = CategoryBlock

        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_dph_mode_overrides_default(self):
        """
        测试 DPH 语法中的 mode 会覆盖默认值

        构造函数默认使用 prompt 模式，DPH 语法可以覆盖为 tool_call
        """
        # 构造时使用默认 prompt 模式
        block = ExploreBlock(context=self.context)

        # DPH 语法指定 tool_call
        content = '/explore/(mode="tool_call") 问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # DPH 的 mode 应该生效
        self.assertEqual(block.mode, "tool_call")
        self.assertIsInstance(block.strategy, ToolCallStrategy)

    def test_tools_format_preserved_when_mode_changes(self):
        """
        测试 mode 变化时 tools_format 应该保持
        """
        block = ExploreBlock(context=self.context, tools_format="full")

        content = '/explore/(mode="tool_call") 问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)

        # mode 改变
        self.assertEqual(block.mode, "tool_call")
        # tools_format 应保持（策略应使用正确的 format）
        self.assertEqual(block.tools_format, "full")
        self.assertEqual(block.strategy.tools_format, "full")


class TestExploreBlockDeduplicatorParamParsing(unittest.TestCase):
    """Test enable_skill_deduplicator param parsing."""

    def setUp(self):
        from dolphin.core.common.enums import CategoryBlock

        self.CategoryBlock = CategoryBlock
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_enable_skill_deduplicator_false_string_is_parsed_as_bool_false(self):
        """DPH string 'false' should disable the deduplicator."""
        block = ExploreBlock(context=self.context)
        content = "/explore/(enable_skill_deduplicator=false) 问题 -> result"
        block.parse_block_content(
            content, category=self.CategoryBlock.EXPLORE, replace_variables=False
        )
        self.assertIs(block.enable_skill_deduplicator, False)


class TestExploreBlockExecModeParsing(unittest.TestCase):
    """Test exec_mode parameter parsing and validation in ExploreBlock."""

    def setUp(self):
        from dolphin.core.common.enums import CategoryBlock
        self.CategoryBlock = CategoryBlock
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config, context_manager=self.context_manager
        )
        self.context._calc_all_skills()

    def test_exec_mode_seq_parsing(self):
        """Test 'seq' maps to 'sequential'."""
        block = ExploreBlock(context=self.context)
        content = '/explore/(exec_mode="seq") 问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)
        from dolphin.core.task_registry import PlanExecMode
        self.assertEqual(block.params.get("exec_mode"), PlanExecMode.SEQUENTIAL)

    def test_exec_mode_para_parsing(self):
        """Test 'para' maps to 'parallel'."""
        block = ExploreBlock(context=self.context)
        content = '/explore/(exec_mode="para") 问题 -> result'
        block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)
        from dolphin.core.task_registry import PlanExecMode
        self.assertEqual(block.params.get("exec_mode"), PlanExecMode.PARALLEL)

    def test_exec_mode_invalid_raises_error(self):
        """Test invalid values raise ValueError."""
        block = ExploreBlock(context=self.context)
        content = '/explore/(exec_mode="invalid") 问题 -> result'
        with self.assertRaises(ValueError) as cm:
            block.parse_block_content(content, category=self.CategoryBlock.EXPLORE, replace_variables=False)
        self.assertIn("Invalid execution mode", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
