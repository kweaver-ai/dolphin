#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SemanticGradient: 封装语义梯度数据的访问逻辑，统一处理不同数据结构格式
"""

from typing import List, Any, Optional, Dict
from dataclasses import dataclass


@dataclass
class SemanticGradient:
    """
    语义梯度数据的封装类，统一处理SemanticJudge返回的复杂嵌套数据结构

    SemanticJudge可能返回以下格式之一：
    1. 扁平格式: {'score': 0.8, 'candidate_injects': [...], ...}
    2. 嵌套格式: {'output_var_value': {'score': 0.8, 'candidate_injects': [...]}, 'score': 0.0, ...}
    """

    _raw_data: Dict[str, Any]
    _score: float
    _correct: bool
    _error_types: List[str]
    _missing_constraints: List[str]
    _action_vector: List[str]
    _candidate_injects: List[str]
    _rationale: str

    @classmethod
    def from_judge_result(cls, judge_result: Dict[str, Any]) -> "SemanticGradient":
        """
        从SemanticJudge的原始结果创建SemanticGradient实例

        Args:
            judge_result: SemanticJudge返回的原始字典数据

        Returns:
            SemanticGradient实例

        Raises:
            ValueError: 当数据格式无效时
        """
        if not isinstance(judge_result, dict):
            raise ValueError(
                f"judge_result必须是字典类型，实际类型: {type(judge_result)}"
            )

        # 优先从output_var_value获取数据，回退到根级别
        output_var_value = judge_result.get("output_var_value", {})

        def _get_field(field_name: str, default_value: Any = None) -> Any:
            """优先从output_var_value获取字段，回退到根级别"""
            if isinstance(output_var_value, dict) and field_name in output_var_value:
                return output_var_value[field_name]
            return judge_result.get(field_name, default_value)

        # 提取和验证各个字段
        score = _get_field("score", 0.0)
        if not isinstance(score, (int, float)):
            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0.0

        correct = _get_field("correct", False)
        if not isinstance(correct, bool):
            correct = bool(correct)

        error_types = _get_field("error_types", [])
        if not isinstance(error_types, list):
            error_types = []
        error_types = [str(et) for et in error_types if et]

        missing_constraints = _get_field("missing_constraints", [])
        if not isinstance(missing_constraints, list):
            missing_constraints = []
        missing_constraints = [str(mc) for mc in missing_constraints if mc]

        action_vector = _get_field("action_vector", [])
        if not isinstance(action_vector, list):
            action_vector = []
        action_vector = [str(av) for av in action_vector if av]

        candidate_injects = _get_field("candidate_injects", [])
        if not isinstance(candidate_injects, list):
            candidate_injects = []
        candidate_injects = [str(ci) for ci in candidate_injects if ci]

        rationale = _get_field("rationale", "")
        if not isinstance(rationale, str):
            rationale = str(rationale) if rationale else ""

        return cls(
            _raw_data=judge_result,
            _score=score,
            _correct=correct,
            _error_types=error_types,
            _missing_constraints=missing_constraints,
            _action_vector=action_vector,
            _candidate_injects=candidate_injects,
            _rationale=rationale,
        )

    @property
    def score(self) -> float:
        """语义得分 (0.0-1.0)"""
        return self._score

    @property
    def correct(self) -> bool:
        """是否语义正确"""
        return self._correct

    @property
    def error_types(self) -> List[str]:
        """错误类型列表"""
        return self._error_types.copy()

    @property
    def missing_constraints(self) -> List[str]:
        """缺失约束列表"""
        return self._missing_constraints.copy()

    @property
    def action_vector(self) -> List[str]:
        """动作向量列表"""
        return self._action_vector.copy()

    @property
    def candidate_injects(self) -> List[str]:
        """候选注入列表"""
        return self._candidate_injects.copy()

    @property
    def rationale(self) -> str:
        """判断理由"""
        return self._rationale

    @property
    def loss(self) -> float:
        """语义损失 (1.0 - score)"""
        return 1.0 - self._score

    @property
    def has_candidate_injects(self) -> bool:
        """是否有候选注入"""
        return len(self._candidate_injects) > 0

    @property
    def has_action_vector(self) -> bool:
        """是否有动作向量"""
        return len(self._action_vector) > 0

    @property
    def primary_error_type(self) -> Optional[str]:
        """主要错误类型（第一个错误类型）"""
        return self._error_types[0] if self._error_types else None

    def get_best_inject_candidate(self) -> Optional[str]:
        """获取最佳注入候选（第一个候选注入）"""
        return self._candidate_injects[0] if self._candidate_injects else None

    def get_action_summary(self) -> str:
        """获取动作向量摘要（用分号连接）"""
        return "；".join(self._action_vector) if self._action_vector else ""

    def is_valid_for_optimization(self) -> bool:
        """判断是否适合用于优化（有候选注入或动作向量）"""
        return self.has_candidate_injects or self.has_action_vector

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于序列化）"""
        return {
            "score": self._score,
            "correct": self._correct,
            "error_types": self._error_types,
            "missing_constraints": self._missing_constraints,
            "action_vector": self._action_vector,
            "candidate_injects": self._candidate_injects,
            "rationale": self._rationale,
            "loss": self.loss,
            "has_candidate_injects": self.has_candidate_injects,
            "has_action_vector": self.has_action_vector,
        }

    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"SemanticGradient(score={self._score:.3f}, "
            f"correct={self._correct}, "
            f"candidates={len(self._candidate_injects)}, "
            f"actions={len(self._action_vector)})"
        )

    def __repr__(self) -> str:
        """详细字符串表示"""
        return (
            f"SemanticGradient("
            f"score={self._score}, "
            f"correct={self._correct}, "
            f"error_types={self._error_types}, "
            f"candidate_injects={len(self._candidate_injects)}, "
            f"action_vector={len(self._action_vector)})"
        )


