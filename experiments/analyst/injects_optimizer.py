#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
注入内容优化器（纯语义驱动）

核心思想：基于 SemanticJudge 的诊断结果（score、error_types、action_vector、candidate_injects）
生成注入内容并控制收敛，损失为语义损失 loss = 1 - score。

安全约束：不泄露答案到注入内容中。
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import random

try:
    from .semantic_gradient import SemanticGradient
except ImportError:
    from semantic_gradient import SemanticGradient


class ErrorType(Enum):
    """错误类型分类"""

    FIELD_ERROR = "field_error"  # 字段使用错误
    CALCULATION_ERROR = "calc_error"  # 计算逻辑错误
    FORMAT_ERROR = "format_error"  # 输出格式错误
    INCOMPLETE = "incomplete"  # 结果不完整
    MAGNITUDE_ERROR = "magnitude"  # 数量级错误
    LOGIC_ERROR = "logic_error"  # 逻辑推理错误
    TIMEOUT_ERROR = "timeout_error"  # 执行超时
    UNKNOWN = "unknown"


@dataclass
class FailureRecord:
    """失败记录"""

    iteration: int
    inject_content: str
    actual_output: str
    error_type: ErrorType
    error_features: Dict
    loss: float


@dataclass
class OptimizationInfo:
    """优化信息"""

    gradient: Dict
    learning_rate: float
    convergence_status: str
    loss: float
    momentum_strength: float


