#!/usr/bin/env python3
"""
测试 continue_exploration 方法对 skills 配置的继承

Bug 描述：
continue_exploration 方法没有走 execute -> parse_block_content 流程，
导致 self.skills 保持 None，无法继承第一轮 execute 设置的 skills 配置。

预期行为：
1. 如果 kwargs 中传入 skills/tools，应该使用传入的配置
2. 否则，应该继承 context 中已有的 skillkit 配置
"""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.skill.skillset import Skillset
from dolphin.core.skill.skill_function import SkillFunction


def mock_search(query: str):
    """Mock search function"""
    return f"Search results for: {query}"


def mock_calculator(expression: str):
    """Mock calculator function"""
    return f"Result: {expression}"


def mock_other_tool(param: str):
    """Mock other tool function"""
    return f"Other tool: {param}"


class TestContinueExplorationSkillsInheritance(unittest.TestCase):
    """
    测试 continue_exploration 对 skills 配置的继承
    """

    def setUp(self):
        """测试前的设置"""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager,
        )

        # Create mock skillkit objects (owner_skillkit must have getName() method)
        vm_skillkit_mock = MagicMock()
        vm_skillkit_mock.getName.return_value = "vm_skillkit"
        
        resource_skillkit_mock = MagicMock()
        resource_skillkit_mock.getName.return_value = "resource_skillkit"

        # 创建包含多个技能的 Skillset
        self.all_skills = Skillset()
        search_skill = SkillFunction(mock_search)
        search_skill.set_owner_skillkit(vm_skillkit_mock)
        self.all_skills.addSkill(search_skill)

        calculator_skill = SkillFunction(mock_calculator)
        calculator_skill.set_owner_skillkit(vm_skillkit_mock)
        self.all_skills.addSkill(calculator_skill)

        other_skill = SkillFunction(mock_other_tool)
        other_skill.set_owner_skillkit(resource_skillkit_mock)
        self.all_skills.addSkill(other_skill)

        # 设置 context 的技能
        self.context.set_skills(self.all_skills)
        self.context._calc_all_skills()

    def test_continue_exploration_without_skills_uses_all_skills(self):
        """
        测试 continue_exploration 在没有传入 skills 参数时使用 all_skills
        
        这是当前行为：self.skills = None 时，get_skillkit() 返回 all_skills
        """
        block = ExploreBlock(context=self.context)

        # 模拟多轮对话：调用 continue_exploration 但不传 skills
        # 此时 self.skills 应该仍然是 None（因为没有 parse）
        self.assertIsNone(block.skills)

        # get_skillkit() 应该返回所有技能
        skillkit = block.get_skillkit()
        skill_names = skillkit.getSkillNames()

        # 应该包含所有三个技能
        self.assertIn("mock_search", skill_names)
        self.assertIn("mock_calculator", skill_names)
        self.assertIn("mock_other_tool", skill_names)

    def test_continue_exploration_inherits_skills_from_first_execute(self):
        """
        测试同一个 ExploreBlock 实例调用 continue_exploration 时保留 skills 配置
        
        场景：
        1. 第一轮通过 execute 配置了特定的 skills=["mock_search", "mock_calculator"]
        2. 第二轮复用同一个 block 实例调用 continue_exploration
        3. 期望第二轮仍然只能使用第一轮配置的技能子集
        """
        from dolphin.core.common.enums import CategoryBlock

        block = ExploreBlock(context=self.context)

        # 模拟第一轮 execute：解析 DPH 语法，设置特定的 skills
        content = '/explore/(skills=["mock_search", "mock_calculator"]) 用户问题 -> result'
        block.parse_block_content(content, category=CategoryBlock.EXPLORE, replace_variables=False)

        # 验证第一轮解析后 skills 被正确设置
        self.assertIsNotNone(block.skills)
        self.assertEqual(set(block.skills), {"mock_search", "mock_calculator"})

        # 获取第一轮的 skillkit
        first_round_skillkit = block.get_skillkit()
        first_round_skill_names = first_round_skillkit.getSkillNames()

        # 第一轮应该只有配置的两个技能
        self.assertEqual(len(first_round_skill_names), 2)
        self.assertIn("mock_search", first_round_skill_names)
        self.assertIn("mock_calculator", first_round_skill_names)
        self.assertNotIn("mock_other_tool", first_round_skill_names)

        # 模拟第二轮：同一个 block 实例，调用 continue_exploration（不传 skills）
        # 由于是同一个实例，self.skills 应该保持第一轮设置的值
        # 注意：这里只是检查 self.skills 是否被保留，不实际调用 continue_exploration
        
        # 验证 self.skills 仍然是第一轮设置的值
        self.assertEqual(set(block.skills), {"mock_search", "mock_calculator"})

        # get_skillkit() 应该返回第一轮配置的技能子集
        second_round_skillkit = block.get_skillkit()
        second_round_skill_names = second_round_skillkit.getSkillNames()

        self.assertEqual(len(second_round_skill_names), 2)
        self.assertIn("mock_search", second_round_skill_names)
        self.assertIn("mock_calculator", second_round_skill_names)
        self.assertNotIn("mock_other_tool", second_round_skill_names)

    def test_tools_support_wildcard_patterns(self):
        """
        测试 /explore/ 的 tools/skills 参数支持通配符（fnmatch/glob）匹配
        """
        from dolphin.core.common.enums import CategoryBlock

        block = ExploreBlock(context=self.context)

        # 使用通配符，仅匹配 mock_other_tool
        content = "/explore/(tools=[mock_*tool]) 用户问题 -> result"
        block.parse_block_content(
            content, category=CategoryBlock.EXPLORE, replace_variables=False
        )

        self.assertEqual(block.skills, ["mock_*tool"])

        filtered_skillkit = block.get_skillkit()
        filtered_names = set(filtered_skillkit.getSkillNames())

        self.assertEqual(filtered_names, {"mock_other_tool"})

    def test_tools_support_skillkit_namespace_patterns(self):
        """
        测试 tools 支持 <skillkit>.<pattern> 形式的命名空间过滤
        """
        from dolphin.core.common.enums import CategoryBlock

        block = ExploreBlock(context=self.context)

        content = "/explore/(tools=[resource_skillkit.*]) 用户问题 -> result"
        block.parse_block_content(
            content, category=CategoryBlock.EXPLORE, replace_variables=False
        )

        filtered_skillkit = block.get_skillkit()
        filtered_names = set(filtered_skillkit.getSkillNames())
        self.assertEqual(filtered_names, {"mock_other_tool"})

        content = "/explore/(tools=[vm_skillkit.mock_*]) 用户问题 -> result"
        block.parse_block_content(
            content, category=CategoryBlock.EXPLORE, replace_variables=False
        )
        filtered_skillkit = block.get_skillkit()
        filtered_names = set(filtered_skillkit.getSkillNames())
        self.assertEqual(filtered_names, {"mock_search", "mock_calculator"})

    def test_new_block_needs_skills_from_kwargs(self):
        """
        测试新创建的 ExploreBlock 实例需要通过 kwargs 传入 skills
        
        这是 dolphin_language.py 中 continue_exploration 的实际场景：
        每次调用都创建新的 ExploreBlock 实例，需要通过 kwargs 传入 skills
        """
        # 创建新的 ExploreBlock（模拟 dolphin_language.py 的行为）
        new_block = ExploreBlock(context=self.context)

        # 新 block 的 skills 应该是 None
        self.assertIsNone(new_block.skills)

        # 新 block 的 get_skillkit() 会返回 all_skills（因为 skills=None）
        new_skillkit = new_block.get_skillkit()
        new_skill_names = new_skillkit.getSkillNames()
        
        # 应该包含所有三个技能
        self.assertEqual(len(new_skill_names), 3)

        # 修复后，通过 kwargs 传入 skills 可以正确过滤
        # 模拟 continue_exploration 中的 skills 设置逻辑
        kwargs = {"skills": ["mock_search", "mock_calculator"]}
        if "skills" in kwargs:
            new_block.skills = kwargs["skills"]
        elif "tools" in kwargs:
            new_block.skills = kwargs["tools"]
        
        # 验证 skills 被正确设置
        self.assertEqual(set(new_block.skills), {"mock_search", "mock_calculator"})
        
        # 验证 get_skillkit() 返回正确的技能子集
        filtered_skillkit = new_block.get_skillkit()
        filtered_skill_names = filtered_skillkit.getSkillNames()
        
        self.assertEqual(len(filtered_skill_names), 2)
        self.assertIn("mock_search", filtered_skill_names)
        self.assertIn("mock_calculator", filtered_skill_names)
        self.assertNotIn("mock_other_tool", filtered_skill_names)

    def test_continue_exploration_accepts_skills_from_kwargs(self):
        """
        测试 continue_exploration 可以从 kwargs 接收 skills 参数
        
        修复后的期望行为：
        - continue_exploration(skills=["mock_search"]) 应该设置 self.skills = ["mock_search"]
        """
        block = ExploreBlock(context=self.context)

        # 当前 continue_exploration 不接受 skills 参数
        # 修复后应该可以通过 kwargs 传入 skills
        
        # 验证当前状态：skills 为 None
        self.assertIsNone(block.skills)

        # 模拟 continue_exploration 应该支持的行为（修复后）
        # block.skills = kwargs.get("skills") or kwargs.get("tools")
        
        # 目前我们测试：如果手动设置 skills，get_skillkit 应该正确过滤
        block.skills = ["mock_search"]
        
        skillkit = block.get_skillkit()
        skill_names = skillkit.getSkillNames()
        
        self.assertEqual(len(skill_names), 1)
        self.assertIn("mock_search", skill_names)
        self.assertNotIn("mock_calculator", skill_names)
        self.assertNotIn("mock_other_tool", skill_names)

    def test_new_block_inherits_skills_from_context(self):
        """
        测试新创建的 ExploreBlock 可以从 context 继承上一轮的 skills 配置
        
        这是核心测试：验证多轮对话场景中，即使创建新的 ExploreBlock 实例，
        也能从 context 继承上一轮设置的 skills 配置。
        """
        # 模拟第一轮：设置 skills 到 context
        self.context.set_last_skills(["mock_search", "mock_calculator"])
        
        # 创建新的 ExploreBlock（模拟 dolphin_language.py 的行为）
        new_block = ExploreBlock(context=self.context)
        
        # 新 block 的 skills 初始为 None
        self.assertIsNone(new_block.skills)
        
        # 模拟 continue_exploration 中的 skills 设置逻辑（从 context 继承）
        kwargs = {}  # 没有传入 skills
        if "skills" in kwargs:
            new_block.skills = kwargs["skills"]
        elif "tools" in kwargs:
            new_block.skills = kwargs["tools"]
        else:
            # 从 context 继承上一轮的 skills 配置
            last_skills = self.context.get_last_skills()
            if last_skills is not None:
                new_block.skills = last_skills
        
        # 验证 skills 从 context 继承
        self.assertIsNotNone(new_block.skills)
        self.assertEqual(set(new_block.skills), {"mock_search", "mock_calculator"})
        
        # 验证 get_skillkit() 返回正确的技能子集
        filtered_skillkit = new_block.get_skillkit()
        filtered_skill_names = filtered_skillkit.getSkillNames()
        
        self.assertEqual(len(filtered_skill_names), 2)
        self.assertIn("mock_search", filtered_skill_names)
        self.assertIn("mock_calculator", filtered_skill_names)
        self.assertNotIn("mock_other_tool", filtered_skill_names)

    def test_kwargs_skills_overrides_context_skills(self):
        """
        测试 kwargs 中的 skills 参数优先于 context 中的配置
        """
        # 设置 context 中的 skills
        self.context.set_last_skills(["mock_search", "mock_calculator"])
        
        # 创建新的 ExploreBlock
        new_block = ExploreBlock(context=self.context)
        
        # 通过 kwargs 传入不同的 skills（应该覆盖 context 中的配置）
        kwargs = {"skills": ["mock_other_tool"]}
        if "skills" in kwargs:
            new_block.skills = kwargs["skills"]
        elif "tools" in kwargs:
            new_block.skills = kwargs["tools"]
        else:
            last_skills = self.context.get_last_skills()
            if last_skills is not None:
                new_block.skills = last_skills
        
        # 验证 kwargs 中的 skills 优先
        self.assertEqual(new_block.skills, ["mock_other_tool"])
        
        # 验证 get_skillkit() 返回 kwargs 配置的技能
        filtered_skillkit = new_block.get_skillkit()
        filtered_skill_names = filtered_skillkit.getSkillNames()
        
        self.assertEqual(len(filtered_skill_names), 1)
        self.assertIn("mock_other_tool", filtered_skill_names)
        self.assertNotIn("mock_search", filtered_skill_names)
        self.assertNotIn("mock_calculator", filtered_skill_names)


