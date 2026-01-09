#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TwoPhaseEvaluator - 两阶段评估器

核心思想：
成本优化 - 先用快速近似评估筛选，再用精确评估验证。

工作流程：
1. Phase 1（筛选阶段）: 使用 ApproximateEvaluator 快速评估所有候选
2. 过滤：只保留有潜力的候选（基于置信度阈值）
3. Phase 2（验证阶段）: 使用 SemanticJudgeEvaluator 精确评估筛选后的候选
4. 合并：保留精确评估的结果，淘汰的候选使用近似评估结果

优势：
- 显著降低评估成本（避免对所有候选进行昂贵的精确评估）
- 保持评估质量（对有潜力的候选进行完整评估）
- 自适应策略（可根据预算动态调整两阶段的比例）
"""
from typing import Any
from dataclasses import dataclass

from experiments.optimization.types import Candidate, EvaluationResult
from experiments.optimization.protocols import Evaluator
from experiments.optimization.evaluators.approximate_evaluator import ApproximateEvaluator


@dataclass
class TwoPhaseConfig:
    """两阶段评估配置"""
    # 第一阶段（近似评估）
    phase1_min_confidence: float = 0.3  # 最低置信度
    phase1_max_candidates: int = 10     # 最多保留数

    # 第二阶段（精确评估）
    phase2_enable: bool = True          # 是否启用第二阶段
    phase2_min_candidates: int = 1      # 至少评估的候选数

    # 自适应策略
    adaptive: bool = True               # 是否自适应调整
    cost_threshold: float = 100.0       # 成本阈值（超过则更保守）


class TwoPhaseEvaluator(Evaluator):
    """
    两阶段评估器

    结合快速近似评估和精确评估，平衡成本与质量。
    """

    def __init__(
        self,
        phase1_evaluator: ApproximateEvaluator,
        phase2_evaluator: Evaluator,
        config: TwoPhaseConfig = None
    ):
        """
        Args:
            phase1_evaluator: 第一阶段评估器（快速近似）
            phase2_evaluator: 第二阶段评估器（精确评估）
            config: 配置参数
        """
        self.phase1 = phase1_evaluator
        self.phase2 = phase2_evaluator
        self.config = config or TwoPhaseConfig()

        # 统计信息
        self.stats = {
            'phase1_count': 0,
            'phase2_count': 0,
            'filtered_count': 0,
            'total_cost': 0.0
        }

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        单个候选的两阶段评估

        注：对于单个候选，通常直接使用 phase2（精确评估）
        """
        # 先进行快速评估
        phase1_result = self.phase1.evaluate(candidate, context)
        self.stats['phase1_count'] += 1

        # 如果置信度太低，直接返回 phase1 结果
        if not phase1_result.metadata.get('is_promising', False):
            self.stats['filtered_count'] += 1
            return phase1_result

        # 进行精确评估
        phase2_result = self.phase2.evaluate(candidate, context)
        self.stats['phase2_count'] += 1

        # 合并 metadata
        phase2_result.metadata['phase1_score'] = phase1_result.score
        phase2_result.metadata['phase1_confidence'] = phase1_result.metadata.get('is_promising', False)

        return phase2_result

    def batch_evaluate(
        self,
        candidates: list[Candidate],
        context: dict
    ) -> list[EvaluationResult]:
        """
        批量评估（两阶段优化的核心）

        工作流程：
        1. Phase 1: 快速评估所有候选
        2. 筛选：保留有潜力的候选
        3. Phase 2: 精确评估筛选后的候选
        4. 合并结果
        """
        if not candidates:
            return []

        # === Phase 1: 快速评估 ===
        print(f"  [TwoPhase] Phase 1: 快速评估 {len(candidates)} 个候选...")
        phase1_results = []
        for candidate in candidates:
            result = self.phase1.evaluate(candidate, context)
            phase1_results.append(result)
            self.stats['phase1_count'] += 1

        # 筛选有潜力的候选
        promising_candidates = []
        promising_indices = []
        filtered_results = []

        for i, result in enumerate(phase1_results):
            if result.metadata.get('is_promising', False):
                promising_candidates.append(candidates[i])
                promising_indices.append(i)
            else:
                # 淘汰的候选，保留 phase1 结果
                filtered_results.append((i, result))
                self.stats['filtered_count'] += 1

        print(f"  [TwoPhase] 筛选后保留 {len(promising_candidates)} 个候选（淘汰 {len(filtered_results)} 个）")

        # 如果没有候选通过筛选，返回 phase1 结果
        if not promising_candidates:
            return phase1_results

        # 自适应调整：如果候选数仍然很多，进一步限制
        if self.config.adaptive and len(promising_candidates) > self.config.phase1_max_candidates:
            # 按 phase1 分数排序，只保留 top-k
            sorted_pairs = sorted(
                zip(promising_candidates, promising_indices,
                    [phase1_results[i] for i in promising_indices]),
                key=lambda x: x[2].score,
                reverse=True
            )
            promising_candidates = [x[0] for x in sorted_pairs[:self.config.phase1_max_candidates]]
            promising_indices = [x[1] for x in sorted_pairs[:self.config.phase1_max_candidates]]

            print(f"  [TwoPhase] 自适应限制为 {len(promising_candidates)} 个候选")

        # === Phase 2: 精确评估 ===
        if self.config.phase2_enable:
            print(f"  [TwoPhase] Phase 2: 精确评估 {len(promising_candidates)} 个候选...")
            phase2_results_map = {}

            for i, candidate in enumerate(promising_candidates):
                original_idx = promising_indices[i]
                result = self.phase2.evaluate(candidate, context)

                # 记录 phase1 的信息
                result.metadata['phase1_score'] = phase1_results[original_idx].score
                result.metadata['evaluator'] = 'two_phase'

                phase2_results_map[original_idx] = result
                self.stats['phase2_count'] += 1

            # === 合并结果 ===
            final_results = []
            for i in range(len(candidates)):
                if i in phase2_results_map:
                    # 有 phase2 结果，使用精确评估
                    final_results.append(phase2_results_map[i])
                else:
                    # 被淘汰的候选，使用 phase1 结果
                    final_results.append(phase1_results[i])

            return final_results
        else:
            # 不启用 phase2，直接返回 phase1 结果
            return phase1_results

    def get_stats(self) -> dict:
        """获取统计信息"""
        total = self.stats['phase1_count']
        if total == 0:
            return self.stats

        return {
            **self.stats,
            'phase1_ratio': self.stats['phase1_count'] / total,
            'phase2_ratio': self.stats['phase2_count'] / total,
            'filter_ratio': self.stats['filtered_count'] / total,
            'cost_reduction': 1.0 - (self.stats['phase2_count'] / total)
        }

    def reset_stats(self):
        """重置统计信息"""
        self.stats = {
            'phase1_count': 0,
            'phase2_count': 0,
            'filtered_count': 0,
            'total_cost': 0.0
        }


