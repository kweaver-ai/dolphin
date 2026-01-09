#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptOptimizer 使用示例

演示如何使用 PromptOptimizer 优化 Agent 的 .dph 文件。
"""
import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from experiments.optimization import (
    PromptOptimizer,
    QuickPromptOptimizer,
    DeepPromptOptimizer,
    Budget
)


class MockLLMClient:
    """模拟的 LLM 客户端（实际使用时替换为真实的）"""

    def generate(self, prompt: str) -> str:
        """生成优化后的 prompt"""
        # 实际实现中，这里会调用 LLM API
        return "优化后的 prompt 内容..."


class MockSemanticJudge:
    """模拟的 SemanticJudge（实际使用时替换为真实的）"""

    def evaluate(self, analysis_content: str, expected: str, actual: str, knowledge: str = '') -> dict:
        """评估结果（与 SemanticJudge 接口保持一致）"""
        # 简单的模拟
        if expected and expected.lower() in actual.lower():
            score = 1.0
        else:
            score = 0.5

        from experiments.optimization.types import SemanticJudgeDetail

        return {
            'score': score,
            'details': SemanticJudgeDetail(
                error_types=[],
                action_vector=['improve clarity'],
                candidate_injects=[],
                rationale='Mock evaluation',
                phase='exact'
            )
        }


def example_1_basic_usage():
    """示例 1: 基本使用"""
    print("=" * 70)
    print("  示例 1: PromptOptimizer 基本使用")
    print("=" * 70)
    print()

    # 1. 创建 LLM 客户端和 SemanticJudge
    llm_client = MockLLMClient()
    semantic_judge = MockSemanticJudge()

    # 2. 创建优化器
    optimizer = PromptOptimizer.create_default(
        llm_client=llm_client,
        semantic_judge=semantic_judge,
        target_section='system'  # 只优化 system 部分
    )

    # 3. 准备上下文
    context = {
        'agent_path': 'path/to/agent.dph',
        'failed_cases': [
            {'case_id': '001', 'error_type': 'logic_error'},
            {'case_id': '002', 'error_type': 'tool_misuse'}
        ],
        'knowledge': '业务规则：...',
        'error_types': ['logic_error', 'tool_misuse']
    }

    # 4. 设置预算
    budget = Budget(max_iters=3, max_seconds=180)

    # 5. 优化 Agent 内容
    target = """
system = \"\"\"
你是一个数据分析助手。
\"\"\"
"""

    print("优化原始内容...")
    result = optimizer.optimize(target, context, budget)

    # 6. 查看结果
    print(f"\n✓ 优化完成！")
    print(f"  最佳得分: {result.best_score:.2f}")
    if result.best_candidate:
        print(f"  优化后的内容:\n{result.best_candidate.content[:200]}...")
    print()


def example_2_optimize_file():
    """示例 2: 优化文件（带备份）"""
    print("=" * 70)
    print("  示例 2: 优化 Agent 文件（带备份）")
    print("=" * 70)
    print()

    llm_client = MockLLMClient()
    semantic_judge = MockSemanticJudge()

    # 创建优化器
    optimizer = PromptOptimizer.create_default(
        llm_client=llm_client,
        semantic_judge=semantic_judge
    )

    # 注意：这里使用的是示例路径，实际使用时需要真实的文件路径
    print("⚠️  这是一个演示示例，使用的是模拟路径")
    print()

    # 示例代码（实际使用时取消注释）
    print("使用示例代码：")
    print("""
    result = optimizer.optimize_file(
        agent_path='experiments/design/watsons_baseline/dolphins/my_agent.dph',
        context={
            'failed_cases': failed_cases,
            'knowledge': business_rules,
            'error_types': ['logic_error']
        },
        budget=Budget(max_iters=5, max_seconds=300),
        backup=True,      # 自动备份原文件到 .backup/ 目录
        replace=False     # 不自动替换（先查看结果）
    )

    if result.best_candidate:
        print(f"✓ 优化成功！最佳得分: {result.best_score:.2f}")

        # 查看优化后的内容
        print("优化后的内容:")
        print(result.best_candidate.content)

        # 如果满意，手动替换
        # agent_path.write_text(result.best_candidate.content)
    """)
    print()


def example_3_quick_vs_deep():
    """示例 3: 快速优化 vs 深度优化"""
    print("=" * 70)
    print("  示例 3: 快速优化 vs 深度优化")
    print("=" * 70)
    print()

    llm_client = MockLLMClient()
    semantic_judge = MockSemanticJudge()

    # 快速优化器：少量候选，快速收敛
    quick_optimizer = QuickPromptOptimizer(
        llm_client=llm_client,
        semantic_judge=semantic_judge
    )

    # 深度优化器：更多候选，追求最佳
    deep_optimizer = DeepPromptOptimizer(
        llm_client=llm_client,
        semantic_judge=semantic_judge
    )

    target = """