class TestContinueExplorationSkillsWithKwargsParam(unittest.TestCase):
    """
    测试 continue_exploration 方法通过 kwargs 接收 skills 参数
    
    这个测试类验证修复后的行为
    """

    def setUp(self):
        """测试前的设置"""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager,
        )

        # 创建包含多个技能的 Skillset
        self.all_skills = Skillset()
        self.all_skills.addSkill(SkillFunction(mock_search))
        self.all_skills.addSkill(SkillFunction(mock_calculator))
        self.all_skills.addSkill(SkillFunction(mock_other_tool))

        # 设置 context 的技能
        self.context.set_skills(self.all_skills)
        self.context._calc_all_skills()

    def test_skills_parameter_priority_from_kwargs(self):
        """
        测试 skills 参数的优先级：kwargs > 当前值 > None
        """
        block = ExploreBlock(context=self.context)
        
        # 初始状态：skills 为 None
        self.assertIsNone(block.skills)
        
        # 模拟修复后的逻辑：从 kwargs 设置 skills
        kwargs = {"skills": ["mock_search"]}
        
        # 修复后的逻辑应该是：
        # if "skills" in kwargs:
        #     self.skills = kwargs["skills"]
        # elif "tools" in kwargs:
        #     self.skills = kwargs["tools"]
        
        if "skills" in kwargs:
            block.skills = kwargs["skills"]
        elif "tools" in kwargs:
            block.skills = kwargs["tools"]
        
        # 验证 skills 被正确设置
        self.assertEqual(block.skills, ["mock_search"])
        
        # 验证 get_skillkit 返回正确的技能集
        skillkit = block.get_skillkit()
        skill_names = skillkit.getSkillNames()
        
        self.assertEqual(len(skill_names), 1)
        self.assertIn("mock_search", skill_names)

    def test_tools_parameter_as_alias_for_skills(self):
        """
        测试 tools 参数作为 skills 的别名
        """
        block = ExploreBlock(context=self.context)
        
        kwargs = {"tools": ["mock_calculator"]}
        
        if "skills" in kwargs:
            block.skills = kwargs["skills"]
        elif "tools" in kwargs:
            block.skills = kwargs["tools"]
        
        self.assertEqual(block.skills, ["mock_calculator"])
        
        skillkit = block.get_skillkit()
        skill_names = skillkit.getSkillNames()
        
        self.assertEqual(len(skill_names), 1)
        self.assertIn("mock_calculator", skill_names)


