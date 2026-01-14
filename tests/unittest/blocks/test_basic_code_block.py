#!/usr/bin/env python3
"""
BasicCodeBlock 类的单元测试
"""

import unittest


from dolphin.core.context.context import Context


from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.enums import CategoryBlock


class TestBasicCodeBlock(unittest.TestCase):
    """BasicCodeBlock 的单元测试类"""

    def setUp(self):
        """测试前的设置"""
        self.block = BasicCodeBlock(context=Context())

    def test_load_dynamic_tools_should_not_depend_on_deprecated_namespace(self):
        """
        回归用例：
        _load_dynamic_tools 内部存在对 `DolphinLanguageSDK.skill.*` 的硬编码导入，
        但本仓库的 DolphinLanguageSDK 仅为兼容层（无 skill 子包），会触发 ModuleNotFoundError。

        该用例用于显式覆盖该分支：修复导入路径前应失败，修复后应通过。
        """
        block = BasicCodeBlock(context=Context())
        try:
            block._load_dynamic_tools({"_dynamic_tools": []})
        except Exception as e:
            self.fail(f"_load_dynamic_tools 不应依赖 DolphinLanguageSDK.skill.*，但触发异常: {e}")

    def test_find_matching_paren(self):
        """测试匹配括号功能"""
        # 测试简单括号匹配
        self.assertEqual(self.block.find_matching_paren("(hello)", 0), 6)
        self.assertEqual(self.block.find_matching_paren("test(hello)", 4), 10)

        # 测试嵌套括号
        self.assertEqual(self.block.find_matching_paren("((nested))", 0), 9)
        self.assertEqual(self.block.find_matching_paren("(a(b)c)", 0), 6)

        # 测试未匹配的括号
        self.assertEqual(self.block.find_matching_paren("(unmatched", 0), -1)

        # 测试复杂情况
        self.assertEqual(self.block.find_matching_paren("func(a, b(c, d), e)", 4), 18)

        # 测试括号不匹配
        self.assertEqual(self.block.find_matching_paren("(unmatched", 0), -1)

        # 测试括号不匹配，字符串中
        self.assertEqual(self.block.find_matching_paren("('(unmatched')", 0), 13)

        # 测试长字符串
        str = r"""\n角色定位：\n1. 你是一个数据分析的专家，能够完成数据分析任务\n2. 你能熟练进行数据分析任务的分解、决策并完成任务，你也可以和用户自然的交互\n3. 你要按照用户提问的分析维度进行汇总，如时间、品类等\n4. 你可以生成代码在沙箱中执行\n5. 你能够对你在数据详细的解读，并给出洞察\n\n重要原则：\n1. 严禁捏造工具结果、编造数据、模拟工具输出、严禁模拟代码的结果，一定按要求生成工具调用参数\n2. 如果用户没有明确要求画图，则不要画图\n3. 输出答案时，要输出工具的结果和一条数据样例，但是要在注释中，格式为 \\<!-- result_cache_key: XX, data_sample: YY --\\>, 后续工具会使用。后续的工具在使用时，务必要能正确使用\n4. 如果用户要画图，一定要用 json2plot，不要生成代码画图，json2plot 的参数要生成一定要参考 data_sample\n5. 不需要对显示 json2plot 工具的参数和输出，前端会展示图，展示完成后对结果进行分析、解读和提出下一步的而建议\n6. 输出你的步骤，并在调用工具前输出你的思考\n7. 数值计算必须写代码并执行\n8. 仔细分析上下文，识别用户的话题切换\n9. 你的上下文环境已经是 markdown 了，所以不需要输输出类型 ```xxx``` 的内容\n10. 如果工具执行错误，不要反复执行\n\nsandbox 工具执行代码注意事项:\n1. Python 代码的结果要从 stderr, stdout, return_code 来判断结果\n\n关于业务的提示：\n1. 同比\t同比是指将本期数据与上一年同期数据进行比较，用于反映长期趋势，消除季节性因素的影响\t同比增长率 = （本期数 - 同期数） / 同期数 × 100%\n2. 环比\t环比是指将本期数据与上一相邻统计周期（如上个月或上一季度）进行比较，用于反映短期变化\t环比增长率 = （本期数 - 上期数） / 上期数 × 100%\n3. 异常波动\t使用同比和环比，以2025年12个月为窗口，分别计算同比和环比的历史均值和标准差\t\"异常高增长 = 本期同比（或环比） > 历史均值 + 2 × 标准差\n4. 异常低增长 = 本期同比（或环比） < 历史均值 - 2 × 标准差\n5. 正常波动 = 历史均值 ± 2 × 标准差范围内\"\n6. 爆发性生长\t使用同比和环比，以2025年12个月为窗口，分别计算同比和环比的历史均值和标准差\t爆发性生长 = 本期同比（或环比） > 历史均值 + 3 × 标准差\n7. Z分数（Z-score）异常检测法\t\"平均值：计算平均水平\n8. 标准差：衡量销量分散程度的指标，标准差越大，说明各系列销量差异越大\n\n9. Z分数 = \(某XX销量 - 平均销量\) / 标准差\n10. 某XX的销量偏离平均值有多少个标准差\n\n11. Z分数 > 2：销量异常偏高（高于平均值2个标准差以上）\n12. Z分数 < -2：销量异常偏低（低于平均值2个标准差以上）\n13. -2 ≤ Z分数 ≤ 2：销量在正常范围内\n\n在正态分布中：\n1. 约68%的数据落在平均值±1个标准差范围内\n2. 约95%的数据落在平均值±2个标准差范围内\n3. 约99.7%的数据落在平均值±3个标准差范围内\n4. 选择2作为阈值意味着我们认为大约5%的极端情况为 *异常*，这是统计学中常用的判断标准。\"\n\n我们可以分析的数据资源，如果用到请参考: {'result': {'data_sources': {'detail': [{'en_name': 't_sales', 'description': '', 'ddl': \"CREATE TABLE vdm_mysql_beqctvol.default.t_sales\\n(\\narea_1_region VARCHAR comment '大区名称'\\narea_2_province VARCHAR comment '统计省区名称'\\narea_3_district VARCHAR comment '片区'\\nbo_1_bu VARCHAR comment 'bo1事业部'\\nbo_2_category VARCHAR comment 'bo2品类'\\nbo_3_series VARCHAR comment 'bo3系列'\\nbrand VARCHAR comment '品牌'\\ndate DATETIME comment '日期'\\noperation_dim VARCHAR comment '经营维度'\\nprd_class VARCHAR comment '大类'\\nrowid INT comment '行序号'\\nsales_std DOUBLE comment '销量(标准化）'\\ntarget_channel VARCHAR comment '目标渠道'\\ntarget_std DOUBLE comment '目标(标准化）\\n);\\n\", 'en2cn': {'bo_2_category': 'bo2品类', 'brand': '品牌', 'rowid': '行序号', 'area_3_district': '片区', 'prd_class': '大类', 'sales_std': '销量(标准化）', 'area_1_region': '大区名称', 'bo_3_series': 'bo3系列', 'operation_dim': '经营维度', 'area_2_province': '统计省区名称', 'bo_1_bu': 'bo1事业部', 'date': '日期', 'target_channel': '目标渠道', 'target_std': '目标(标准化）'}, 'path': 'vdm_mysql_beqctvol.default.t_sales', 'id': 'c3f1878a-f23a-4c18-baec-7f6019131357', 'name': '立白销量目标宽表'}], 'view_schema_infos': {'c3f1878a-f23a-4c18-baec-7f6019131357': 'vdm_mysql_beqctvol'}}}}\n"""
        str_test = f'(tools=[executeSQL, _python, _search], model="Tome-Max", system_prompt="{str}")'
        self.assertNotEqual(self.block.find_matching_paren(str_test, 0), -1)

        # 测试单引号
        str_test = "(tools=[executeSQL, _python, _search], model='Tome-Max', system_prompt='xxx') -> result"
        self.assertEqual(self.block.find_matching_paren(str_test, 0), 76)
        # 测试双引号
        str_test = '(tools=[executeSQL, _python, _search], model="Tome-Max", system_prompt="xxx") -> result'
        self.assertEqual(self.block.find_matching_paren(str_test, 0), 76)

        # # 测试连续单引号
        str_test = "(tools=[], system_prompt='', history=True) 你好 -> result"
        self.assertEqual(self.block.find_matching_paren(str_test, 0), 41)
        # # 测试连续双引号
        str_test = "(tools=[], system_prompt='', history=True) 你好 -> result"
        self.assertEqual(self.block.find_matching_paren(str_test, 0), 41)

        # 测试单双引号嵌套(该用例测试不过)
        # str_test = "(tools=[], system_prompt='" "', history=True) 你好 -> result"
        # self.assertEqual(self.block.find_matching_paren(str_test, 0), 61)
        # 测试字符串包含\n
        str_test = """(tools=[executeSQL, _python, _search], model="Tome-Max", system_prompt="_beqctvol\n'}}}}")"""
        self.assertEqual(self.block.find_matching_paren(str_test, 0), 88)

    def test_split_parameters_smartly(self):
        """测试智能参数分割功能"""
        # 简单参数分割
        result = self.block.split_parameters_smartly("a=1, b=2, c=3")
        self.assertEqual(result, ["a=1", "b=2", "c=3"])

        # 包含引号的参数
        result = self.block.split_parameters_smartly('a="hello", b="world, test", c=3')
        self.assertEqual(result, ['a="hello"', 'b="world, test"', "c=3"])

        # 包含方括号的参数
        result = self.block.split_parameters_smartly('tools=[a,b,c], model="gpt-4"')
        self.assertEqual(result, ["tools=[a,b,c]", 'model="gpt-4"'])

        # 包含大括号的参数
        result = self.block.split_parameters_smartly(
            'params={"key":"value,test"}, mode=simple'
        )
        self.assertEqual(result, ['params={"key":"value,test"}', "mode=simple"])

        # 复杂嵌套情况
        result = self.block.split_parameters_smartly(
            'a=[1,2,3], b={"x":"y,z"}, c="simple"'
        )
        self.assertEqual(result, ["a=[1,2,3]", 'b={"x":"y,z"}', 'c="simple"'])

        # 空字符串和空格处理
        result = self.block.split_parameters_smartly("")
        self.assertEqual(result, [])

        result = self.block.split_parameters_smartly("   ")
        self.assertEqual(result, [])

    def test_parse_tools_parameter(self):
        """测试工具参数解析功能"""
        # 带引号的工具列表
        result = self.block.parse_tools_parameter('["tool1", "tool2", "tool3"]')
        self.assertEqual(result, ["tool1", "tool2", "tool3"])

        # 不带引号的工具列表
        result = self.block.parse_tools_parameter("[tool1, tool2, tool3]")
        self.assertEqual(result, ["tool1", "tool2", "tool3"])

        # 混合引号的工具列表
        result = self.block.parse_tools_parameter('["tool1", tool2, "tool3"]')
        self.assertEqual(result, ["tool1", "tool2", "tool3"])

        # 单个工具
        result = self.block.parse_tools_parameter("single_tool")
        self.assertEqual(result, ["single_tool"])

        # 逗号分隔的工具
        result = self.block.parse_tools_parameter("tool1, tool2, tool3")
        self.assertEqual(result, ["tool1", "tool2", "tool3"])

        # 空参数
        result = self.block.parse_tools_parameter("")
        self.assertEqual(result, [])

        result = self.block.parse_tools_parameter("[]")
        self.assertEqual(result, [])

    def test_parse_parameter_value(self):
        """测试参数值解析功能"""
        # 字符串值
        result = self.block.parse_parameter_value("text", '"hello world"')
        self.assertEqual(result, "hello world")

        result = self.block.parse_parameter_value("text", "'hello world'")
        self.assertEqual(result, "hello world")

        # JSON 对象
        result = self.block.parse_parameter_value(
            "config", '{"key": "value", "num": 123}'
        )
        self.assertEqual(result, {"key": "value", "num": 123})

        # JSON 数组
        result = self.block.parse_parameter_value("list", '[1, 2, 3, "test"]')
        self.assertEqual(result, [1, 2, 3, "test"])

        # 数值类型
        result = self.block.parse_parameter_value("count", "123")
        self.assertEqual(result, 123)

        result = self.block.parse_parameter_value("price", "12.34")
        self.assertEqual(result, 12.34)

        # 布尔值
        result = self.block.parse_parameter_value("flag", "true")
        self.assertEqual(result, True)

        result = self.block.parse_parameter_value("flag", "false")
        self.assertEqual(result, False)

        # 特殊参数类型
        result = self.block.parse_parameter_value("history", "true")
        self.assertEqual(result, True)

        result = self.block.parse_parameter_value("tools", '["tool1", "tool2"]')
        self.assertEqual(result, ["tool1", "tool2"])

    def test_parse_parameters_from_string(self):
        """测试参数字符串解析功能"""
        # 简单参数
        context = Context()
        context.set_variable("user_input", "the_user_input")
        self.block = BasicCodeBlock(context=context)  # 重置

        result = self.block.parse_parameters_from_string(
            'model="gpt-4", history=true, count=5'
        )
        expected = {"model": "gpt-4", "history": True, "count": 5}
        self.assertEqual(result, expected)

        # 包含 JSON 的参数
        result = self.block.parse_parameters_from_string(
            'config={"key":"value"}, tools=["tool1", "tool2"]'
        )
        expected = {"config": {"key": "value"}, "tools": ["tool1", "tool2"]}
        self.assertEqual(result, expected)

        # 包含变量引用的参数
        result = self.block.parse_parameters_from_string(
            'query=$user_input, model="gpt-4"'
        )
        expected = {
            "query": "the_user_input",
            "model": "gpt-4",
        }
        self.assertEqual(result, expected)

        # 空参数字符串
        result = self.block.parse_parameters_from_string("")
        self.assertEqual(result, {})

    def test_parse_tool_parameters_from_string(self):
        """测试工具参数解析功能"""
        context = Context()
        context.set_variable("user_input", "the_user_input")
        self.block = BasicCodeBlock(context=context)  # 重置

        # 多行参数处理
        params_str = """
            query=$user_input,
            config={"company":"Tencent","quarter":"202304"},
            count=123
        """
        result = self.block.parse_tool_parameters_from_string(params_str)
        expected = {
            "query": "the_user_input",
            "config": {"company": "Tencent", "quarter": "202304"},
            "count": 123,
        }
        self.assertEqual(result, expected)

    def test_parse_block_content_normal_format(self):
        """测试普通块格式解析"""
        # Judge 块格式
        content = '/judge/(model="gpt-4", history=true) 判断用户意图 -> result'
        self.block.parse_block_content(content, CategoryBlock.JUDGE)

        self.assertEqual(self.block.category, CategoryBlock.JUDGE)
        self.assertEqual(self.block.content, "判断用户意图")
        self.assertEqual(self.block.assign_type, "->")
        self.assertEqual(self.block.output_var, "result")
        self.assertEqual(self.block.params, {"model": "gpt-4", "history": True})

        # Explore 块格式
        content = '/explore/(tools=["tool1", "tool2"]) 探索问题 >> output'
        self.block = BasicCodeBlock(context=None)  # 重置
        self.block.parse_block_content(content, CategoryBlock.EXPLORE)

        self.assertEqual(self.block.category, CategoryBlock.EXPLORE)
        self.assertEqual(self.block.content, "探索问题")
        self.assertEqual(self.block.assign_type, ">>")
        self.assertEqual(self.block.output_var, "output")
        self.assertEqual(
            self.block.params, {"tools": ["tool1", "tool2"], "history": False}
        )

        # 没有参数的块
        content = "/prompt/ 简单提示 -> result"
        self.block = BasicCodeBlock(context=None)  # 重置
        self.block.parse_block_content(content, CategoryBlock.PROMPT)

        self.assertEqual(self.block.category, CategoryBlock.PROMPT)
        self.assertEqual(self.block.content, "简单提示")
        self.assertEqual(self.block.params, {"history": False})

    def test_parse_block_content_tool_format(self):
        """测试工具块格式解析"""
        # 简单工具调用
        content = '@websearch(query="hello world") -> result'
        self.block.parse_block_content(content)

        self.assertEqual(self.block.category, CategoryBlock.TOOL)
        self.assertEqual(self.block.content, "websearch")
        self.assertEqual(self.block.assign_type, "->")
        self.assertEqual(self.block.output_var, "result")
        self.assertEqual(self.block.params, {"query": "hello world"})

        # 包含变量引用的工具调用
        content = '@llm_tagger(statement=$query, tags=["tag1", "tag2"]) -> result'

        context = Context()
        context.set_variable("query", "the_query")
        context.runtime_graph = None

        self.block = BasicCodeBlock(context=context)  # 重置
        self.block.parse_block_content(content)

        self.assertEqual(self.block.category, CategoryBlock.TOOL)
        self.assertEqual(self.block.content, "llm_tagger")
        self.assertEqual(self.block.params["statement"], "the_query")
        self.assertEqual(self.block.params["tags"], ["tag1", "tag2"])

        # 复杂参数的工具调用
        content = '@生成SQL查询语句(dimensions=$parser_result.dimensions, params={"company":"Tencent","quarter":"202304"}) -> res'

        context = Context()
        context.set_variable("parser_result", {"dimensions": "the_dimensions"})
        context.runtime_graph = None

        self.block = BasicCodeBlock(context=context)  # 重置
        self.block.parse_block_content(content)

        self.assertEqual(self.block.category, CategoryBlock.TOOL)
        self.assertEqual(self.block.content, "生成SQL查询语句")
        self.assertEqual(
            self.block.params["dimensions"],
            "the_dimensions",
        )
        self.assertEqual(
            self.block.params["params"], {"company": "Tencent", "quarter": "202304"}
        )

    def test_parse_block_content_error_cases(self):
        """测试解析错误情况"""
        # 普通格式缺少 category
        with self.assertRaises(ValueError) as context:
            self.block.parse_block_content("/judge/ test -> result")
        self.assertIn("category is required", str(context.exception))

        # 无效的工具格式
        with self.assertRaises(ValueError) as context:
            self.block.parse_block_content("@invalid_format")
        self.assertIn("Invalid tool call format", str(context.exception))

        # 括号不匹配
        with self.assertRaises(ValueError) as context:
            self.block.parse_block_content(
                "/judge/(unclosed test -> result", CategoryBlock.JUDGE
            )
        self.assertIn("Unmatched parentheses", str(context.exception))

        # 缺少赋值操作符
        with self.assertRaises(ValueError) as context:
            self.block.parse_block_content(
                "/judge/ test without assignment", CategoryBlock.JUDGE
            )
        self.assertIn("Invalid block format", str(context.exception))

    def test_get_parameter_with_default(self):
        """测试获取参数默认值功能"""
        params = {"key1": "value1", "key2": 123}

        # 存在的参数
        result = self.block.get_parameter_with_default(params, "key1", "default")
        self.assertEqual(result, "value1")

        # 不存在的参数，返回默认值
        result = self.block.get_parameter_with_default(params, "key3", "default_value")
        self.assertEqual(result, "default_value")

        # None 默认值
        result = self.block.get_parameter_with_default(params, "key4", None)
        self.assertIsNone(result)

    def test_edge_cases(self):
        """测试边界情况"""
        # 空内容
        with self.assertRaises(ValueError):
            self.block.parse_block_content("", CategoryBlock.JUDGE)

        # 只有空格
        with self.assertRaises(ValueError):
            self.block.parse_block_content("   ", CategoryBlock.JUDGE)

        # 特殊字符处理
        content = '@tool-name_123(param_1="test value", param-2=456) -> result_var'
        self.block.parse_block_content(content)
        self.assertEqual(self.block.content, "tool-name_123")
        self.assertEqual(self.block.output_var, "result_var")

    def test_system_prompt_truncation_issue(self):
        """测试 system_prompt 截断问题

        当变量值包含逗号等特殊字符时，确保参数解析不会被截断
        测试场景：变量值 "hello, world" 包含逗号，应该被正确解析而不是被截断为 "hello"
        """
        from unittest.mock import Mock

        # 创建 mock context
        mock_context = Mock()

        # 设置变量识别的 mock：当识别到 $result 时返回其位置信息
        def mock_recognize_variable(text):
            if "$result" in text:
                start_idx = text.find("$result")
                end_idx = start_idx + len("$result")
                return [("$result", (start_idx, end_idx))]
            return []

        mock_context.recognize_variable.side_effect = mock_recognize_variable
        mock_context.get_variable_type.return_value = "hello, world"

        # 创建 block 并解析包含变量的内容
        self.block = BasicCodeBlock(context=mock_context)
        content = "/prompt/(system_prompt=$result)1+1->final"

        # 解析 block 内容
        self.block.parse_block_content(content, CategoryBlock.PROMPT)

        # 验证核心结果：system_prompt 应该是完整的值，不被截断
        self.assertEqual(self.block.params["system_prompt"], "hello, world")
        self.assertEqual(self.block.system_prompt, "hello, world")

        # 验证其他基本属性
        self.assertEqual(self.block.category, CategoryBlock.PROMPT)
        self.assertEqual(self.block.content, "1+1")
        self.assertEqual(self.block.output_var, "final")

    def test_variable_with_special_characters(self):
        """测试包含各种特殊字符的变量值

        确保包含括号、方括号、大括号、等号等特殊字符的变量值都能被正确处理
        """
        from unittest.mock import Mock

        test_cases = [
            ("function(param)", "包含圆括号"),
            ("array[0]", "包含方括号"),
            ("{key: value}", "包含大括号"),
            ("key=value", "包含等号"),
            ("multi, params, here", "包含多个逗号"),
            ("complex(param)[0]={value}", "包含多种特殊字符"),
        ]

        for variable_value, description in test_cases:
            with self.subTest(value=variable_value, desc=description):
                # 创建 mock context
                mock_context = Mock()

                def mock_recognize_variable(text):
                    if "$test_var" in text:
                        start_idx = text.find("$test_var")
                        end_idx = start_idx + len("$test_var")
                        return [("$test_var", (start_idx, end_idx))]
                    return []

                mock_context.recognize_variable.side_effect = mock_recognize_variable
                mock_context.get_variable_type.return_value = variable_value

                # 创建 block 并解析
                block = BasicCodeBlock(context=mock_context)
                content = "/prompt/(system_prompt=$test_var)content->result"

                # 解析 block 内容
                block.parse_block_content(content, CategoryBlock.PROMPT)

                # 验证变量值没有被截断或错误解析
                self.assertEqual(
                    block.params["system_prompt"],
                    variable_value,
                    f"Failed for {description}: {variable_value}",
                )
                self.assertEqual(
                    block.system_prompt,
                    variable_value,
                    f"Failed for {description}: {variable_value}",
                )

    def test_variable_with_word_apostrophe_in_params(self):
        """测试变量值包含词内撇号（user's）时的参数解析

        变量替换发生在括号匹配和参数分割之前；若把词内撇号当作字符串引号，会导致：
        - find_matching_paren 无法正确找到 ')'，抛出 Unmatched parentheses
        - split_parameters_smartly 无法在后续 ',' 处分割参数
        """
        from unittest.mock import Mock

        mock_context = Mock()

        def mock_recognize_variable(text):
            if "$sys" in text:
                start_idx = text.find("$sys")
                end_idx = start_idx + len("$sys")
                return [("$sys", (start_idx, end_idx))]
            return []

        mock_context.recognize_variable.side_effect = mock_recognize_variable
        mock_context.get_variable_type.return_value = (
            "You must follow the user's request.\nNo extra steps."
        )

        block = BasicCodeBlock(context=mock_context)
        content = '/prompt/(system_prompt=$sys, model="v3") do -> result'
        block.parse_block_content(content, CategoryBlock.PROMPT)

        self.assertEqual(block.params["model"], "v3")
        self.assertIn("user's", block.params["system_prompt"])

    def test_initialization(self):
        """测试初始化"""
        block = BasicCodeBlock(context=None)
        self.assertIsNone(block.category)
        self.assertEqual(block.params, {})
        self.assertIsNone(block.content)
        self.assertIsNone(block.assign_type)
        self.assertIsNone(block.output_var)

    def test_tools_parameter_syntax_error(self):
        """测试 tools 参数语法错误是否抛出 SyntaxError"""

        # 测试 parse_tools_parameter 方法的直接调用
        tools_values = [
            "[tool1, tool2",  # 缺少右括号
            '[tool1, "tool2"',  # 缺少右括号，含引号
            '["tool1", tool2',  # 缺少右括号，混合引号
            "[",  # 只有左括号
            '["tool1", "tool2"',  # 缺少右括号，双引号
            "[tool1, 'tool2'",  # 缺少右括号，混合引号类型
        ]

        for tools_value in tools_values:
            with self.subTest(tools_value=tools_value):
                # 测试 parse_tools_parameter 方法直接抛出 SyntaxError
                with self.assertRaises(SyntaxError) as context:
                    self.block.parse_tools_parameter(tools_value)

                self.assertIn("Unmatched brackets", str(context.exception))
                print(
                    f"✓ tools_value '{tools_value}' correctly raised: {context.exception}"
                )

        # 测试在完整的 block 解析上下文中的错误处理
        full_param_cases = [
            "tools=[tool1, tool2",  # 完整参数字符串
            'tools=[tool1, "tool2"',
            'tools=["tool1", tool2',
            "tools=[",
        ]

        for param_case in full_param_cases:
            with self.subTest(param_case=param_case):
                # 测试在完整的解析上下文中
                with self.assertRaises(SyntaxError) as context:
                    content = f"/explore/({param_case}) test content -> result"
                    self.block.parse_block_content(content, CategoryBlock.EXPLORE)

                self.assertIn("Unmatched brackets", str(context.exception))
                print(
                    f"✓ Full param '{param_case}' correctly raised: {context.exception}"
                )

    def test_tools_parameter_quote_syntax_error(self):
        """测试 tools 参数引号语法错误"""

        # 测试引号不匹配的情况
        quote_error_cases = [
            '["tool1", "tool2]',  # 缺少右引号
            "[tool1', 'tool2']",  # 混合引号错误
        ]

        for case in quote_error_cases:
            with self.subTest(case=case):
                # 应该抛出语法错误
                with self.assertRaises(SyntaxError) as context:
                    self.block.parse_tools_parameter(case)

                self.assertIn("Unmatched", str(context.exception))
                print(
                    f"✓ Quote error case '{case}' correctly raised: {context.exception}"
                )

        # 测试有效的混合引号情况
        valid_mixed_cases = [
            "[\"tool1\", 'tool2']",  # 混合引号但语法正确
            "['tool1', \"tool2\"]",  # 反向混合引号
        ]

        for case in valid_mixed_cases:
            with self.subTest(case=case):
                # 这些应该正常解析
                result = self.block.parse_tools_parameter(case)
                self.assertEqual(result, ["tool1", "tool2"])
                print(f"✓ Valid mixed quote case '{case}' parsed correctly: {result}")

    def test_tools_parameter_edge_cases(self):
        """测试 tools 参数的边界情况"""

        # 测试有效的复杂情况
        valid_cases = [
            ("[]", []),  # 空数组
            ('[""]', []),  # 空字符串工具（应该被过滤掉）
            ('["tool1"]', ["tool1"]),  # 单个工具
            ('["tool1", "tool2", "tool3"]', ["tool1", "tool2", "tool3"]),  # 多个工具
            (
                '["tool with spaces", "tool-with-dashes"]',
                ["tool with spaces", "tool-with-dashes"],
            ),  # 复杂工具名
            ("[tool1, tool2]", ["tool1", "tool2"]),  # 无引号
            ("tool1,tool2,tool3", ["tool1", "tool2", "tool3"]),  # 纯逗号分隔
            ("single_tool", ["single_tool"]),  # 单个工具名
        ]

        for input_val, expected in valid_cases:
            with self.subTest(input_val=input_val):
                result = self.block.parse_tools_parameter(input_val)
                self.assertEqual(result, expected)
                print(f"✓ Valid case '{input_val}' -> {result}")

        # 测试更多错误情况
        error_cases = [
            ("[tool1, tool2, tool3",),  # 长列表缺少右括号
            ('["tool1", "tool2", "tool3"',),  # 长列表缺少右括号
            ('[tool1"',),  # 畸形引号
        ]

        for case_tuple in error_cases:
            case = case_tuple[0]
            with self.subTest(case=case):
                with self.assertRaises(SyntaxError) as context:
                    self.block.parse_tools_parameter(case)
                print(f"✓ Error case '{case}' correctly raised: {context.exception}")

    def test_tool_block_category(self):
        """测试工具块的 category 设置"""
        # 测试工具块是否正确设置了 CategoryBlock.TOOL
        content = '@test_tool(param="value") -> result'
        self.block.parse_block_content(content)

        # 验证工具块的 category 是 TOOL
        self.assertEqual(self.block.category, CategoryBlock.TOOL)

        # 验证其他属性也设置正确
        self.assertEqual(self.block.content, "test_tool")
        self.assertEqual(self.block.params, {"param": "value"})
        self.assertEqual(self.block.assign_type, "->")
        self.assertEqual(self.block.output_var, "result")

        # 测试中文工具名
        content = '@中文工具名(param="值") -> 结果'
        self.block = BasicCodeBlock(context=None)  # 重置
        self.block.parse_block_content(content)

        self.assertEqual(self.block.category, CategoryBlock.TOOL)
        self.assertEqual(self.block.content, "中文工具名")
        self.assertEqual(self.block.params, {"param": "值"})
        self.assertEqual(self.block.output_var, "结果")


if __name__ == "__main__":
    # 设置详细的测试输出
    unittest.main(verbosity=2)
