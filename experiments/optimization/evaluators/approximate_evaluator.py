#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ApproximateEvaluator - 快速近似评估器

核心思想：
在完整的 SemanticJudge 评估之前，使用更快速的方法进行初步筛选。
这样可以显著降低评估成本，只对有潜力的候选进行精确评估。

快速评估策略：
1. 基于规则的快速判断（格式、长度等）
2. 简化的语义匹配（关键词、相似度）
3. 历史经验匹配（知识库）
4. 轻量级 LLM 调用（如果可用）
"""
from typing import Any
from dataclasses import dataclass
import re
from difflib import SequenceMatcher

from experiments.optimization.types import Candidate, EvaluationResult, SemanticJudgeDetail
from experiments.optimization.protocols import EvaluatorBase


@dataclass
class ApproximateConfig:
    """近似评估配置"""
    # 快速评估的权重
    format_weight: float = 0.3      # 格式匹配权重
    keyword_weight: float = 0.3     # 关键词匹配权重
    similarity_weight: float = 0.4   # 相似度权重

    # 阈值
    min_confidence: float = 0.3      # 最低置信度（低于此值直接淘汰）
    max_candidates: int = 10         # 最多保留的候选数

    # 关键词提取
    extract_keywords: bool = True


class ApproximateEvaluator(EvaluatorBase):
    """
    快速近似评估器

    用于 TwoPhaseEvaluator 的第一阶段，快速筛选候选。
    """

    def __init__(self, config: ApproximateConfig = None):
        self.config = config or ApproximateConfig()
        self._expected_keywords: set[str] = set()
        self._format_patterns: list[str] = []

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        快速评估单个候选

        评估维度：
        1. 格式匹配度
        2. 关键词覆盖度
        3. 与预期的相似度
        """
        # 提取上下文信息
        expected = context.get('expected', '')
        question = context.get('question', '')
        knowledge = context.get('knowledge', '')

        # 首次评估时，提取关键词和格式
        if self.config.extract_keywords and not self._expected_keywords:
            self._extract_expected_info(expected, question, knowledge)

        # 快速评估
        format_score = self._evaluate_format(candidate.content)
        keyword_score = self._evaluate_keywords(candidate.content)
        similarity_score = self._evaluate_similarity(candidate.content, expected)

        # 加权计算总分
        total_score = (
            format_score * self.config.format_weight +
            keyword_score * self.config.keyword_weight +
            similarity_score * self.config.similarity_weight
        )

        # 如果分数太低，直接标记为低置信度
        if total_score < self.config.min_confidence:
            is_promising = False
        else:
            is_promising = True

        # 构建评估结果
        details = SemanticJudgeDetail(
            error_types=['approximate_low_confidence'] if not is_promising else [],
            action_vector=[
                f'format_score: {format_score:.2f}',
                f'keyword_score: {keyword_score:.2f}',
                f'similarity_score: {similarity_score:.2f}'
            ],
            candidate_injects=[],
            rationale=f'快速评估 - 置信度: {"高" if is_promising else "低"}',
            phase='approx'
        )

        return EvaluationResult(
            score=total_score,
            detail={'is_promising': is_promising, 'semantic_detail': details},
            cost_tokens=10,  # 近似评估成本很低
            metadata={
                'evaluator': 'approximate',
                'is_promising': is_promising,
                'format_score': format_score,
                'keyword_score': keyword_score,
                'similarity_score': similarity_score
            }
        )

    def _extract_expected_info(self, expected: str, question: str, knowledge: str):
        """提取预期答案和问题中的关键信息"""
        # 提取关键词
        text = f"{expected} {question}"
        # 简单的关键词提取（去除常见停用词）
        stop_words = {'的', '了', '和', '是', '在', '有', '与', '等', '如', '为',
                     'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at'}

        words = re.findall(r'\w+', text.lower())
        self._expected_keywords = {w for w in words if w not in stop_words and len(w) > 1}

        # 提取可能的格式模式（如数字格式、选项格式等）
        # 检查是否是选择题格式（A/B/C/D）
        if re.search(r'\b[A-D]\b', expected):
            self._format_patterns.append(r'\b[A-D]\b')

        # 检查是否是数值格式
        if re.search(r'\d+\.?\d*', expected):
            self._format_patterns.append(r'\d+\.?\d*')

        # 检查是否是列表格式
        if re.search(r'[，,]', expected):
            self._format_patterns.append(r'[，,]')

    def _evaluate_format(self, content: str) -> float:
        """
        评估格式匹配度

        检查输出是否符合预期的格式模式
        """
        if not self._format_patterns:
            return 0.5  # 没有特定格式要求，给中等分

        matches = 0
        for pattern in self._format_patterns:
            if re.search(pattern, content):
                matches += 1

        return matches / len(self._format_patterns)

    def _evaluate_keywords(self, content: str) -> float:
        """
        评估关键词覆盖度

        检查输出中包含了多少预期的关键词
        """
        if not self._expected_keywords:
            return 0.5  # 没有关键词，给中等分

        content_words = set(re.findall(r'\w+', content.lower()))
        matched = self._expected_keywords & content_words
        coverage = len(matched) / len(self._expected_keywords)

        return coverage

    def _evaluate_similarity(self, content: str, expected: str) -> float:
        """
        评估与预期答案的相似度

        使用简单的字符串相似度算法
        """
        if not expected:
            return 0.5  # 没有预期答案，给中等分

        # 使用 SequenceMatcher 计算相似度
        similarity = SequenceMatcher(None, content.lower(), expected.lower()).ratio()

        return similarity

    def filter_promising(
        self,
        candidates: list[Candidate],
        evaluations: list[EvaluationResult]
    ) -> tuple[list[Candidate], list[EvaluationResult]]:
        """
        过滤出有潜力的候选

        用于两阶段评估的第一阶段，只保留值得精确评估的候选
        """
        promising = []
        promising_evals = []

        # 按分数排序
        sorted_pairs = sorted(
            zip(candidates, evaluations),
            key=lambda x: x[1].score,
            reverse=True
        )

        # 只保留高置信度的，且不超过最大数量
        for candidate, evaluation in sorted_pairs[:self.config.max_candidates]:
            if evaluation.metadata.get('is_promising', False):
                promising.append(candidate)
                promising_evals.append(evaluation)

        return promising, promising_evals