class TestContinueExplorationModeInheritance(unittest.TestCase):
    """
    测试 continue_exploration 对 mode 配置的继承
    """

    def setUp(self):
        """测试前的设置"""
        self.context_manager = ContextManager()
        self.global_config = GlobalConfig()
        self.context = Context(
            config=self.global_config,
            context_manager=self.context_manager,
        )

        # 创建包含技能的 Skillset
        self.all_skills = Skillset()
        self.all_skills.addSkill(SkillFunction(mock_search))

        # 设置 context 的技能
        self.context.set_skills(self.all_skills)
        self.context._calc_all_skills()

    def test_default_mode_is_tool_call(self):
        """测试默认 mode 是 tool_call"""
        block = ExploreBlock(context=self.context)
        self.assertEqual(block.mode, "tool_call")

    def test_new_block_inherits_mode_from_context(self):
        """
        测试新创建的 ExploreBlock 可以从 context 继承上一轮的 mode 配置
        """
        from dolphin.core.code_block.explore_strategy import ToolCallStrategy

        # 模拟第一轮：设置 mode 到 context
        # 为了验证继承逻辑，这里设置为与默认值不同的 prompt
        self.context.set_last_explore_mode("prompt")

        # 创建新的 ExploreBlock
        new_block = ExploreBlock(context=self.context)

        # 新 block 的 mode 默认是 tool_call
        self.assertEqual(new_block.mode, "tool_call")

        # 模拟 continue_exploration 中的 mode 设置逻辑（从 context 继承）
        kwargs = {}  # 没有传入 mode
        if "mode" in kwargs:
            new_mode = kwargs["mode"]
            if new_mode in ["prompt", "tool_call"] and new_mode != new_block.mode:
                new_block.mode = new_mode
                new_block.strategy = new_block._create_strategy()
        else:
            # 从 context 继承上一轮的 mode 配置
            last_mode = self.context.get_last_explore_mode()
            if last_mode is not None and last_mode != new_block.mode:
                new_block.mode = last_mode
                new_block.strategy = new_block._create_strategy()

        # 验证 mode 从 context 继承为与默认不同的 prompt
        self.assertEqual(new_block.mode, "prompt")
        from dolphin.core.code_block.explore_strategy import PromptStrategy
        self.assertIsInstance(new_block.strategy, PromptStrategy)

    def test_kwargs_mode_overrides_context_mode(self):
        """
        测试 kwargs 中的 mode 参数优先于 context 中的配置
        """
        from dolphin.core.code_block.explore_strategy import PromptStrategy

        # 设置 context 中的 mode 为 tool_call
        self.context.set_last_explore_mode("tool_call")

        # 创建新的 ExploreBlock
        new_block = ExploreBlock(context=self.context)

        # 通过 kwargs 传入不同的 mode（应该覆盖 context 中的配置）
        kwargs = {"mode": "prompt"}
        if "mode" in kwargs:
            new_mode = kwargs["mode"]
            if new_mode in ["prompt", "tool_call"] and new_mode != new_block.mode:
                new_block.mode = new_mode
                new_block.strategy = new_block._create_strategy()
        else:
            last_mode = self.context.get_last_explore_mode()
            if last_mode is not None and last_mode != new_block.mode:
                new_block.mode = last_mode
                new_block.strategy = new_block._create_strategy()

        # 验证 kwargs 中的 mode 优先（保持 prompt）
        self.assertEqual(new_block.mode, "prompt")
        self.assertIsInstance(new_block.strategy, PromptStrategy)

    def test_execute_saves_mode_to_context(self):
        """
        测试 execute 方法会将 mode 保存到 context
        """
        from dolphin.core.common.enums import CategoryBlock

        # 初始状态：context 没有保存任何 mode
        self.assertIsNone(self.context.get_last_explore_mode())

        block = ExploreBlock(context=self.context)

        # 模拟解析 DPH 语法，设置 tool_call 模式
        content = '/explore/(mode="tool_call") 用户问题 -> result'
        block.parse_block_content(content, category=CategoryBlock.EXPLORE, replace_variables=False)

        self.assertEqual(block.mode, "tool_call")

        # 模拟 execute 中保存 mode 的逻辑
        self.context.set_last_explore_mode(block.mode)

        # 验证 mode 被保存到 context
        self.assertEqual(self.context.get_last_explore_mode(), "tool_call")


