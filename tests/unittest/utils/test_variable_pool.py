#!/usr/bin/env python3
"""
VariablePool 类的单元测试
"""

import unittest

from dolphin.core.context.variable_pool import (
    VariablePool,
    convert_object_to_dict_access,
)
from dolphin.core.common.types import Var, SourceType
from dolphin.core.context.var_output import VarOutput


class TestVariablePool(unittest.TestCase):
    """VariablePool 的单元测试类"""

    def setUp(self):
        """测试前的设置"""
        self.pool = VariablePool()

    def test_init_variables(self):
        """测试初始化变量功能"""
        variables = {"var1": "value1", "var2": 42, "var3": [1, 2, 3]}
        self.pool.init_variables(variables)

        self.assertTrue(self.pool.contain_var("var1"))
        self.assertTrue(self.pool.contain_var("var2"))
        self.assertTrue(self.pool.contain_var("var3"))

        self.assertEqual(self.pool.get_var_value("var1"), "value1")
        self.assertEqual(self.pool.get_var_value("var2"), 42)
        self.assertEqual(self.pool.get_var_value("var3"), [1, 2, 3])

    def test_contain_var(self):
        """测试变量存在检查功能"""
        self.pool.set_var("test_var", "test_value")

        self.assertTrue(self.pool.contain_var("test_var"))
        self.assertFalse(self.pool.contain_var("non_existent"))

    def test_get_var(self):
        """测试获取变量对象功能"""
        self.pool.set_var("test_var", "test_value")
        var = self.pool.get_var("test_var")

        self.assertIsInstance(var, Var)
        self.assertEqual(var.value, "test_value")

        # 测试不存在的变量
        self.assertIsNone(self.pool.get_var("non_existent"))

    def test_get_var_value(self):
        """测试获取变量值功能"""
        self.pool.set_var("test_var", "test_value")

        self.assertEqual(self.pool.get_var_value("test_var"), "test_value")
        self.assertIsNone(self.pool.get_var_value("non_existent"))

    def test_set_var_with_value(self):
        """测试设置变量值功能"""
        self.pool.set_var("test1", "string_value")
        self.pool.set_var("test2", 123)
        self.pool.set_var("test3", [1, 2, 3])

        self.assertEqual(self.pool.get_var_value("test1"), "string_value")
        self.assertEqual(self.pool.get_var_value("test2"), 123)
        self.assertEqual(self.pool.get_var_value("test3"), [1, 2, 3])

    def test_set_var_with_var_object(self):
        """测试设置Var对象功能"""
        var_obj = Var("test_value")
        self.pool.set_var("test_var", var_obj)

        self.assertEqual(self.pool.get_var_value("test_var"), "test_value")

    def test_set_var_output(self):
        """测试设置输出变量功能"""
        self.pool.set_var_output(
            "output_var", "output_value", SourceType.SKILL, {"tool": "test_tool"}
        )

        var = self.pool.get_var("output_var")
        self.assertIsInstance(var, VarOutput)
        self.assertEqual(var.value, "output_value")
        self.assertEqual(var.source_type, SourceType.SKILL)
        self.assertEqual(var.skill_info, {"tool": "test_tool"})

    def test_delete_var(self):
        """测试删除变量功能"""
        self.pool.set_var("test_var", "test_value")
        self.assertTrue(self.pool.contain_var("test_var"))

        self.pool.delete_var("test_var")
        self.assertFalse(self.pool.contain_var("test_var"))

        # 删除不存在的变量不应该报错
        self.pool.delete_var("non_existent")

    def test_clear(self):
        """测试清空变量池功能"""
        self.pool.set_var("var1", "value1")
        self.pool.set_var("var2", "value2")

        self.pool.clear()

        self.assertFalse(self.pool.contain_var("var1"))
        self.assertFalse(self.pool.contain_var("var2"))

    def test_get_all_variables(self):
        """测试获取所有变量功能"""
        self.pool.set_var("var1", "value1")
        self.pool.set_var("var2", 42)

        all_vars = self.pool.get_all_variables()

        self.assertIn("var1", all_vars)
        self.assertIn("var2", all_vars)
        # 对于普通Var对象，to_dict()直接返回值
        self.assertEqual(all_vars["var1"], "value1")
        self.assertEqual(all_vars["var2"], 42)

    def test_keys(self):
        """测试获取变量名列表功能"""
        self.pool.set_var("var1", "value1")
        self.pool.set_var("var2", "value2")

        keys = list(self.pool.keys())
        self.assertIn("var1", keys)
        self.assertIn("var2", keys)

    def test_get_variable_type_simple_var(self):
        """测试简单变量的get_variable_type功能"""
        # 设置测试变量
        self.pool.set_var("simple_var", "simple_value")
        self.pool.set_var("number_var", 123)
        self.pool.set_var("bool_var", True)

        # 测试简单变量获取
        self.assertEqual(self.pool.get_variable_type("$simple_var"), "simple_value")
        self.assertEqual(self.pool.get_variable_type("$number_var"), 123)
        self.assertEqual(self.pool.get_variable_type("$bool_var"), True)

    def test_get_variable_type_dict_access(self):
        """测试字典访问的get_variable_type功能"""
        # 设置测试数据
        test_dict = {
            "text": "hello world",
            "nested": {"value": 42},
            "deep": {"level1": {"level2": "deep_value"}},
        }
        self.pool.set_var("dict_var", test_dict)

        # 测试字典访问
        self.assertEqual(self.pool.get_variable_type("$dict_var.text"), "hello world")
        self.assertEqual(self.pool.get_variable_type("$dict_var.nested.value"), 42)
        self.assertEqual(
            self.pool.get_variable_type("$dict_var.deep.level1.level2"), "deep_value"
        )

    def test_get_variable_type_array_access(self):
        """测试数组访问的get_variable_type功能"""
        # 设置测试数据
        test_array = ["first", "second", "third"]
        test_dict_array = [
            {"name": "item1", "value": 10},
            {"name": "item2", "value": 20},
        ]
        self.pool.set_var("array_var", test_array)
        self.pool.set_var("dict_array_var", test_dict_array)

        # 测试数组访问
        self.assertEqual(self.pool.get_variable_type("$array_var[0]"), "first")
        self.assertEqual(self.pool.get_variable_type("$array_var[1]"), "second")
        self.assertEqual(
            self.pool.get_variable_type("$dict_array_var[0].name"), "item1"
        )
        self.assertEqual(self.pool.get_variable_type("$dict_array_var[1].value"), 20)

    def test_get_variable_type_complex_access(self):
        """测试复杂嵌套访问的get_variable_type功能"""
        # 设置复杂测试数据
        complex_data = {
            "result": {
                "text": [
                    {"content": [{"answer": "first_answer"}]},
                    {"content": [{"answer": "second_answer"}]},
                ]
            }
        }
        self.pool.set_var("complex_var", complex_data)

        # 测试复杂访问
        self.assertEqual(
            self.pool.get_variable_type(
                "$complex_var.result.text[0].content[0].answer"
            ),
            "first_answer",
        )

    def test_get_variable_type_list_processing(self):
        """测试列表处理的get_variable_type功能"""
        # 测试包含agent_name和answer的列表
        list_with_agents = [
            {"agent_name": "main", "answer": "Hello"},
            {"agent_name": "other", "answer": "World"},
            {"agent_name": "main", "answer": " Test"},
        ]
        self.pool.set_var("agent_list", list_with_agents)

        result = self.pool.get_variable_type("$agent_list")
        self.assertEqual(result, "Hello Test")  # 只处理main agent的answer

        # 测试混合类型列表
        mixed_list = ["string1", "string2", "string3"]
        self.pool.set_var("mixed_list", mixed_list)

        result = self.pool.get_variable_type("$mixed_list")
        self.assertEqual(result, ["string1", "string2", "string3"])

    def test_convert_object_to_dict_access(self):
        """测试对象访问转换为字典访问功能"""
        # 测试基本转换
        self.assertEqual(convert_object_to_dict_access("result.text"), "result['text']")

        # 测试数组访问
        self.assertEqual(
            convert_object_to_dict_access("result.text[0]"), "result['text'][0]"
        )

        # 测试复杂嵌套
        self.assertEqual(
            convert_object_to_dict_access("result.text[0].content[0].answer"),
            "result['text'][0]['content'][0]['answer']",
        )

        # 测试只有数组访问
        self.assertEqual(convert_object_to_dict_access("result[0]"), "result[0]")

    def test_get_variable_type_edge_cases(self):
        """测试get_variable_type的边界情况"""
        # 测试不存在的变量 - 应该抛出异常
        with self.assertRaises(AttributeError):
            self.pool.get_variable_type("$non_existent_var")

        # 测试空列表
        self.pool.set_var("empty_list", [])
        result = self.pool.get_variable_type("$empty_list")
        self.assertEqual(result, [])

        # 测试None值
        self.pool.set_var("none_var", None)
        result = self.pool.get_variable_type("$none_var")
        self.assertIsNone(result)

        # 测试包含数字0的数组索引特殊处理
        test_data = {"items": [{"value": "test0"}]}
        self.pool.set_var("test_var", test_data)
        # 这个测试验证[0替换为[的逻辑
        result = self.pool.get_variable_type("$test_var.items[0].value")
        self.assertEqual(result, "test0")

    def test_get_variable_type_special_list_cases(self):
        """测试列表处理的特殊情况"""
        # 测试只包含字典但没有agent_name的列表
        list_without_agent = [{"key": "value1"}, {"key": "value2"}]
        self.pool.set_var("no_agent_list", list_without_agent)
        result = self.pool.get_variable_type("$no_agent_list")
        self.assertEqual(result, list_without_agent)

        # 测试混合类型的列表
        mixed_list = [
            {"agent_name": "main", "answer": "from_main"},
            "string",
            42,
            {"agent_name": "other", "answer": "from_other"},
        ]
        self.pool.set_var("mixed_type_list", mixed_list)
        result = self.pool.get_variable_type("$mixed_type_list")
        self.assertEqual(result, "from_main")

    def test_get_variable_type_invalid_access(self):
        """测试无效访问路径"""
        test_data = {"valid": "value"}
        self.pool.set_var("test_data", test_data)

        # 测试访问不存在的属性
        with self.assertRaises((KeyError, AttributeError)):
            self.pool.get_variable_type("$test_data.invalid_key")

    def test_get_var_path_value(self):
        """Test get_var_path_value method for accessing nested values"""
        # Test data setup
        test_data = {
            "profile": {
                "name": "John Doe",
                "contact": {"email": "john@example.com", "phone": "1234567890"},
            },
            "settings": {
                "theme": "dark",
                "notifications": {"email": True, "push": False},
            },
        }
        self.pool.set_var("user", test_data)

        # Test successful path access
        self.assertEqual(self.pool.get_var_path_value("user.profile.name"), "John Doe")
        self.assertEqual(
            self.pool.get_var_path_value("user.profile.contact.email"),
            "john@example.com",
        )
        self.assertEqual(self.pool.get_var_path_value("user.settings.theme"), "dark")
        self.assertEqual(
            self.pool.get_var_path_value("user.settings.notifications.email"), True
        )

        # Test error cases
        self.assertEqual(self.pool.get_var_path_value(""), None)  # Empty path

        self.assertEqual(
            self.pool.get_var_path_value("nonexistent.path"), None
        )  # Non-existent base variable

        self.assertEqual(
            self.pool.get_var_path_value("user.profile.nonexistent"), None
        )  # Non-existent nested key

        # Test invalid path on non-dict value
        self.pool.set_var("simple", "value")
        self.assertEqual(
            self.pool.get_var_path_value("simple.invalid"), None
        )  # Trying to access path on non-dict value


if __name__ == "__main__":
    unittest.main()
