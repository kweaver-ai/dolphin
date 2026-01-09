#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_nested_value 函数测试脚本
测试递归解析嵌套变量名的各种情况
"""

from dolphin.lib.utils.data_process import get_nested_value


def test_basic_access():
    """测试基本访问"""
    print("=== 测试基本访问 ===")

    data = {"name": "张三", "age": 25, "city": "北京"}

    # 测试基本键访问
    assert get_nested_value("name", data) == "张三"
    assert get_nested_value("age", data) == 25
    assert get_nested_value("city", data) == "北京"

    print("✓ 基本访问测试通过")


def test_nested_dict_access():
    """测试嵌套字典访问"""
    print("=== 测试嵌套字典访问 ===")

    data = {
        "user": {
            "profile": {"name": "李四", "email": "lisi@example.com"},
            "settings": {"theme": "dark", "language": "zh-CN"},
        }
    }

    # 测试嵌套访问
    # assert get_nested_value("user.profile.name", data) == "李四"
    assert get_nested_value("user['profile']['name']", data) == "李四"
    assert get_nested_value("user.profile.email", data) == "lisi@example.com"
    assert get_nested_value("user.settings.theme", data) == "dark"
    assert get_nested_value("user.settings.language", data) == "zh-CN"

    print("✓ 嵌套字典访问测试通过")


def test_array_access():
    """测试数组访问"""
    print("=== 测试数组访问 ===")

    data = {
        "numbers": [1, 2, 3, 4, 5],
        "users": [
            {"name": "王五", "age": 30},
            {"name": "赵六", "age": 28},
            {"name": "钱七", "age": 35},
        ],
    }

    # 测试基本数组访问
    assert get_nested_value("numbers[0]", data) == 1
    assert get_nested_value("numbers[2]", data) == 3
    assert get_nested_value("numbers[4]", data) == 5

    # 测试数组中的对象访问
    assert get_nested_value("users[0].name", data) == "王五"
    assert get_nested_value("users[1].age", data) == 28
    assert get_nested_value("users[2].name", data) == "钱七"

    print("✓ 数组访问测试通过")


def test_mixed_access():
    """测试混合访问（数组和字典混合）"""
    print("=== 测试混合访问 ===")

    data = {
        "company": {
            "departments": [
                {
                    "name": "技术部",
                    "employees": [
                        {"name": "张三", "role": "工程师"},
                        {"name": "李四", "role": "架构师"},
                    ],
                },
                {"name": "产品部", "employees": [{"name": "王五", "role": "产品经理"}]},
            ]
        }
    }

    # 测试复杂的混合访问
    assert get_nested_value("company.departments[0].name", data) == "技术部"
    assert get_nested_value("company.departments[0].employees[0].name", data) == "张三"
    assert (
        get_nested_value("company.departments[0].employees[0].role", data) == "工程师"
    )
    assert get_nested_value("company.departments[1].employees[0].name", data) == "王五"

    print("✓ 混合访问测试通过")


def test_edge_cases():
    """测试边界情况"""
    print("=== 测试边界情况 ===")

    data = {
        "empty_dict": {},
        "empty_list": [],
        "null_value": None,
        "zero": 0,
        "empty_string": "",
    }

    # 测试空字符串变量名
    assert get_nested_value("", data) == data

    # 测试空字典
    assert get_nested_value("empty_dict", data) == {}

    # 测试空列表
    assert get_nested_value("empty_list", data) == []

    # 测试 null 值
    assert get_nested_value("null_value", data) is None

    # 测试零值
    assert get_nested_value("zero", data) == 0

    # 测试空字符串
    assert get_nested_value("empty_string", data) == ""

    print("✓ 边界情况测试通过")


def test_error_cases():
    """测试错误情况"""
    print("=== 测试错误情况 ===")

    data = {"name": "测试", "numbers": [1, 2, 3], "user": {"name": "张三"}}

    # 测试不存在的键
    try:
        get_nested_value("nonexistent", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不存在于数据中" in str(e)

    # 测试不存在的嵌套键
    try:
        get_nested_value("user.age", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不存在于数据中" in str(e)

    # 测试数组索引超出范围
    try:
        get_nested_value("numbers[10]", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "超出范围" in str(e)

    # 测试负数索引
    try:
        get_nested_value("numbers[-1]", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不是有效的数字" in str(e) or "超出范围" in str(e)

    # 测试对非字典使用点号访问
    try:
        get_nested_value("name.age", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不是字典类型" in str(e)

    # 测试对非列表使用索引访问
    try:
        get_nested_value("name[0]", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不是列表类型" in str(e)

    # 测试无效的数组索引
    try:
        get_nested_value("numbers[abc]", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "不是有效的数字" in str(e)

    # 测试不匹配的方括号
    try:
        get_nested_value("numbers[0", data)
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "方括号不匹配" in str(e)

    print("✓ 错误情况测试通过")


def test_complex_scenarios():
    """测试复杂场景"""
    print("=== 测试复杂场景 ===")

    data = {
        "api_response": {
            "status": "success",
            "data": {
                "items": [
                    {
                        "id": 1,
                        "title": "文章1",
                        "tags": ["技术", "编程"],
                        "author": {
                            "name": "作者1",
                            "profile": {"avatar": "avatar1.jpg", "bio": "技术专家"},
                        },
                    },
                    {
                        "id": 2,
                        "title": "文章2",
                        "tags": ["设计", "UI"],
                        "author": {
                            "name": "作者2",
                            "profile": {"avatar": "avatar2.jpg", "bio": "设计师"},
                        },
                    },
                ],
                "pagination": {"page": 1, "total": 100, "per_page": 20},
            },
        }
    }

    # 测试复杂的嵌套访问
    assert get_nested_value("api_response.status", data) == "success"
    assert get_nested_value("api_response.data.items[0].id", data) == 1
    assert get_nested_value("api_response.data.items[0].title", data) == "文章1"
    assert get_nested_value("api_response.data.items[0].tags[0]", data) == "技术"
    assert get_nested_value("api_response.data.items[0].author.name", data) == "作者1"
    assert (
        get_nested_value("api_response.data.items[0].author.profile.avatar", data)
        == "avatar1.jpg"
    )
    assert (
        get_nested_value("api_response.data.items[1].author.profile.bio", data)
        == "设计师"
    )
    assert get_nested_value("api_response.data.pagination.page", data) == 1
    assert get_nested_value("api_response.data.pagination.total", data) == 100

    print("✓ 复杂场景测试通过")


def run_all_tests():
    """运行所有测试"""
    print("开始测试 get_nested_value 函数...\n")

    try:
        # test_basic_access()
        test_nested_dict_access()
        test_array_access()
        test_mixed_access()
        test_edge_cases()
        test_error_cases()
        test_complex_scenarios()

        print("\n🎉 所有测试通过！")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
