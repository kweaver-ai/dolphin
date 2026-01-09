"""ContextManager Usage Example

Demonstrates how to dynamically manage context buckets, supporting incremental updates and controllable compression.

"""

import sys
import os
from dolphin.core.common.enums import Messages, MessageRole
from tabulate import tabulate

# Add item path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from dolphin.core.context_engineer.core.context_manager import (
    ContextManager,
)
from dolphin.core.context_engineer.config.settings import (
    ContextConfig,
)


def get_context_config() -> ContextConfig:
    return ContextConfig.from_dict(
        {
            "model": {
                "name": "gpt-4",
                "context_limit": 100,
                "output_target": 10,
            },
            "buckets": {
                "system": {
                    "name": "system",
                    "min_tokens": 10,
                    "max_tokens": 30,
                    "weight": 2.0,
                    "message_role": "system",
                },
                "task": {
                    "name": "task",
                    "min_tokens": 5,
                    "max_tokens": 30,
                    "weight": 2.0,
                    "message_role": "user",
                },
                "history": {
                    "name": "history",
                    "min_tokens": 5,
                    "max_tokens": 200,
                    "weight": 1.0,
                    "message_role": "user",
                },
            },
            "policies": {
                "default": {
                    "drop_order": [],
                    "bucket_order": [
                        "system",
                        "_query",
                        "tool_response",
                        "task",
                        "history",
                    ],
                }
            },
        }
    )


def print_stats_table(stats: dict, title: str = "Token Statistics") -> None:
    """Print the complete stats information in table format."""
    print(f"\n=== {title} ===")

    # Print overall statistics
    overview_data = [
        ["总token数", stats["total_tokens"]],
        ["桶数量", stats["bucket_count"]],
        ["需要压缩", stats["compression_needed"]],
    ]
    print(tabulate(overview_data, headers=["项目", "值"], tablefmt="grid"))

    # Print detailed information for each bucket
    if stats["buckets"]:
        print("\n=== 桶详细信息 ===")
        bucket_headers = [
            "桶名称",
            "Tokens",
            "分配Tokens",
            "优先级",
            "压缩状态",
            "利用率",
            "需要压缩",
        ]
        bucket_data = []
        for name, info in stats["buckets"].items():
            bucket_data.append(
                [
                    name,
                    info["tokens"],
                    info["allocated"],
                    info["priority"],
                    "是" if info["is_compressed"] else "否",
                    f"{info['utilization']:.2%}",
                    "是" if info["needs_compression"] else "否",
                ]
            )
        print(tabulate(bucket_data, headers=bucket_headers, tablefmt="grid"))


def main():
    """Demonstrate the basic usage of ContextManager"""

    # Create incremental context manager
    context_config = get_context_config()
    manager = ContextManager(context_config=context_config)
    manager.set_layout_policy("default")
    print("=== 初始状态 ===")
    stats = manager.get_token_stats()
    print_stats_table(stats, "初始状态统计")

    # Add system prompt bucket
    print("\n=== 添加系统提示桶 ===")
    manager.add_bucket(
        bucket_name="system",
        content="你是一个有用的AI助手，请帮助用户解决问题。",
        allocated_tokens=50,
    )

    # Add task description bucket
    manager.add_bucket(
        bucket_name="task",
        content="用户想要了解如何提高编程技能。",
        allocated_tokens=20,
    )

    stats = manager.get_token_stats()
    print_stats_table(stats, "添加桶后统计")

    # Update bucket contents (incremental update)
    print("\n=== 增量更新桶内容 ===")
    manager.update_bucket_content(
        "task", "用户想要了解如何提高编程技能 ，特别是Python和机器学习方面的技能。"
    )

    stats = manager.get_token_stats()
    print_stats_table(stats, "更新内容后统计")

    # Dynamically add new bucket
    print("\n=== 动态添加对话历史桶 ===")
    history_messages = Messages()
    history_messages.add_message("用户对话历史1")
    history_messages.add_message("用户对话历史2")
    history_messages.add_message("用户对话历史3")
    history_messages.add_message("用户对话历史4")

    manager.add_bucket(
        "history",
        history_messages,
        # allocated_tokens=10,
    )

    manager.add_bucket(
        bucket_name="tool_response",
        content="这是调用工具的结果的",
        message_role=MessageRole.TOOL,
    )

    stats = manager.get_token_stats()
    print_stats_table(stats, "添加历史桶后统计")

    # Check if compression is needed
    if manager.needs_compression():
        print("\n=== 检测到需要压缩 ===")
        # Compress all buckets that need to be compressed
        results = manager.compress_all()
        print("压缩结果:", results)

    print("\n=== 压缩后统计 ===")
    stats = manager.get_token_stats()
    print_stats_table(stats, "添加桶后统计")

    # Assemble final context
    print("\n=== 组装最终上下文 ===")
    context = manager.assemble_context()
    print(f"上下文桶顺序: {context['bucket_order']}")
    print(f"布局策略: {context['layout_policy']}")

    # Convert to message format
    print("\n=== 转换为消息格式 ===")

    messages = manager.to_dph_messages()
    for i, message in enumerate(messages.messages):
        print(
            f"消息 {i + 1}: {message.role.value} - {message.content[:50]}{'...' if len(message.content) > 50 else ''}"
        )

    # Remove Bucket
    print("\n=== 移除历史桶 ===")
    manager.remove_bucket("history")
    stats = manager.get_token_stats()
    print_stats_table(stats, "移除历史桶后统计")

    # Clear all contexts
    print("\n=== 清空所有上下文 ===")
    manager.clear()
    stats = manager.get_token_stats()
    print_stats_table(stats, "清空后统计")


def performance_comparison():
    """Performance Comparison: Traditional Full Assembly vs Incremental Management"""

    print("\n=== 性能对比演示 ===")

    # Traditional approach: Full assembly each time
    from dolphin.core.context_engineer.core.context_assembler import (
        ContextAssembler,
    )
    from dolphin.core.context_engineer.core.budget_manager import (
        BudgetAllocation,
    )

    # Simulate multi-turn dialogue scenarios
    content_sections = {
        "system": "你是一个有用的AI助手。",
        "task": "用户的问题描述。",
        "history": "之前的对话历史。",
    }

    budget_allocations = [
        BudgetAllocation("system", 50, 2.0),
        BudgetAllocation("task", 100, 1.5),
        BudgetAllocation("history", 200, 1.0),
    ]

    # Traditional approach: Process all data in full each time
    assembler = ContextAssembler()

    # Incremental mode: dynamic management
    incremental_manager = ContextManager()

    # Initial Setup
    incremental_manager.add_bucket("system", content_sections["system"], 2.0, 50)
    incremental_manager.add_bucket("task", content_sections["task"], 1.5, 100)
    incremental_manager.add_bucket("history", content_sections["history"], 1.0, 200)

    print("传统方式需要每次传入完整内容进行全量处理")
    print("增量方式支持动态更新，性能更优")

    # Demonstrate the advantages of incremental updates
    print("\n=== 增量更新优势 ===")

    # Update a single bucket (incremental mode)
    incremental_manager.update_bucket_content("task", "更新后的问题描述。")
    print("增量方式：只更新变化的桶，无需全量处理")

    # Check compression requirements
    if incremental_manager.needs_compression():
        print("检测到需要压缩，可以按需压缩")
        incremental_manager.compress_bucket("history")

    print("增量管理支持细粒度的控制，避免不必要的计算")


if __name__ == "__main__":
    main()
    # performance_comparison()
