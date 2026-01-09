#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SuccessiveHalvingSelector - 逐步淘汰选择器

核心思想：
受 Hyperband 和 Successive Halving 算法启发，逐轮淘汰表现较差的候选。
每轮只保留表现最好的一半（或指定比例），将资源集中在优秀的候选上。

优势：
- 资源高效：避免在差候选上浪费评估资源
- 探索平衡：早期保留多样性，后期聚焦最优
- 自适应：根据评估反馈动态调整

适用场景：
- 候选数量大时
- 评估成本高时
- 需要多轮迭代优化时
"""
from typing import Any
from dataclasses import dataclass
import math

from experiments.optimization.types import Candidate, EvaluationResult
from experiments.optimization.protocols import Selector


@dataclass
class SuccessiveHalvingConfig:
    """逐步淘汰配置"""
    halving_ratio: float = 0.5      # 每轮保留的比例（0.5 = 保留一半）
    min_candidates: int = 1         # 最少保留的候选数
    max_rounds: int = 10            # 最多淘汰轮数

    # 多样性保护
    diversity_boost: bool = True    # 是否保护多样性
    diversity_ratio: float = 0.2    # 多样性候选的比例


class SuccessiveHalvingSelector(Selector):
    """
    逐步淘汰选择器

    每次调用 select() 时，逐步减少候选数量，聚焦优秀候选。
    """

    def __init__(self, config: SuccessiveHalvingConfig = None):
        self.config = config or SuccessiveHalvingConfig()
        self.round = 0  # 当前轮次

    def select(
        self,
        candidates: list[Candidate],
        evaluations: list[EvaluationResult]
    ) -> list[Candidate]:
        """
        选择保留的候选

        策略：
        1. 按评估分数排序
        2. 保留 top (n * halving_ratio) 个候选
        3. 如果启用多样性保护，额外保留一些多样化候选
        """
        if not candidates:
            return []

        # 计算本轮应保留的数量
        current_size = len(candidates)
        target_size = max(
            self.config.min_candidates,
            int(current_size * self.config.halving_ratio)
        )

        # 按分数排序
        sorted_pairs = sorted(
            zip(candidates, evaluations),
            key=lambda x: x[1].score,
            reverse=True
        )

        # 选择 top-k
        selected = [pair[0] for pair in sorted_pairs[:target_size]]

        # 多样性保护：如果启用，额外保留一些多样化的候选
        if self.config.diversity_boost and current_size > target_size:
            diversity_count = max(1, int(target_size * self.config.diversity_ratio))
            diverse_candidates = self._select_diverse(
                candidates=candidates,
                evaluations=evaluations,
                already_selected=selected,
                count=diversity_count
            )
            selected.extend(diverse_candidates)

        # 限制总数不超过目标
        if len(selected) > target_size + int(target_size * self.config.diversity_ratio):
            selected = selected[:target_size + int(target_size * self.config.diversity_ratio)]

        self.round += 1
        print(f"  [SuccessiveHalving] Round {self.round}: {current_size} -> {len(selected)} 候选")

        return selected

    def _select_diverse(
        self,
        candidates: list[Candidate],
        evaluations: list[EvaluationResult],
        already_selected: list[Candidate],
        count: int
    ) -> list[Candidate]:
        """
        选择多样化的候选

        策略：
        1. 排除已选择的候选
        2. 计算候选之间的差异度
        3. 选择与已选候选差异最大的
        """
        # 构建候选池（排除已选择的）
        selected_ids = {c.id for c in already_selected}
        candidate_pool = [
            (c, e) for c, e in zip(candidates, evaluations)
            if c.id not in selected_ids
        ]

        if not candidate_pool:
            return []

        diverse = []

        # 简单策略：选择分数分布不同的候选
        # 将候选按分数分组
        score_ranges = self._group_by_score([e.score for e in evaluations])

        for score_range in score_ranges:
            for c, e in candidate_pool:
                if e.score in score_range and len(diverse) < count:
                    # 检查是否与已选候选有差异
                    if self._is_diverse(c, already_selected):
                        diverse.append(c)
                        break

            if len(diverse) >= count:
                break

        return diverse[:count]

    def _group_by_score(self, scores: list[float], num_groups: int = 3) -> list[tuple[float, float]]:
        """将分数分组"""
        if not scores:
            return []

        min_score = min(scores)
        max_score = max(scores)
        range_size = (max_score - min_score) / num_groups

        groups = []
        for i in range(num_groups):
            start = min_score + i * range_size
            end = start + range_size
            groups.append((start, end))

        return groups

    def _is_diverse(self, candidate: Candidate, others: list[Candidate]) -> bool:
        """
        判断候选是否与其他候选有差异

        简单策略：检查 metadata 或 content 的差异
        """
        # 检查 parent_id 差异（不同演化路径）
        candidate_parent = candidate.parent_id
        other_parents = {c.parent_id for c in others}

        if candidate_parent and candidate_parent not in other_parents:
            return True

        # 检查 metadata 中的 direction 差异
        candidate_direction = candidate.metadata.get('direction', '')
        other_directions = {c.metadata.get('direction', '') for c in others}

        if candidate_direction and candidate_direction not in other_directions:
            return True

        # 检查内容长度差异（作为简单的多样性指标）
        candidate_len = len(candidate.content)
        other_lens = [len(c.content) for c in others]
        avg_len = sum(other_lens) / len(other_lens) if other_lens else candidate_len

        if abs(candidate_len - avg_len) > avg_len * 0.2:  # 差异超过 20%
            return True

        return False

    def reset(self):
        """重置轮次计数"""
        self.round = 0


class AggressiveHalvingSelector(SuccessiveHalvingSelector):
    """
    激进淘汰选择器

    更快速地淘汰候选，适用于候选数量很大的场景。
    """

    def __init__(self):
        config = SuccessiveHalvingConfig(
            halving_ratio=0.3,  # 每轮只保留 30%
            min_candidates=1,
            max_rounds=10,
            diversity_boost=False  # 不保护多样性，纯粹按分数
        )
        super().__init__(config)


class ConservativeHalvingSelector(SuccessiveHalvingSelector):
    """
    保守淘汰选择器

    更缓慢地淘汰候选，保留更多的探索空间。
    """

    def __init__(self):
        config = SuccessiveHalvingConfig(
            halving_ratio=0.7,  # 每轮保留 70%
            min_candidates=2,
            max_rounds=15,
            diversity_boost=True,
            diversity_ratio=0.3  # 保留 30% 的多样性候选
        )
        super().__init__(config)


class DynamicHalvingSelector(Selector):
    """
    动态淘汰选择器

    根据候选的表现动态调整淘汰比例。
    如果候选质量差异大，淘汰更多；如果差异小，保留更多。
    """

    def __init__(self, base_ratio: float = 0.5, min_candidates: int = 1):
        self.base_ratio = base_ratio
        self.min_candidates = min_candidates
        self.round = 0

    def select(
        self,
        candidates: list[Candidate],
        evaluations: list[EvaluationResult]
    ) -> list[Candidate]:
        """动态选择"""
        if not candidates:
            return []

        # 计算分数的方差，判断候选质量差异
        scores = [e.score for e in evaluations]
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)

        # 根据方差调整保留比例
        if std_dev > 0.2:
            # 差异大，可以更激进地淘汰
            ratio = self.base_ratio * 0.8
        elif std_dev < 0.05:
            # 差异小，保守地保留更多
            ratio = self.base_ratio * 1.2
        else:
            # 正常情况
            ratio = self.base_ratio

        ratio = max(0.1, min(0.9, ratio))  # 限制在 [0.1, 0.9]

        # 计算保留数量
        target_size = max(self.min_candidates, int(len(candidates) * ratio))

        # 选择 top-k
        sorted_pairs = sorted(
            zip(candidates, evaluations),
            key=lambda x: x[1].score,
            reverse=True
        )
        selected = [pair[0] for pair in sorted_pairs[:target_size]]

        self.round += 1
        print(f"  [DynamicHalving] Round {self.round}: {len(candidates)} -> {len(selected)} "
              f"(ratio={ratio:.2f}, std={std_dev:.3f})")

        return selected

    def reset(self):
        """重置轮次"""
        self.round = 0


def create_default_successive_halving_selector(
    aggressive: bool = False,
    diversity: bool = True
) -> Selector:
    """创建默认配置的逐步淘汰选择器"""
    if aggressive:
        return AggressiveHalvingSelector()

    config = SuccessiveHalvingConfig(
        halving_ratio=0.5,
        min_candidates=1,
        max_rounds=10,
        diversity_boost=diversity,
        diversity_ratio=0.2 if diversity else 0.0
    )

    return SuccessiveHalvingSelector(config)