system = \"\"\"
你是一个助手。
\"\"\"
"""

    context = {
        'agent_path': 'test.dph',
        'error_types': ['logic_error']
    }

    print("1. 快速优化（3 个初始候选，耐心值=1）")
    quick_budget = Budget(max_iters=3)
    quick_result = quick_optimizer.optimize(target, context, quick_budget)
    print(f"   得分: {quick_result.best_score:.2f}")
    print()

    print("2. 深度优化（10 个初始候选，耐心值=5）")
    deep_budget = Budget(max_iters=10)
    deep_result = deep_optimizer.optimize(target, context, deep_budget)
    print(f"   得分: {deep_result.best_score:.2f}")
    print()

    print("对比：")
    print(f"  快速优化 - 迭代: {len(quick_result.optimization_history)}, 得分: {quick_result.best_score:.2f}")
    print(f"  深度优化 - 迭代: {len(deep_result.optimization_history)}, 得分: {deep_result.best_score:.2f}")
    print()


def example_4_custom_configuration():
    """示例 4: 自定义配置"""
    print("=" * 70)
    print("  示例 4: 自定义优化器配置")
    print("=" * 70)
    print()

    llm_client = MockLLMClient()
    semantic_judge = MockSemanticJudge()

    # 自定义配置
    optimizer = PromptOptimizer(
        llm_client=llm_client,
        semantic_judge=semantic_judge,
        target_section='system',     # 只优化 system 部分
        initial_size=5,              # 5 个初始候选
        use_two_phase=True,          # 使用两阶段评估（成本优化）
        patience=3,                  # 耐心值 3
        min_improvement=0.05         # 最小改进 5%
    )

    print("自定义配置：")
    print(f"  - 目标部分: system")
    print(f"  - 初始候选数: 5")
    print(f"  - 两阶段评估: 是（先快速筛选，再精确评估）")
    print(f"  - 早停耐心值: 3")
    print(f"  - 最小改进: 5%")
    print()

    # 示例：优化 system prompt
    target = """
system = \"\"\"
你是一个数据分析助手。
请帮助用户分析数据并回答问题。
\"\"\"
"""

    context = {
        'agent_path': 'agent.dph',
        'failed_cases': [
            {'question': 'Q1', 'expected': 'A1', 'actual': 'Wrong'},
            {'question': 'Q2', 'expected': 'A2', 'actual': 'Wrong'}
        ],
        'knowledge': '分析规则：...',
        'error_types': ['logic_error', 'missing_info']
    }

    budget = Budget(max_iters=5, max_seconds=300)

    print("运行优化...")
    result = optimizer.optimize(target, context, budget)

    print(f"✓ 完成！最佳得分: {result.best_score:.2f}")
    print()


def main():
    """主函数"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║            PromptOptimizer 使用示例                              ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()

    # 运行示例
    example_1_basic_usage()
    example_2_optimize_file()
    example_3_quick_vs_deep()
    example_4_custom_configuration()

    print("=" * 70)
    print("  更多信息")
    print("=" * 70)
    print()
    print("📖 完整文档:")
    print("  - experiments/optimization/README.md")
    print("  - experiments/optimization/OPTIMIZATION_METHODS.md")
    print("  - experiments/optimization/PHASE2_IMPLEMENTATION_SUMMARY.md")
    print()
    print("🧪 测试用例:")
    print("  - tests/unittest/experiments/test_optimization_phase2.py")
    print()
    print("💡 提示:")
    print("  - 快速优化：使用 QuickPromptOptimizer")
    print("  - 深度优化：使用 DeepPromptOptimizer")
    print("  - 成本优化：启用两阶段评估（use_two_phase=True）")
    print("  - 安全第一：始终先 backup=True, replace=False")
    print()


if __name__ == '__main__':
    main()
