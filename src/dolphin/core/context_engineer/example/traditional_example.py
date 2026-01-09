"""ContextAssembler Traditional Full-Volume Processing Example

Demonstrates how to use ContextAssembler for traditional full-volume processing,
compared with incremental management methods, showcasing the workflow and characteristics of the traditional approach.
"""

import sys
import os
from tabulate import tabulate

# Add item path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from dolphin.core.context_engineer.core.context_assembler import (
    ContextAssembler,
    AssembledContext,
)
from dolphin.core.context_engineer.core.budget_manager import (
    BudgetManager,
    BudgetAllocation,
)
from dolphin.core.context_engineer.config.settings import (
    ContextConfig,
)


def get_context_config() -> ContextConfig:
    """Get context configuration"""
    return ContextConfig.from_dict(
        {
            "model": {
                "name": "gpt-4",
                "context_limit": 1000,
                "output_target": 100,
            },
            "buckets": {
                "system": {
                    "name": "system",
                    "min_tokens": 20,
                    "max_tokens": 100,
                    "weight": 2.0,
                    "message_role": "system",
                },
                "task": {
                    "name": "task",
                    "min_tokens": 10,
                    "max_tokens": 200,
                    "weight": 2.0,
                    "message_role": "user",
                },
                "history": {
                    "name": "history",
                    "min_tokens": 10,
                    "max_tokens": 300,
                    "weight": 1.0,
                    "message_role": "user",
                },
                "tool_response": {
                    "name": "tool_response",
                    "min_tokens": 10,
                    "max_tokens": 100,
                    "weight": 1.5,
                    "message_role": "tool",
                },
            },
            "policies": {
                "default": {
                    "drop_order": [],
                    "bucket_order": [
                        "system",
                        "task",
                        "tool_response",
                        "history",
                    ],
                }
            },
        }
    )


def print_assembled_context_stats(
    assembled_context: AssembledContext, title: str
) -> None:
    """Print statistics of the assembly context"""
    print(f"\n=== {title} ===")

    # Overall Statistics
    overview_data = [
        ["总token数", assembled_context.total_tokens],
        ["部分数量", len(assembled_context.sections)],
        ["丢弃部分", len(assembled_context.dropped_sections)],
    ]
    print(tabulate(overview_data, headers=["项目", "值"], tablefmt="grid"))

    # Detailed Statistics
    if assembled_context.sections:
        print("\n=== 各部分详细信息 ===")
        headers = ["部分名称", "Token数", "分配Token", "优先级", "消息角色", "利用率"]
        data = []
        for section in assembled_context.sections:
            utilization = (
                section.token_count / section.allocated_tokens
                if section.allocated_tokens > 0
                else 0
            )
            data.append(
                [
                    section.name,
                    section.token_count,
                    section.allocated_tokens,
                    section.priority,
                    section.message_role.value,
                    f"{utilization:.2%}",
                ]
            )
        print(tabulate(data, headers=headers, tablefmt="grid"))

    # Location Mapping
    print("\n=== 桶顺序 ===")
    for position, buckets in assembled_context.placement_map.items():
        if buckets:
            print(f"{position}: {buckets}")


def demonstrate_traditional_workflow():
    """Demonstrate the traditional full-processing workflow"""
    print("=== 传统全量处理工作流程演示 ===")

    # Initialize component
    context_config = get_context_config()
    assembler = ContextAssembler(context_config=context_config)
    budget_manager = BudgetManager(context_config=context_config)

    # Prepare initial content
    print("\n=== 步骤1: 准备内容 ===")
    content_sections = {
        "system": "你是一个专业的编程助手，擅长帮助用户解决编程问题。",
        "task": "用户想要学习如何使用Python进行数据分析和可视化。",
        "history": "用户：我想学习Python数据分析\n助手：我可以帮你学习Python数据分析，从基础开始。",
        "tool_response": "Python数据分析工具已加载完成",
    }

    # Calculate Budget Allocation
    print("\n=== 步骤2: 计算预算分配 ===")
    budget_allocations = budget_manager.allocate_budget()

    headers = ["桶名称", "分配Token", "优先级"]
    allocation_data = []
    for allocation in budget_allocations:
        allocation_data.append(
            [
                allocation.bucket_name,
                allocation.allocated_tokens,
                allocation.priority,
            ]
        )
    print(tabulate(allocation_data, headers=headers, tablefmt="grid"))

    # First Assembly
    print("\n=== 步骤3: 第一次全量组装 ===")
    assembled_context = assembler.assemble_context(
        content_sections=content_sections,
        budget_allocations=budget_allocations,
    )
    print_assembled_context_stats(assembled_context, "第一次组装结果")

    # Changelog (all content needs to be reprocessed)
    print("\n=== 步骤4: 更新内容（传统方式需要重新处理所有内容） ===")
    updated_content_sections = content_sections.copy()
    updated_content_sections["task"] = (
        "用户想要学习如何使用Python进行数据分析和可视化，特别是使用pandas和matplotlib库。"
    )
    updated_content_sections["history"] += (
        "\n用户：我想了解pandas和matplotlib\n助手：pandas用于数据处理，matplotlib用于绘图。"
    )

    # Second Assembly (Full Processing)
    print("\n=== 步骤5: 第二次全量组装 ===")
    assembled_context = assembler.assemble_context(
        content_sections=updated_content_sections,
        budget_allocations=budget_allocations,
    )
    print_assembled_context_stats(assembled_context, "第二次组装结果")

    # Update content again
    print("\n=== 步骤6: 再次更新内容 ===")
    final_content_sections = updated_content_sections.copy()
    final_content_sections["history"] += (
        "\n用户：请给我一个示例\n助手：好的，我来给你一个数据分析的示例。"
    )
    final_content_sections["tool_response"] = (
        "数据分析工具已准备就绪，包含pandas、numpy、matplotlib等库"
    )

    # Third Assembly (Full Processing)
    print("\n=== 步骤7: 第三次全量组装 ===")
    assembled_context = assembler.assemble_context(
        content_sections=final_content_sections,
        budget_allocations=budget_allocations,
    )
    print_assembled_context_stats(assembled_context, "第三次组装结果")

    # Convert to message format
    print("\n=== 步骤8: 转换为消息格式 ===")
    messages = assembler.to_messages()
    for i, message in enumerate(messages):
        print(
            f"消息 {i + 1}: {message['role']} - {message['content'][:50]}{'...' if len(message['content']) > 50 else ''}"
        )

    return assembled_context


