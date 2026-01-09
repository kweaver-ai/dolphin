#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptOptimizer - Agent Prompt 源码优化器

核心思想：
直接优化 Agent 的 .dph 源文件，生成改进版本。

与 SimInjectOptimizer 的区别：
- SimInject: 运行时注入，临时生效，不修改源码
- PromptOptimizer: 设计时优化，修改源码，永久改进

工作流程：
1. 读取原始 .dph 文件
2. 使用 PromptModifierGenerator 生成改进版本
3. 使用 TwoPhaseEvaluator 评估（先快速筛选，再精确评估）
4. 使用 SuccessiveHalvingSelector 逐步淘汰
5. 返回最佳版本（可选择是否替换原文件）

安全机制：
- 作用域限制：默认只修改 system 部分
- 答案脱敏：禁止泄露测试答案
- 自动备份：修改前自动备份原文件
- 格式验证：确保生成有效的 .dph 文件
"""
from pathlib import Path
from typing import Any
from datetime import datetime
import shutil

from experiments.optimization.engine import EvolutionOptimizationEngine
from experiments.optimization.generators.prompt_modifier_generator import (
    PromptModifierGenerator,
    PromptModificationConstraint
)
from experiments.optimization.evaluators.approximate_evaluator import ApproximateEvaluator
from experiments.optimization.evaluators.two_phase_evaluator import TwoPhaseEvaluator
from experiments.optimization.evaluators.semantic_judge_evaluator import SemanticJudgeEvaluator
from experiments.optimization.selectors.successive_halving_selector import SuccessiveHalvingSelector
from experiments.optimization.controllers.budget_controller import (
    BudgetController,
    EarlyStoppingController
)
from experiments.optimization.types import Budget, OptimizationResult


class PromptOptimizer(EvolutionOptimizationEngine):
    """
    Agent Prompt 源码优化器

    基于演化优化框架，组合以下组件：
    - Generator: PromptModifierGenerator（生成 prompt 变体）
    - Evaluator: TwoPhaseEvaluator（两阶段评估，成本优化）
    - Selector: SuccessiveHalvingSelector（逐步淘汰）
    - Controller: EarlyStoppingController（早停控制）
    """

    def __init__(
        self,
        llm_client: Any,
        semantic_judge: Any = None,
        target_section: str = 'system',
        initial_size: int = 5,
        use_two_phase: bool = True,
        patience: int = 2,
        min_improvement: float = 0.05
    ):
        """
        Args:
            llm_client: LLM 客户端（用于生成 prompt 变体）
            semantic_judge: SemanticJudge 实例（用于精确评估）
            target_section: 优化目标部分（'system', 'tools', 'all'）
            initial_size: 初始候选数量
            use_two_phase: 是否使用两阶段评估（成本优化）
            patience: 早停的耐心值
            min_improvement: 最小改进阈值
        """
        # 创建组件
        generator = PromptModifierGenerator(
            llm_client=llm_client,
            initial_size=initial_size,
            constraints=PromptModificationConstraint(
                target_section=target_section,
                max_length_ratio=1.3,
                preserve_sections=[],
                forbidden_patterns=[
                    r'答案是.*',
                    r'correct answer is.*',
                    r'expected.*result.*is.*',
                ]
            )
        )

        # 创建评估器
        if use_two_phase and semantic_judge:
            # 两阶段评估：先快速筛选，再精确评估
            phase1 = ApproximateEvaluator()
            phase2 = SemanticJudgeEvaluator(semantic_judge)
            evaluator = TwoPhaseEvaluator(phase1, phase2)
        elif semantic_judge:
            # 只使用精确评估
            evaluator = SemanticJudgeEvaluator(semantic_judge)
        else:
            # 只使用近似评估
            evaluator = ApproximateEvaluator()

        # 创建选择器
        selector = SuccessiveHalvingSelector()

        # 创建控制器
        controller = EarlyStoppingController(
            patience=patience,
            min_improvement=min_improvement
        )

        super().__init__(
            generator=generator,
            evaluator=evaluator,
            selector=selector,
            controller=controller
        )

        self.llm_client = llm_client
        self.semantic_judge = semantic_judge
        self.target_section = target_section

    @classmethod
    def create_default(
        cls,
        llm_client: Any,
        semantic_judge: Any = None,
        target_section: str = 'system',
        aggressive: bool = False
    ) -> 'PromptOptimizer':
        """
        创建默认配置的 PromptOptimizer

        Args:
            llm_client: LLM 客户端
            semantic_judge: SemanticJudge 实例（可选）
            target_section: 优化目标部分
            aggressive: 是否使用激进的优化策略

        Returns:
            配置好的 PromptOptimizer
        """
        if aggressive:
            # 激进策略：更多初始候选，更严格的淘汰
            return cls(
                llm_client=llm_client,
                semantic_judge=semantic_judge,
                target_section=target_section,
                initial_size=10,
                use_two_phase=True,
                patience=1,
                min_improvement=0.1
            )
        else:
            # 保守策略：少量候选，耐心优化
            return cls(
                llm_client=llm_client,
                semantic_judge=semantic_judge,
                target_section=target_section,
                initial_size=5,
                use_two_phase=True,
                patience=3,
                min_improvement=0.05
            )

    def optimize_file(
        self,
        agent_path: str | Path,
        context: dict,
        budget: Budget,
        backup: bool = True,
        replace: bool = False
    ) -> OptimizationResult:
        """
        优化 agent 文件

        Args:
            agent_path: Agent 文件路径
            context: 优化上下文（failed_cases, knowledge, etc.）
            budget: 预算
            backup: 是否备份原文件
            replace: 是否用最佳版本替换原文件

        Returns:
            优化结果
        """
        agent_path = Path(agent_path)

        if not agent_path.exists():
            raise FileNotFoundError(f"Agent 文件不存在: {agent_path}")

        # 1. 读取原始文件
        original_content = agent_path.read_text(encoding='utf-8')

        # 2. 备份原文件
        if backup:
            backup_path = self._backup_file(agent_path)
            print(f"✓ 已备份原文件: {backup_path}")

        # 3. 补充上下文
        context['agent_path'] = str(agent_path)

        # 4. 运行优化
        print(f"开始优化 {agent_path.name} 的 {self.target_section} 部分...")
        result = self.optimize(
            target=original_content,
            context=context,
            budget=budget
        )

        # 5. 如果需要，替换原文件
        if replace and result.best_candidate:
            print(f"\n替换原文件...")
            agent_path.write_text(result.best_candidate.content, encoding='utf-8')
            print(f"✓ 已用最佳版本替换: {agent_path}")
            print(f"  最佳得分: {result.best_score:.2f}")
            print(f"  备份位置: {backup_path if backup else '(未备份)'}")

        return result

    def _backup_file(self, file_path: Path) -> Path:
        """备份文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = file_path.parent / '.backup'
        backup_dir.mkdir(exist_ok=True)

        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_dir / backup_name

        shutil.copy2(file_path, backup_path)
        return backup_path


