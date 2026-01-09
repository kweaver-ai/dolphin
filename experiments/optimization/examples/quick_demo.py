#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速演示：展示优化框架的核心工作流程
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from optimization import (
    EvolutionOptimizationEngine,
    Candidate,
    EvaluationResult,
    ExecutionContext,
    Budget,
    get_registry,
)


# === Mock 组件（仅用于演示） ===

class SimpleGenerator:
    """简单的候选生成器（演示用）"""

    def initialize(self, target, context):
        """生成3个初始候选"""
        print("\n[Generator] 生成初始候选...")
        candidates = []
        for i in range(3):
            content = f"候选方案 {i+1}: 优化建议_{i+1}"
            candidate = Candidate(
                content=content,
                execution_context=ExecutionContext(mode='variable')
            )
            candidates.append(candidate)
            print(f"  ✓ {content}")
        return candidates

    def evolve(self, selected, evaluations, context):
        """基于最佳候选生成改进版本"""
        if not selected:
            return []

        print("\n[Generator] 基于最佳候选生成改进版本...")
        best = selected[0]
        improved = Candidate(
            content=f"{best.content} + 改进",
            execution_context=ExecutionContext(mode='variable'),
            parent_id=best.id
        )
        print(f"  ✓ {improved.content}")
        return [improved]


class SimpleEvaluator:
    """简单的评估器（演示用）"""

    def __init__(self):
        self.eval_count = 0

    def evaluate(self, candidate, context):
        """评估单个候选"""
        self.eval_count += 1
        # 模拟评分：每次评估分数递增
        score = 0.5 + (self.eval_count * 0.1)
        return EvaluationResult(score=min(score, 1.0), cost_tokens=100)

    def batch_evaluate(self, candidates, context):
        """批量评估"""
        print(f"\n[Evaluator] 评估 {len(candidates)} 个候选...")
        results = []
        for candidate in candidates:
            result = self.evaluate(candidate, context)
            print(f"  ✓ {candidate.content[:30]}... => 得分: {result.score:.2f}")
            results.append(result)
        return results


def demo_basic_flow():
    """演示1: 基本优化流程"""
    print("=" * 70)
    print("演示1: 基本优化流程")
    print("=" * 70)

    # 获取注册表
    registry = get_registry()

    # 创建组件
    generator = SimpleGenerator()
    evaluator = SimpleEvaluator()
    selector = registry.create_selector('topk', k=1)
    controller = registry.create_controller('budget')

    # 创建优化引擎
    engine = EvolutionOptimizationEngine(
        generator=generator,
        evaluator=evaluator,
        selector=selector,
        controller=controller
    )

    # 运行优化
    print("\n开始优化...")
    budget = Budget(max_iters=3)
    result = engine.optimize(target=None, context={}, budget=budget)

    # 展示结果
    print("\n" + "=" * 70)
    print("优化结果:")
    print("=" * 70)
    print(f"最佳候选: {result.best_candidate.content if result.best_candidate else 'None'}")
    print(f"最佳得分: {result.best_score:.2f}")
    print(f"总迭代: {result.metrics['total_iterations']}")
    print(f"总Token消耗: {result.metrics['total_cost_tokens']}")
    print(f"得分提升: {result.metrics['score_improvement']:.2f}")

    print("\n优化历史:")
    for hist in result.optimization_history:
        print(f"  轮次 {hist['iteration']}: "
              f"种群={hist['population_size']}, "
              f"最佳得分={hist['best_score']:.2f}, "
              f"平均得分={hist['avg_score']:.2f}")

    print("\n使用的组件:")
    for comp_type, comp_name in result.components_used.items():
        print(f"  {comp_type}: {comp_name}")


def demo_early_stopping():
    """演示2: 早停机制"""
    print("\n\n" + "=" * 70)
    print("演示2: 早停机制")
    print("=" * 70)

    registry = get_registry()

    # 使用早停控制器
    engine = EvolutionOptimizationEngine(
        generator=SimpleGenerator(),
        evaluator=SimpleEvaluator(),
        selector=registry.create_selector('topk', k=1),
        controller=registry.create_controller('early_stopping', patience=2, min_improvement=0.5)
    )

    print("\n说明: 使用早停控制器（patience=2, min_improvement=0.5）")
    print("如果连续2轮得分提升 < 0.5，将提前终止优化\n")

    budget = Budget(max_iters=10)  # 最多10轮，但会因为早停提前结束
    result = engine.optimize(target=None, context={}, budget=budget)

    print(f"\n实际执行轮数: {result.metrics['total_iterations']} (最大预算: 10)")
    print(f"最终得分: {result.best_score:.2f}")


def demo_component_registry():
    """演示3: 组件注册表"""
    print("\n\n" + "=" * 70)
    print("演示3: 组件注册表")
    print("=" * 70)

    registry = get_registry()
    components = registry.list_components()

    print("\n当前注册的组件:")
    for comp_type, names in components.items():
        print(f"\n{comp_type.upper()}:")
        for name in names:
            print(f"  - {name}")

    print("\n通过注册表创建组件:")
    selector = registry.create_selector('topk', k=5)
    print(f"  ✓ 创建了 TopKSelector(k=5): {type(selector).__name__}")

    controller = registry.create_controller('early_stopping', patience=3)
    print(f"  ✓ 创建了 EarlyStoppingController(patience=3): {type(controller).__name__}")


def main():
    """运行所有演示"""
    print("\n")
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  Evolution-Based Optimization Framework - 快速演示".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)

    demo_basic_flow()
    demo_early_stopping()
    demo_component_registry()

    print("\n\n" + "=" * 70)
    print("演示完成！")
    print("=" * 70)
    print("\n📖 更多信息:")
    print("  - 完整文档: experiments/analyst/optimization/README.md")
    print("  - 实施总结: experiments/analyst/optimization/IMPLEMENTATION_SUMMARY.md")
    print("  - 使用示例: experiments/analyst/optimization/examples/sim_inject_example.py")
    print("  - 运行测试: pytest tests/test_optimization.py -v")
    print("\n")


if __name__ == '__main__':
    main()