class RuleBasedApproximateEvaluator(ApproximateEvaluator):
    """
    基于规则的快速评估器

    适用于有明确规则的场景（如格式检查、必要字段验证等）
    """

    def __init__(self, rules: list[dict] = None, config: ApproximateConfig = None):
        """
        Args:
            rules: 评估规则列表，每个规则包含：
                - name: 规则名称
                - pattern: 正则表达式模式
                - weight: 权重
                - required: 是否必需
        """
        super().__init__(config)
        self.rules = rules or []

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """基于规则进行快速评估"""
        if not self.rules:
            # 没有规则，回退到父类的近似评估
            return super().evaluate(candidate, context)

        content = candidate.content
        total_score = 0.0
        total_weight = 0.0
        failed_required = []

        for rule in self.rules:
            name = rule.get('name', 'unnamed')
            pattern = rule.get('pattern', '')
            weight = rule.get('weight', 1.0)
            required = rule.get('required', False)

            if re.search(pattern, content):
                # 规则匹配
                total_score += weight
            else:
                # 规则未匹配
                if required:
                    failed_required.append(name)

            total_weight += weight

        # 如果有必需规则未满足，直接给低分
        if failed_required:
            normalized_score = 0.1
            error_types = [f'missing_required_{rule}' for rule in failed_required]
        else:
            normalized_score = total_score / total_weight if total_weight > 0 else 0.5
            error_types = []

        details = SemanticJudgeDetail(
            error_types=error_types,
            action_vector=[f'规则评估: {normalized_score:.2f}'],
            candidate_injects=[],
            rationale=f'基于规则的快速评估，未满足必需规则: {failed_required}' if failed_required else '规则评估通过',
            phase='approx'
        )

        return EvaluationResult(
            score=normalized_score,
            detail={'semantic_detail': details},
            cost_tokens=5,
            metadata={
                'evaluator': 'rule_based_approximate',
                'is_promising': normalized_score >= self.config.min_confidence,
                'failed_required': failed_required
            }
        )


def create_default_approximate_evaluator(
    min_confidence: float = 0.3,
    max_candidates: int = 10
) -> ApproximateEvaluator:
    """创建默认配置的近似评估器"""
    config = ApproximateConfig(
        format_weight=0.3,
        keyword_weight=0.3,
        similarity_weight=0.4,
        min_confidence=min_confidence,
        max_candidates=max_candidates,
        extract_keywords=True
    )
    return ApproximateEvaluator(config)