class AdaptiveTwoPhaseEvaluator(TwoPhaseEvaluator):
    """
    自适应两阶段评估器

    根据预算和已用成本，动态调整两阶段的策略。
    """

    def __init__(
        self,
        phase1_evaluator: ApproximateEvaluator,
        phase2_evaluator: Evaluator,
        budget: 'Budget' = None,
        config: TwoPhaseConfig = None
    ):
        super().__init__(phase1_evaluator, phase2_evaluator, config)
        self.budget = budget
        self.iterations_completed = 0

    def batch_evaluate(
        self,
        candidates: list[Candidate],
        context: dict
    ) -> list[EvaluationResult]:
        """自适应批量评估"""
        # 估算剩余预算
        if self.budget and self.budget.max_iters:
            remaining_ratio = 1.0 - (self.iterations_completed / self.budget.max_iters)

            # 如果预算紧张（剩余<30%），更保守地使用 phase2
            if remaining_ratio < 0.3:
                original_max = self.config.phase1_max_candidates
                self.config.phase1_max_candidates = max(
                    self.config.phase2_min_candidates,
                    int(original_max * 0.5)  # 减少 50%
                )
                print(f"  [Adaptive] 预算紧张，phase2 限制调整为 {self.config.phase1_max_candidates}")

        # 执行评估
        results = super().batch_evaluate(candidates, context)

        # 更新迭代计数
        self.iterations_completed += 1

        return results


def create_default_two_phase_evaluator(
    phase1_evaluator: ApproximateEvaluator,
    phase2_evaluator: Evaluator,
    adaptive: bool = True
) -> TwoPhaseEvaluator:
    """创建默认配置的两阶段评估器"""
    config = TwoPhaseConfig(
        phase1_min_confidence=0.3,
        phase1_max_candidates=10,
        phase2_enable=True,
        phase2_min_candidates=1,
        adaptive=adaptive,
        cost_threshold=100.0
    )

    return TwoPhaseEvaluator(
        phase1_evaluator=phase1_evaluator,
        phase2_evaluator=phase2_evaluator,
        config=config
    )