def aggregate_gradients(
    gradients: List[SemanticGradient], top_n: int = 1, history: List[str] = None
) -> Optional[str]:
    """
    聚合多个语义梯度，生成最佳注入内容，支持历史感知避免重复

    Args:
        gradients: SemanticGradient实例列表
        top_n: 返回前N个最受欢迎的候选注入，默认为1
        history: 历史注入内容列表，用于避免重复

    Returns:
        聚合后的注入内容，如果无法生成则返回None
    """
    if not gradients:
        return None

    history = history or []

    # 投票选择最佳候选注入，考虑历史避免重复
    votes: Dict[str, float] = {}  # 使用float支持加权

    for grad in gradients:
        # 基于梯度分数加权投票
        weight = max(0.1, 1.0 - grad.score)  # 分数越低权重越高

        for candidate in grad.candidate_injects:
            if not candidate.strip():
                continue

            # 历史惩罚：如果候选注入与历史重复，降低权重
            history_penalty = 1.0
            for hist in history:
                if candidate == hist:
                    history_penalty = 0.1  # 完全相同大幅降权
                elif _similarity(candidate, hist) > 0.8:
                    history_penalty = 0.3  # 高相似度降权
                elif _similarity(candidate, hist) > 0.5:
                    history_penalty = 0.7  # 中等相似度轻微降权

            final_weight = weight * history_penalty
            votes[candidate] = votes.get(candidate, 0) + final_weight

    if votes:
        # 过滤掉权重过低的候选（避免完全重复）
        filtered_votes = {k: v for k, v in votes.items() if v > 0.05}

        if filtered_votes:
            # 按权重排序，选择前top_n个
            sorted_candidates = sorted(
                filtered_votes.items(), key=lambda x: x[1], reverse=True
            )
            selected_candidates = sorted_candidates[:top_n]
            selected_texts = [candidate for candidate, _ in selected_candidates]

            if top_n == 1:
                return selected_texts[0] if selected_texts else None
            else:
                # 返回多个候选，用分号连接
                return "；".join(selected_texts)

    # 回退：汇总动作向量，同样考虑历史去重
    all_actions = []
    seen_actions = set()

    # 优先选择来自高损失（低分数）梯度的动作
    sorted_grads = sorted(gradients, key=lambda g: g.score)  # 分数低的优先

    for grad in sorted_grads:
        for action in grad.action_vector:
            if not action.strip() or action in seen_actions:
                continue

            # 检查与历史的重复性
            is_novel = True
            for hist in history:
                if action in hist or _similarity(action, hist) > 0.6:
                    is_novel = False
                    break

            if is_novel:
                all_actions.append(action)
                seen_actions.add(action)
                if len(all_actions) >= 6:  # 限制最多6个动作
                    break

        if len(all_actions) >= 6:
            break

    if all_actions:
        return "；".join(all_actions)

    return None


def _similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度

    Args:
        text1, text2: 要比较的文本

    Returns:
        相似度分数 (0.0-1.0)
    """
    if not text1 or not text2:
        return 0.0

    # 简单的字符级相似度计算
    text1, text2 = text1.strip(), text2.strip()
    if text1 == text2:
        return 1.0

    # 使用集合交集计算相似度
    words1 = set(text1.split())
    words2 = set(text2.split())

    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0