class QuickPromptOptimizer(PromptOptimizer):
    """
    快速 Prompt 优化器

    适用于快速验证优化想法，牺牲一些质量换取速度。
    """

    def __init__(self, llm_client: Any, semantic_judge: Any = None):
        super().__init__(
            llm_client=llm_client,
            semantic_judge=semantic_judge,
            target_section='system',
            initial_size=3,      # 只生成 3 个初始候选
            use_two_phase=True,  # 使用两阶段评估节省成本
            patience=1,          # 耐心值为 1，快速收敛
            min_improvement=0.1  # 较高的改进阈值
        )


class DeepPromptOptimizer(PromptOptimizer):
    """
    深度 Prompt 优化器

    适用于系统性优化，追求最佳质量。
    """

    def __init__(self, llm_client: Any, semantic_judge: Any):
        super().__init__(
            llm_client=llm_client,
            semantic_judge=semantic_judge,
            target_section='system',
            initial_size=10,     # 更多初始候选
            use_two_phase=True,  # 使用两阶段评估
            patience=5,          # 更大的耐心值
            min_improvement=0.02 # 更小的改进阈值（更严格的收敛）
        )


def optimize_agent_file(
    agent_path: str | Path,
    llm_client: Any,
    semantic_judge: Any = None,
    failed_cases: list[dict] = None,
    knowledge: str = '',
    budget: Budget = None,
    target_section: str = 'system',
    backup: bool = True,
    replace: bool = False
) -> OptimizationResult:
    """
    便捷函数：优化 Agent 文件

    Args:
        agent_path: Agent 文件路径
        llm_client: LLM 客户端
        semantic_judge: SemanticJudge 实例
        failed_cases: 失败的测试用例
        knowledge: 业务知识
        budget: 优化预算
        target_section: 优化目标部分
        backup: 是否备份
        replace: 是否替换原文件

    Returns:
        优化结果
    """
    optimizer = PromptOptimizer.create_default(
        llm_client=llm_client,
        semantic_judge=semantic_judge,
        target_section=target_section
    )

    context = {
        'failed_cases': failed_cases or [],
        'knowledge': knowledge,
        'error_types': []  # 可以从 failed_cases 中提取
    }

    # 从 failed_cases 提取错误类型
    if failed_cases:
        error_types = set()
        for case in failed_cases:
            if 'error_type' in case:
                error_types.add(case['error_type'])
        context['error_types'] = list(error_types)

    budget = budget or Budget(max_iters=5, max_seconds=300)

    return optimizer.optimize_file(
        agent_path=agent_path,
        context=context,
        budget=budget,
        backup=backup,
        replace=replace
    )