def demonstrate_performance_comparison():
    """Performance Comparison Demo"""
    print("\n=== 性能对比演示 ===")

    # Simulate multi-turn dialogue scenarios
    base_content = {
        "system": "你是一个有用的AI助手。",
        "task": "用户的问题描述。",
        "history": "之前的对话历史。",
    }

    budget_allocations = [
        BudgetAllocation("system", 50, 2.0),
        BudgetAllocation("task", 100, 1.5),
        BudgetAllocation("history", 200, 1.0),
    ]

    assembler = ContextAssembler()

    # Simulate multi-turn dialogue
    conversation_rounds = 5
    content_updates = [
        "用户的问题描述更新。",
        "用户的问题描述更新，添加了更多细节。",
        "用户的问题描述更新，添加了更多细节和背景信息。",
        "用户的问题描述更新，添加了更多细节、背景信息和具体需求。",
        "用户的问题描述更新，添加了更多细节、背景信息、具体需求和期望结果。",
    ]

    print("\n=== 传统全量处理模拟 ===")
    for i in range(conversation_rounds):
        print(f"\n--- 第{i + 1}轮对话 ---")

        # Changelog
        updated_content = base_content.copy()
        updated_content["task"] = content_updates[i]
        updated_content["history"] = f"之前的对话历史（第{i + 1}轮）。" + "\n".join(
            [f"对话历史{j}" for j in range(i + 1)]
        )

        # Full processing is required each time
        assembled_context = assembler.assemble_context(
            content_sections=updated_content,
            budget_allocations=budget_allocations,
        )

        print(f"总token数: {assembled_context.total_tokens}")
        print(f"处理的部分数量: {len(assembled_context.sections)}")
        print("特点：每次都需要处理所有内容，无法利用之前的处理结果")

    print("\n=== 传统方式的特点 ===")
    print("1. 每次都需要传入完整的内容进行全量处理")
    print("2. 无法利用之前的处理结果，每次都从零开始")
    print("3. 适合内容变化较大的场景")
    print("4. 实现相对简单，逻辑清晰")
    print("5. 在内容变化小时会造成不必要的重复计算")


def demonstrate_memory_usage():
    """Demonstrate memory usage"""
    print("\n=== 内存使用演示 ===")

    # Create large amounts of content
    large_content_sections = {}
    for i in range(10):
        large_content_sections[f"section_{i}"] = (
            f"这是第{i + 1}个部分的内容，包含大量文本数据。" + "这是一个测试句。" * 50
        )

    budget_allocations = [BudgetAllocation(f"section_{i}", 200, 1.0) for i in range(10)]

    assembler = ContextAssembler()

    print("处理大量内容...")
    assembled_context = assembler.assemble_context(
        content_sections=large_content_sections,
        budget_allocations=budget_allocations,
    )

    print(f"处理的部分数量: {len(assembled_context.sections)}")
    print(f"总token数: {assembled_context.total_tokens}")
    print(
        f"平均每个部分的token数: {assembled_context.total_tokens / len(assembled_context.sections):.1f}"
    )

    print("\n内存使用特点：")
    print("- 每次组装都需要在内存中保存所有内容的完整副本")
    print("- 对于大型内容，内存使用量会线性增长")
    print("- 无法通过增量更新来优化内存使用")


def main():
    """Main function"""
    print("ContextAssembler 传统全量处理示例")
    print("=" * 50)

    # Demonstrate the basic workflow
    demonstrate_traditional_workflow()

    # Performance Comparison Demo
    demonstrate_performance_comparison()

    # Demonstrate memory usage
    demonstrate_memory_usage()

    print("\n=== 总结 ===")
    print("传统全量处理方式的特点：")
    print("✓ 实现简单，逻辑清晰")
    print("✓ 适合内容变化较大的场景")
    print("✓ 每次处理都是独立的，不会累积错误")
    print("✗ 每次都需要全量处理，无法利用之前的计算结果")
    print("✗ 在内容变化小时造成不必要的重复计算")
    print("✗ 内存使用量相对较大")
    print("\n适用场景：")
    print("- 内容变化频繁且变化较大的场景")
    print("- 对实时性要求不高的场景")
    print("- 实现简单性比性能更重要的场景")


if __name__ == "__main__":
    main()