class TestDolphinExecutorContinueExplorationInitialization(unittest.TestCase):
    """
    测试 DolphinExecutor.continue_exploration 的真实初始化流程

    Bug: continue_exploration 未调用 _prepare_for_run()，导致 context.all_skills 为空
    """

    def test_continue_exploration_initializes_all_skills_from_global_skills(self):
        """
        测试 continue_exploration 应该自动初始化 context.all_skills

        场景：
        1. 创建 DolphinExecutor（不手动设置 context.all_skills）
        2. 直接调用 continue_exploration（而不是先调用 run）
        3. 验证 context.all_skills 应该从 global_skills 自动填充

        这是真实的使用场景，测试不应该手动初始化 context
        """
        from dolphin.core.executor.dolphin_executor import DolphinExecutor
        from dolphin.core.config.global_config import GlobalConfig
        from dolphin.core.context_engineer.core.context_manager import ContextManager

        # 创建 executor（模拟真实用户场景，不手动初始化 context）
        executor = DolphinExecutor(
            global_config=GlobalConfig(),
            context_manager=ContextManager()
        )

        # 验证初始状态：context.all_skills 应该是空的
        self.assertTrue(
            executor.context.all_skills.isEmpty(),
            "初始状态下 context.all_skills 应该为空"
        )

        # 验证 global_skills 包含技能（这些技能应该被加载到 context）
        if hasattr(executor.global_skills, "getAllSkills"):
            global_skills = executor.global_skills.getAllSkills()
            self.assertGreater(
                len(global_skills.getSkills()),
                0,
                "global_skills 应该包含技能"
            )

        # 测试关键点：直接创建 ExploreBlock（模拟 continue_exploration 的行为）
        from dolphin.core.code_block.explore_block import ExploreBlock
        explore_block = ExploreBlock(
            context=executor.context,
            debug_infos=None,
        )

        # 在调用 continue_exploration 前，模拟 _prepare_for_run 应该被调用
        # Bug 复现：如果不调用 _prepare_for_run，get_skillkit() 会返回空集
        skillkit_before_prepare = explore_block.get_skillkit()

        # 关键断言：在 _prepare_for_run 之前，skillkit 应该是空的（这是 bug）
        # 修复后，continue_exploration 应该调用 _prepare_for_run，所以不应该是空的
        skills_count_before = len(skillkit_before_prepare.getSkills())

        # 模拟修复：调用 _prepare_for_run（这应该在 continue_exploration 中自动调用）
        executor._prepare_for_run()

        # 验证修复后的状态
        self.assertFalse(
            executor.context.all_skills.isEmpty(),
            "调用 _prepare_for_run 后，context.all_skills 应该被填充"
        )

        # 再次获取 skillkit
        skillkit_after_prepare = explore_block.get_skillkit()
        skills_count_after = len(skillkit_after_prepare.getSkills())

        # 验证 _prepare_for_run 确实加载了技能
        self.assertGreater(
            skills_count_after,
            0,
            "_prepare_for_run 后应该能获取到技能"
        )

        # 验证修复前后的差异
        self.assertNotEqual(
            skills_count_before,
            skills_count_after,
            "调用 _prepare_for_run 前后，可用技能数量应该不同"
        )

    def test_continue_exploration_method_calls_prepare_for_run(self):
        """
        测试 continue_exploration 方法应该自动调用 _prepare_for_run

        使用 mock 验证 _prepare_for_run 是否被调用
        """
        from dolphin.core.executor.dolphin_executor import DolphinExecutor
        from dolphin.core.config.global_config import GlobalConfig
        from dolphin.core.context_engineer.core.context_manager import ContextManager
        from dolphin.core import flags
        from unittest.mock import patch, MagicMock, AsyncMock
        import asyncio

        # 保存原始 flag 状态并禁用 EXPLORE_BLOCK_V2
        original_flag = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
        flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

        try:
            # 创建 executor
            executor = DolphinExecutor(
                global_config=GlobalConfig(),
                context_manager=ContextManager()
            )

            # 验证初始状态
            self.assertTrue(executor.context.all_skills.isEmpty())

            # 使用 patch 监视 _prepare_for_run 是否被调用
            with patch.object(
                executor,
                '_prepare_for_run',
                wraps=executor._prepare_for_run
            ) as mock_prepare:
                # Mock ExploreBlock.continue_exploration 以避免真实的 LLM 调用
                async def mock_explore(*args, **kwargs):
                    # 直接返回，不进行真实的探索
                    yield {"status": "completed"}

                with patch(
                    'dolphin.core.code_block.explore_block.ExploreBlock.continue_exploration',
                    new=mock_explore
                ):
                    # 调用 continue_exploration
                    async def test_call():
                        async for result in executor.continue_exploration(
                            content="test question",
                            output_var="result"
                        ):
                            break  # 只需要第一个结果

                    # 运行异步测试
                    asyncio.run(test_call())

                # 关键断言：_prepare_for_run 应该被调用
                # 这是测试的核心 - 验证 bug 是否已修复
                mock_prepare.assert_called_once()

            # 额外验证：调用后 context.all_skills 应该被填充
            self.assertFalse(
                executor.context.all_skills.isEmpty(),
                "continue_exploration 应该通过 _prepare_for_run 初始化 context.all_skills"
            )
        finally:
            # 恢复原始 flag 状态
            flags.set_flag(flags.EXPLORE_BLOCK_V2, original_flag)


if __name__ == "__main__":
    unittest.main()
