#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimInject Optimizer 使用示例

演示如何使用统一优化框架进行 sim-inject 优化。
"""
import sys
from pathlib import Path

# Add experiments directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from optimization import (
    SimInjectOptimizer,
    Budget,
    get_registry,
)


def example_1_basic_usage():
    """示例1: 基本使用方式"""
    print("=" * 60)
    print("示例1: SimInjectOptimizer 基本使用")
    print("=" * 60)

    # 注意：这是一个演示示例，实际使用需要提供真实的 SemanticJudge 实例
    # from experiments.analyst.semantic_judge import SemanticJudge
    # semantic_judge = SemanticJudge(data_loader=your_data_loader)

    print("""
    # 1. 创建优化器
    optimizer = SimInjectOptimizer.create_default(
        semantic_judge=semantic_judge,
        inject_var='$injects'
    )

    # 2. 准备上下文
    context = {
        'agent_path': '/path/to/agent.dph',
        'analysis_content': 'cross-run failure analysis...',
        'expected': 'expected answer',
        'actual': 'actual output',
        'knowledge': 'business knowledge'
    }

    # 3. 设置预算
    budget = Budget(max_iters=5, max_seconds=300)

    # 4. 运行优化
    result = optimizer.optimize(
        target=None,
        context=context,
        budget=budget
    )

    # 5. 查看结果
    if result.best_candidate:
        print(f"最佳注入: {result.best_candidate.content}")
        print(f"最佳得分: {result.best_score}")
        print(f"优化轮数: {result.metrics['total_iterations']}")
    """)


def example_2_custom_configuration():
    """示例2: 自定义配置"""
    print("\n" + "=" * 60)
    print("示例2: 自定义优化器配置")
    print("=" * 60)

    print("""
    # 使用自定义参数创建优化器
    optimizer = SimInjectOptimizer(
        semantic_judge=semantic_judge,
        inject_var='$custom_injects',  # 自定义变量名
        top_k=5,                        # 每轮保留5个候选
        patience=3,                     # 早停容忍度为3轮
        min_improvement=0.02            # 最小改进阈值为0.02
    )

    # 设置更详细的预算
    budget = Budget(
        max_iters=10,        # 最多10轮迭代
        max_seconds=600,     # 最多10分钟
        max_tokens=100000    # Token预算
    )

    result = optimizer.optimize(target=None, context=context, budget=budget)
    """)


def example_3_using_registry():
    """示例3: 使用组件注册表"""
    print("\n" + "=" * 60)
    print("示例3: 使用组件注册表")
    print("=" * 60)

    registry = get_registry()

    # 列出所有可用组件
    components = registry.list_components()
    print("\n可用组件:")
    for comp_type, names in components.items():
        print(f"  {comp_type}: {', '.join(names)}")

    print("""
    # 通过注册表创建组件
    generator = registry.create_generator('sim_inject', inject_var='$injects', initial_size=5)
    selector = registry.create_selector('topk', k=3)
    controller = registry.create_controller('early_stopping', patience=2)

    # 组合成自定义优化器
    from optimization import EvolutionOptimizationEngine, SemanticJudgeEvaluator

    custom_optimizer = EvolutionOptimizationEngine(
        generator=generator,
        evaluator=SemanticJudgeEvaluator(semantic_judge),
        selector=selector,
        controller=controller
    )
    """)


def example_4_result_analysis():
    """示例4: 结果分析"""
    print("\n" + "=" * 60)
    print("示例4: 优化结果分析")
    print("=" * 60)

    print("""
    # 运行优化后分析结果
    result = optimizer.optimize(target=None, context=context, budget=budget)

    # 1. 最佳候选信息
    if result.best_candidate:
        print(f"最佳候选ID: {result.best_candidate.id}")
        print(f"父候选ID: {result.best_candidate.parent_id}")
        print(f"生成策略: {result.best_candidate.metadata.get('generation_strategy')}")
        print(f"内容:\\n{result.best_candidate.content}")

    # 2. 优化指标
    print(f"\\n优化指标:")
    print(f"  总迭代次数: {result.metrics['total_iterations']}")
    print(f"  总Token消耗: {result.metrics['total_cost_tokens']}")
    print(f"  得分提升: {result.metrics['score_improvement']}")

    # 3. 优化历史
    print(f"\\n优化历史:")
    for hist in result.optimization_history:
        print(f"  轮次 {hist['iteration']}: "
              f"种群={hist['population_size']}, "
              f"最佳={hist['best_score']:.3f}, "
              f"平均={hist['avg_score']:.3f}")

    # 4. 使用的组件
    print(f"\\n使用的组件:")
    for comp_type, comp_name in result.components_used.items():
        print(f"  {comp_type}: {comp_name}")
    """)


def example_5_execution_context():
    """示例5: ExecutionContext 详解"""
    print("\n" + "=" * 60)
    print("示例5: ExecutionContext 机制")
    print("=" * 60)

    print("""
    # SimInject 使用 Variable 模式的 ExecutionContext
    from optimization import ExecutionContextFactory

    exec_ctx = ExecutionContextFactory.create_for_sim_inject(
        base_path=Path('/path/to/agent.dph'),
        inject_var='$injects'
    )

    print(f"执行模式: {exec_ctx.mode}")           # 'variable'
    print(f"基础路径: {exec_ctx.base_path}")      # Path('/path/to/agent.dph')
    print(f"变量: {exec_ctx.variables}")          # {'$injects': ''}

    # 候选解会自动包含执行上下文
    candidate = Candidate(
        content="请注意数据验证",
        execution_context=exec_ctx
    )

    # Evaluator 会自动解析 ExecutionContext 并执行相应的评估
    # 对于 variable 模式，会构建类似这样的命令：
    # dolphin run /path/to/agent.dph --vars '{"$injects": "请注意数据验证"}'
    """)


def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("SimInject Optimizer 使用示例集")
    print("=" * 60)

    example_1_basic_usage()
    example_2_custom_configuration()
    example_3_using_registry()
    example_4_result_analysis()
    example_5_execution_context()

    print("\n" + "=" * 60)
    print("示例演示完成！")
    print("=" * 60)
    print("\n提示: 这些是演示代码，实际使用时需要:")
    print("  1. 提供真实的 SemanticJudge 实例")
    print("  2. 准备实际的 agent.dph 文件和评估数据")
    print("  3. 配置适当的预算和优化参数")
    print("\n详细文档请参考: experiments/analyst/optimization/README.md")


if __name__ == '__main__':
    main()