class InjectsOptimizer:
    """
    基于梯度下降思想的注入内容优化器
    """

    def __init__(
        self,
        learning_rate: float = 1.0,
        momentum: float = 0.9,
        patience: int = 3,
        min_learning_rate: float = 0.1,
    ):
        self.learning_rate = learning_rate
        self.initial_learning_rate = learning_rate
        self.momentum = momentum
        self.patience = patience
        self.min_learning_rate = min_learning_rate

        # 状态记录
        self.velocity = {}
        self.failure_history: List[FailureRecord] = []
        self.loss_history: List[float] = []
        self.best_loss = float("inf")
        self.plateau_count = 0

        # Baseline记录
        self.baseline_result = None
        self.baseline_loss = None

        # 语义驱动上下文（可选）
        self._semantic_judge: Any | None = None
        self._semantic_analysis_content: str = ""
        self._semantic_knowledge: str = ""

    def optimize(
        self,
        actual: str,
        expected: str,
        knowledge_base: str,
        iteration: int,
        previous_inject: str = "",
    ) -> Tuple[str, OptimizationInfo]:
        """
        主优化函数
        返回: (优化后的注入内容, 优化信息)
        """
        # 语义驱动（必须启用）
        if not (self._semantic_judge is not None):
            raise RuntimeError(
                "Semantic mode not enabled. Call enable_semantic(...) before optimize()."
            )

        judge_grad_raw = self._semantic_judge.evaluate(
            analysis_content=self._semantic_analysis_content or "",
            expected=expected or "",
            actual=actual or "",
            knowledge=self._semantic_knowledge or knowledge_base or "",
        )

        semantic_grad = SemanticGradient.from_judge_result(judge_grad_raw)
        gradient = self._build_semantic_gradient(semantic_grad, actual, expected)
        loss = semantic_grad.loss
        self.loss_history.append(loss)
        self._update_momentum(gradient)
        adaptive_lr = self._get_adaptive_learning_rate(iteration)
        new_inject = self._generate_inject_from_gradient(
            gradient, knowledge_base, iteration, adaptive_lr
        )
        self._audit_inject(new_inject, expected)
        self._record_failure(iteration, new_inject, actual, gradient, loss)
        opt_info = OptimizationInfo(
            gradient=gradient,
            learning_rate=adaptive_lr,
            convergence_status=self._check_convergence(),
            loss=loss,
            momentum_strength=self._get_momentum_strength(),
        )
        return new_inject, opt_info

    def enable_semantic(self, judge: Any, analysis_content: str, knowledge: str = ""):
        """启用语义驱动模式。

        Args:
            judge: SemanticJudge 实例（需提供 evaluate 接口）
            analysis_content: 跨 run 汇总分析
            knowledge: 业务知识文本
        """
        self._semantic_judge = judge
        self._semantic_analysis_content = analysis_content or ""
        self._semantic_knowledge = knowledge or ""

    def _build_semantic_gradient(
        self, semantic_grad: SemanticGradient, actual: str, expected: str
    ) -> Dict:
        """将 SemanticGradient 映射为内部梯度结构。"""
        score = semantic_grad.score
        error_types = semantic_grad.error_types
        action_vector = semantic_grad.action_vector
        candidate_injects = semantic_grad.candidate_injects

        et = self._map_semantic_error_to_enum(
            error_types[0] if error_types else "unknown"
        )
        gradient = {
            "has_output": bool(actual and actual.strip()),
            "is_error": self._is_error_output(actual),
            "looks_complete": not (actual or "").endswith(("...", "省略")),
            "has_content": len(actual or "") > 20,
            "semantic_hint": (
                ("needs_refinement" if score < 0.6 else "ok") if actual else "no_output"
            ),
            "error_type": et,
            "magnitude": 1.0 - score,
            "action_vector": action_vector,
            "candidate_injects": candidate_injects,
            "score": score,
            "raw": semantic_grad.to_dict(),
        }

        if self.baseline_result is not None and self.baseline_loss is not None:
            current_loss = 1.0 - score
            baseline_loss = self.baseline_loss
            gradient["improved_from_baseline"] = current_loss < baseline_loss
            gradient["improvement_ratio"] = (
                (baseline_loss - current_loss) / baseline_loss
                if baseline_loss > 0
                else 0
            )
            gradient["baseline_comparison"] = {
                "improvement": gradient["improvement_ratio"],
                "baseline_loss": baseline_loss,
                "current_loss": current_loss,
                "is_better": current_loss < baseline_loss,
                "degradation_ratio": (
                    (current_loss - baseline_loss) / baseline_loss
                    if baseline_loss > 0
                    else 0
                ),
            }

        return gradient

    def _map_semantic_error_to_enum(self, err: str) -> ErrorType:
        """将语义裁判的错误类型字符串映射为内部枚举。"""
        if not err:
            return ErrorType.UNKNOWN
        e = err.lower()
        if any(k in e for k in ["calc", "计算", "数值", "公式"]):
            return ErrorType.CALCULATION_ERROR
        if any(k in e for k in ["字段", "field", "列", "维度"]):
            return ErrorType.FIELD_ERROR
        if any(k in e for k in ["格式", "format", "输出格式"]):
            return ErrorType.FORMAT_ERROR
        if any(k in e for k in ["不完整", "缺失", "incomplete"]):
            return ErrorType.INCOMPLETE
        if any(k in e for k in ["数量级", "magnitude"]):
            return ErrorType.MAGNITUDE_ERROR
        if any(k in e for k in ["逻辑", "reasoning", "logic"]):
            return ErrorType.LOGIC_ERROR
        if any(k in e for k in ["超时", "timeout"]):
            return ErrorType.TIMEOUT_ERROR
        return ErrorType.UNKNOWN

    def set_baseline(self, baseline_result: str, baseline_loss: float):
        """设置baseline以供对比"""
        self.baseline_result = baseline_result
        self.baseline_loss = baseline_loss
        print(f"📊 设置baseline: 损失={baseline_loss:.4f}")

    # 已移除：基于表层统计的损失函数，使用语义损失（1 - score）

    # 已移除：启发式梯度计算（统一改为语义裁判驱动）

    def _is_error_output(self, output: str) -> bool:
        """简单判断是否是错误输出"""
        if not output:
            return True
        lower_output = output.lower()
        return any(
            err in lower_output
            for err in ["error", "exception", "failed", "错误", "失败"]
        )

    def _count_stuck_iterations(self) -> int:
        """计算卡住的迭代次数"""
        if len(self.failure_history) < 2:
            return 0

        # 计算连续相同错误的次数
        current_error = self.failure_history[-1].error_type
        stuck_count = 0
        for record in reversed(self.failure_history):
            if record.error_type == current_error:
                stuck_count += 1
            else:
                break
        return stuck_count

    # 已移除：_classify_error/_classify_error_simple 与基础特征方法（语义驱动下不需要）

    # 已移除：启发式优化方向（由语义裁判的 action_vector/candidate_injects 取代）

    def _update_momentum(self, gradient: Dict):
        """更新动量"""
        error_type_key = gradient["error_type"].value

        if "error_type" not in self.velocity:
            self.velocity["error_type"] = {}

        if error_type_key not in self.velocity["error_type"]:
            self.velocity["error_type"][error_type_key] = 0

        # 更新动量
        self.velocity["error_type"][error_type_key] = (
            self.momentum * self.velocity["error_type"][error_type_key]
            + (1 - self.momentum) * gradient["magnitude"]
        )

    def _generate_inject_from_gradient(
        self, gradient: Dict, knowledge_base: str, iteration: int, learning_rate: float
    ) -> str:
        """
        注入生成：优先采用语义候选与行动向量，其次回退到 hint 组合
        """
        # 优先直接采用候选注入
        cand = gradient.get("candidate_injects") or []
        if isinstance(cand, list) and cand:
            return cand[0]

        # 其次采用行动向量
        actions = gradient.get("action_vector") or []
        if isinstance(actions, list) and actions:
            return "；".join(actions)

        inject_parts = []

        # 基于语义提示的简单指导
        semantic_hint = gradient.get("semantic_hint", "needs_refinement")

        if semantic_hint == "no_output":
            inject_parts.append("请确保提供有效的输出结果")
        elif semantic_hint == "execution_error":
            inject_parts.append("请检查并修正执行过程中的错误")
        elif semantic_hint == "incomplete_response":
            inject_parts.append("请确保输出完整的分析结果")
        elif semantic_hint == "too_brief":
            inject_parts.append("请提供更详细的分析和说明")
        else:
            inject_parts.append("请仔细检查分析质量，确保准确性")

        # 基于失败次数调整策略
        failure_count = gradient.get("failure_count", 0)
        if failure_count > 2:
            inject_parts.append("请尝试不同的分析方法")

        stuck_count = gradient.get("stuck_iterations", 0)
        if stuck_count > 1:
            inject_parts.append("请从新的角度重新思考问题")

        # 添加知识库内容（简化处理）
        if knowledge_base and len(knowledge_base) > 50:
            # 直接使用知识库的前200字符，让LLM自己理解相关性
            knowledge_excerpt = knowledge_base[:200].strip()
            if knowledge_excerpt:
                inject_parts.append(f"参考要点：{knowledge_excerpt}")

        # 基于baseline改进情况的指导
        if gradient.get("improved_from_baseline", False):
            improvement = gradient.get("improvement_ratio", 0)
            if improvement > 0.3:
                inject_parts.append("当前方向正确，继续优化")
            else:
                inject_parts.append("有所改进但仍需进一步优化")
        elif gradient.get("improvement_ratio", 0) < 0:
            inject_parts.append("当前方法可能有问题，请调整策略")

        # 组合所有部分
        base_inject = (
            "；".join(inject_parts) if inject_parts else "请仔细分析并提供准确结果"
        )

        # 根据迭代次数增强强调
        if iteration > 0:
            base_inject = f"第{iteration + 1}次提醒：{base_inject}"

        return base_inject

    # 已移除：知识提取/历史学习等启发式辅助方法

    def _generate_baseline_guidance(self, baseline_comparison: Dict) -> str:
        """基于baseline对比生成指导"""
        if not baseline_comparison:
            return ""

        guidance_parts = []

        # 根据改进/退化幅度提供通用指导
        if not baseline_comparison.get("is_better", False):
            degradation_ratio = baseline_comparison.get("degradation_ratio", 0)
            if degradation_ratio > 0.2:
                guidance_parts.append("当前方法可能导致结果退化，请调整策略")
            else:
                guidance_parts.append("改进有限，建议尝试不同的推理路径")
        else:
            guidance_parts.append("方向正确，建议继续沿此方向细化")

        # 如果改进很小，提供更激进的策略
        improvement = baseline_comparison.get("improvement", 0)
        if 0 < improvement < 0.1:  # 改进很小
            guidance_parts.append("需要更大的策略调整来实现突破")

        if guidance_parts:
            return f"基于baseline对比：{' '.join(guidance_parts)}"
        return ""

    # 已移除：失败模式与重复错误启发式（语义驱动下不需要）

    def _get_adaptive_learning_rate(self, iteration: int) -> float:
        """自适应学习率"""
        # 基础衰减
        decay_rate = 0.9
        base_lr = self.initial_learning_rate * (decay_rate**iteration)

        # 根据收敛状态调整
        if self._check_convergence() == "stuck":
            base_lr *= 1.5  # 增加探索
        elif self._check_convergence() == "oscillating":
            base_lr *= 0.5  # 减少震荡

        return max(base_lr, self.min_learning_rate)

    def _check_convergence(self) -> str:
        """检查收敛状态"""
        if len(self.loss_history) < 3:
            return "initializing"

        recent_losses = self.loss_history[-3:]

        # 检查是否卡住
        if len(self.failure_history) >= 2:
            recent_errors = [f.error_type for f in self.failure_history[-2:]]
            if recent_errors[0] == recent_errors[1]:
                return "stuck"

        # 检查是否震荡
        if len(recent_losses) >= 3:
            if (
                recent_losses[0] < recent_losses[1] > recent_losses[2]
                or recent_losses[0] > recent_losses[1] < recent_losses[2]
            ):
                return "oscillating"

        # 检查是否改善
        if recent_losses[-1] < recent_losses[0]:
            return "improving"

        return "plateau"

    def should_early_stop(self) -> bool:
        """检查是否应该早停"""
        if len(self.loss_history) < self.patience:
            return False

        # 检查最近几次是否没有改善
        recent_losses = self.loss_history[-self.patience :]
        if max(recent_losses) - min(recent_losses) < 0.01:
            self.plateau_count += 1
            return self.plateau_count >= 2

        self.plateau_count = 0
        return False

    def random_exploration(self, knowledge_base: str) -> str:
        """随机探索新策略"""
        strategies = [
            "请从不同角度重新分析问题",
            "建议简化查询逻辑，分步骤执行",
            "请检查是否遗漏了关键的过滤条件",
            "尝试使用不同的数据聚合方式",
        ]

        base_strategy = random.choice(strategies)

        if knowledge_base and len(knowledge_base) > 100:
            # 随机选择知识库的一部分
            start_pos = random.randint(0, len(knowledge_base) - 100)
            knowledge_fragment = knowledge_base[start_pos : start_pos + 200]
            return f"{base_strategy}。参考知识：{knowledge_fragment}"

        return base_strategy

    def _record_failure(
        self,
        iteration: int,
        inject_content: str,
        actual_output: str,
        gradient: Dict,
        loss: float,
    ):
        """记录失败信息"""
        record = FailureRecord(
            iteration=iteration,
            inject_content=inject_content,
            actual_output=actual_output[:500],  # 限制长度
            error_type=gradient["error_type"],
            error_features=gradient.get("features", {}),
            loss=loss,
        )
        self.failure_history.append(record)

        # 只保留最近的记录
        if len(self.failure_history) > 10:
            self.failure_history = self.failure_history[-10:]

    def _audit_inject(self, inject_content: str, expected: str):
        """审计注入内容，确保不包含答案"""
        # 检查直接的答案关键词
        dangerous_patterns = [
            r"答案是",
            r"结果是.*\d",  # 只匹配"结果是"后面跟数字的情况
            r"应该是",
            r"正确答案",
            r"计算结果.*\d",  # 只匹配"计算结果"后面跟数字的情况
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, inject_content):
                raise ValueError(f"注入内容包含危险模式: {pattern}")

        # 提取答案中的关键片段（避免短词误判）
        answer_fragments = []
        words = expected.split()
        for i in range(len(words)):
            for j in range(i + 2, min(i + 6, len(words) + 1)):  # 2-5个词的片段
                fragment = " ".join(words[i:j])
                if len(fragment) > 8:  # 只检查较长的片段，提高阈值
                    answer_fragments.append(fragment)

        for fragment in answer_fragments:
            if fragment.lower() in inject_content.lower():
                raise ValueError(f"注入内容可能泄露答案片段: {fragment[:20]}...")

        # 检查具体数值（3位以上，降低阈值提高安全性）
        expected_numbers = re.findall(r"\d{3,}", expected)
        inject_numbers = re.findall(r"\d{3,}", inject_content)

        for num in inject_numbers:
            if num in expected_numbers:
                raise ValueError(f"注入内容包含答案中的具体数值: {num}")

        # 检查百分比
        expected_percentages = re.findall(r"\d+%", expected)
        inject_percentages = re.findall(r"\d+%", inject_content)

        for pct in inject_percentages:
            if pct in expected_percentages:
                raise ValueError(f"注入内容包含答案中的具体百分比: {pct}")

        return True

    # 已移除：格式类型检测（启发式）

    # 已移除：格式/结构相关的启发式函数

    # 已移除：结构/完整性/数值存在性/误差量级等启发式函数

    def _analyze_previous_inject(self, previous_inject: str) -> Dict:
        """分析之前的注入内容"""
        if not previous_inject:
            return {}

        return {
            "length": len(previous_inject),
            "has_emphasis": any(
                word in previous_inject for word in ["重要", "注意", "关键"]
            ),
            "has_specific_guidance": len(
                re.findall(r"字段|表|计算|公式", previous_inject)
            )
            > 0,
            "iteration_mentioned": bool(re.search(r"第\d+次", previous_inject)),
        }

    def _combine_inject_components(self, components: List[str]) -> str:
        """组合注入组件"""
        if not components:
            return "请仔细分析问题并给出准确结果"

        # 去重并组合
        unique_components = list(dict.fromkeys(components))  # 保持顺序的去重
        return "；".join(unique_components)

    # 已移除：启发式 baseline 对比（语义模式由 _build_semantic_gradient 内部完成）

    def _get_momentum_strength(self) -> float:
        """获取当前动量强度"""
        if not self.velocity.get("error_type"):
            return 0.0

        return sum(self.velocity["error_type"].values()) / len(
            self.velocity["error_type"]
        )

    def get_optimization_summary(self) -> Dict:
        """获取优化总结"""
        if not self.failure_history:
            return {}

        error_types = [f.error_type.value for f in self.failure_history]
        error_counts = {et: error_types.count(et) for et in set(error_types)}

        return {
            "total_iterations": len(self.failure_history),
            "error_distribution": error_counts,
            "loss_trend": (
                self.loss_history[-5:]
                if len(self.loss_history) >= 5
                else self.loss_history
            ),
            "best_loss": self.best_loss,
            "final_convergence_status": self._check_convergence(),
            "momentum_info": self.velocity,
        }
