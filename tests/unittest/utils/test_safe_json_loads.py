#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
safe_json_loads 函数测试脚本
测试各种 JSON 解析场景
"""

import unittest


from dolphin.core.utils.tools import safe_json_loads


class TestSafeJsonLoads(unittest.TestCase):
    def test_basic_json(self):
        """测试基本的 JSON 解析"""
        # 测试普通 JSON
        json_str = '{"name": "test", "value": 123}'
        result = safe_json_loads(json_str)
        self.assertEqual(result, {"name": "test", "value": 123})

        # 测试带单引号的 JSON
        json_str = "{'name': 'test', 'value': 123}"
        result = safe_json_loads(json_str)
        self.assertEqual(result, {"name": "test", "value": 123})

    def test_empty_input(self):
        """测试空输入"""
        self.assertEqual(safe_json_loads(""), {})
        self.assertEqual(safe_json_loads(" "), {})
        self.assertEqual(safe_json_loads(None), {})

    def test_nested_json(self):
        """测试嵌套的 JSON"""
        json_str = '{"data": {"items": [1, 2, 3], "info": {"name": "test"}}}'
        result = safe_json_loads(json_str)
        self.assertEqual(
            result, {"data": {"items": [1, 2, 3], "info": {"name": "test"}}}
        )

    def test_invalid_json(self):
        """测试无效的 JSON"""
        # 测试完全无效的 JSON 格式
        with self.assertRaises(ValueError):
            safe_json_loads("{invalid json}")

        # 测试不完整的 JSON 结构
        with self.assertRaises(ValueError):
            safe_json_loads('{"name": }')

        # 测试错误的值类型
        with self.assertRaises(ValueError):
            safe_json_loads('{"name": undefined}')

    def test_sql_json(self):
        """测试包含 SQL 语句的 JSON"""
        # 测试正常的 SQL JSON
        json_str = """
        {
            "tool_name": "executeSQL",
            "tool_args": {
                "datasource": "test_db",
                "sql": "SELECT * FROM table"
            }
        }
        """
        result = safe_json_loads(json_str)
        self.assertEqual(result["tool_name"], "executeSQL")
        self.assertEqual(result["tool_args"]["sql"], "SELECT * FROM table")

        # 测试带分号和双引号的 SQL JSON
        json_str = """
        {
            "tool_name": "executeSQL",
            "tool_args": {
                "datasource": "california_schools",
                "sql": "SELECT \\"Enrollment (Ages 5-17)\\" FROM frpm WHERE \\"CDSCode\\" = '01316170131763' AND \\"Academic Year\\" = '2014-2015'"
            }
        }
        """
        result = safe_json_loads(json_str)
        self.assertEqual(result["tool_name"], "executeSQL")
        self.assertEqual(
            result["tool_args"]["sql"],
            'SELECT "Enrollment (Ages 5-17)" FROM frpm WHERE "CDSCode" = \'01316170131763\' AND "Academic Year" = \'2014-2015\'',
        )

        # 测试带有格式错误的 SQL JSON
        json_str = """
        {
            "tool_name": "executeSQL",
            "tool_args": {
                "datasource": "california_schools",
                "sql": "SELECT * FROM table WHERE id = 1;";
            }
        }
        """
        with self.assertRaises(ValueError):
            safe_json_loads(json_str)

    def test_special_characters(self):
        """测试包含特殊字符的 JSON"""
        # 测试包含转义字符
        json_str = '{"path": "C:\\\\temp\\\\test"}'
        result = safe_json_loads(json_str)
        self.assertEqual(result["path"], "C:\\temp\\test")

        # 测试包含换行符
        json_str = '{"text": "line1\\nline2"}'
        result = safe_json_loads(json_str)
        self.assertEqual(result["text"], "line1\nline2")


if __name__ == "__main__":
    unittest.main()
