#!/usr/bin/env python3
"""
OutputFormat 功能测试示例
"""

import json


from dolphin.core.common.output_format import (
    OutputFormatFactory,
    JsonOutputFormat,
    JsonlOutputFormat,
    ListStrOutputFormat,
    ObjectTypeOutputFormat,
)
from dolphin.core.common.object_type import ObjectTypeFactory
from dolphin.core.common.enums import MessageRole, Messages


def test_json_format():
    """测试 JSON 格式"""
    print("=== 测试 JSON 格式 ===")

    # 创建 JSON 格式处理器
    json_format = JsonOutputFormat()
    print(f"格式类型: {json_format.getFormatType().value}")
    print(f"格式描述: {json_format.getFormatDescription()}")

    # 测试添加约束到 Messages
    messages = Messages()
    json_format.addFormatConstraintToMessages(messages)
    print(f"添加约束后的消息数量: {len(messages.messages)}")

    # 测试解析响应
    response_str = '{"name": "张三", "age": 30, "city": "北京"}'
    parsed_result = json_format.parseResponse(response_str)
    print(f"解析结果: {parsed_result}")
    print(f"解析结果类型: {type(parsed_result)}")
    print()


def test_jsonl_format():
    """测试 JSONL 格式"""
    print("=== 测试 JSONL 格式 ===")

    # 创建 JSONL 格式处理器
    jsonl_format = JsonlOutputFormat()
    print(f"格式类型: {jsonl_format.getFormatType().value}")
    print(f"格式描述: {jsonl_format.getFormatDescription()}")

    # 测试解析响应
    response_str = """{"name": "张三", "age": 30}
{"name": "李四", "age": 25}
{"name": "王五", "age": 35}"""

    parsed_result = jsonl_format.parseResponse(response_str)
    print(f"解析结果: {parsed_result}")
    print(f"解析结果类型: {type(parsed_result)}")
    print(f"结果数量: {len(parsed_result)}")
    print()


def test_list_str_format():
    """测试 List[str] 格式"""
    print("=== 测试 List[str] 格式 ===")

    # 创建 List[str] 格式处理器
    list_str_format = ListStrOutputFormat()
    print(f"格式类型: {list_str_format.getFormatType().value}")
    print(f"格式描述: {list_str_format.getFormatDescription()}")

    # 测试添加约束到 Messages
    messages = Messages()
    list_str_format.addFormatConstraintToMessages(messages)
    print(f"添加约束后的消息数量: {len(messages.messages)}")

    # 测试解析标准 JSON 数组响应
    response_str1 = '["Apple", "Banana", "Cherry", "Date"]'
    parsed_result1 = list_str_format.parseResponse(response_str1)
    print(f"标准JSON数组解析结果: {parsed_result1}")
    print(f"解析结果类型: {type(parsed_result1)}")

    # 测试解析混合类型的 JSON 数组（会转换为字符串）
    response_str2 = '["Apple", 123, true, "Cherry"]'
    parsed_result2 = list_str_format.parseResponse(response_str2)
    print(f"混合类型数组解析结果: {parsed_result2}")

    # 测试解析带代码块的响应
    response_str3 = """Here are some fruits:
```json
["Mango", "Pineapple", "Grape"]
```"""
    parsed_result3 = list_str_format.parseResponse(response_str3)
    print(f"代码块格式解析结果: {parsed_result3}")

    # 测试解析行分割格式（回退处理）
    response_str4 = """Apple
Banana
Cherry
Date"""
    parsed_result4 = list_str_format.parseResponse(response_str4)
    print(f"行分割格式解析结果: {parsed_result4}")

    print()


def test_object_type_format():
    """测试对象类型格式"""
    print("=== 测试对象类型格式 ===")

    # 创建一个示例对象类型定义
    object_type_def = {
        "title": "UserProfile",
        "description": "用户档案信息",
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "用户姓名"},
            "age": {"type": "integer", "description": "用户年龄"},
            "email": {"type": "string", "description": "用户邮箱"},
            "skills": {"type": "array", "description": "用户技能列表"},
        },
        "required": ["name", "age"],
    }

    # 创建对象类型格式处理器
    obj_format = ObjectTypeOutputFormat("UserProfile", object_type_def)
    print(f"格式类型: {obj_format.getFormatType().value}")
    print(f"对象类型名称: {obj_format.getObjectTypeName()}")
    print(f"格式描述: {obj_format.getFormatDescription()}")

    # 测试生成 function call tools
    tools = obj_format.generateFunctionCallTools()
    print(f"Function Call Tools: {json.dumps(tools, indent=2, ensure_ascii=False)}")

    # 测试解析响应
    response_str = '{"name": "张三", "age": 30, "email": "zhangsan@example.com", "skills": ["Python", "AI"]}'
    parsed_result = obj_format.parseResponse(response_str)
    print(f"解析结果: {parsed_result}")
    print()


def test_factory_parsing():
    """测试工厂类解析"""
    print("=== 测试工厂类解析 ===")

    # 测试 JSON 格式解析
    json_format = OutputFormatFactory.parseFromString("json")
    print(f"解析 'json': {json_format}")

    # 测试 JSONL 格式解析
    jsonl_format = OutputFormatFactory.parseFromString("jsonl")
    print(f"解析 'jsonl': {jsonl_format}")

    # 测试 List[str] 格式解析
    list_str_format = OutputFormatFactory.parseFromString("list_str")
    print(f"解析 'list_str': {list_str_format}")

    # 创建一个全局类型工厂用于测试对象类型
    global_types = ObjectTypeFactory()

    # 添加一个测试类型
    test_type_json = {
        "title": "TestUser",
        "description": "测试用户类型",
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "用户名"},
            "status": {"type": "string", "description": "状态"},
        },
        "required": ["username"],
    }
    global_types.load_from_json(test_type_json)

    # 测试对象类型格式解析
    try:
        obj_format = OutputFormatFactory.parseFromString("obj/TestUser", global_types)
        print(f"解析 'obj/TestUser': {obj_format}")
        print(f"对象类型定义: {obj_format.getObjectTypeDefinition()}")
    except Exception as e:
        print(f"解析对象类型失败: {e}")

    print()


def test_format_constraint_integration():
    """测试格式约束集成"""
    print("=== 测试格式约束集成 ===")

    # 模拟不同格式的使用场景
    formats = [
        ("json", None),
        ("jsonl", None),
        ("list_str", None),
    ]

    for format_str, global_types in formats:
        print(f"测试格式: {format_str}")
        output_format = OutputFormatFactory.parseFromString(format_str, global_types)

        # 创建 Messages 并添加约束
        messages = Messages()
        messages.append_message(MessageRole.USER, "请生成一些示例数据")
        output_format.addFormatConstraintToMessages(messages)

        print(f"  消息数量: {len(messages.messages)}")
        print(f"  最后一条消息: {messages.messages[-1]}")
        print()


if __name__ == "__main__":
    print("OutputFormat 功能测试")
    print("=" * 50)

    test_json_format()
    test_jsonl_format()
    test_list_str_format()
    test_object_type_format()
    test_factory_parsing()
    test_format_constraint_integration()

    print("所有测试完成！")
