#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptModifierGenerator - 基于 LLM 生成 prompt 变体

核心思想：
1. 读取原始 .dph 文件内容
2. 基于 SemanticJudge 的反馈生成改进版本
3. 针对性地改进 system prompt、tool prompt 或结构
4. 使用 temp_file 执行模式进行测试

安全机制：
- 作用域限制：默认只修改 system 部分
- 答案脱敏：禁止在 prompt 中泄露测试答案
- 格式验证：确保生成的是有效的 .dph 文件
"""
from pathlib import Path
from typing import Any
import json
import re
from dataclasses import dataclass

from experiments.optimization.types import Candidate, ExecutionContext, EvaluationResult
from experiments.optimization.protocols import Generator


@dataclass
class PromptModificationConstraint:
    """Prompt 修改约束"""
    target_section: str = 'system'  # 'system', 'tools', 'all'
    max_length_ratio: float = 1.3  # 不超过原长度的 130%
    preserve_sections: list[str] = None  # 保持不变的部分
    forbidden_patterns: list[str] = None  # 禁止出现的模式（如答案泄露）

    def __post_init__(self):
        if self.preserve_sections is None:
            self.preserve_sections = []
        if self.forbidden_patterns is None:
            # 默认禁止直接包含答案的模式
            self.forbidden_patterns = [
                r'答案是.*',
                r'correct answer is.*',
                r'expected.*result.*is.*',
            ]


class PromptModifierGenerator(Generator):
    """
    基于 LLM 生成 Prompt 变体

    工作流程：
    1. initialize: 生成初始 prompt 变体
    2. evolve: 基于评估结果生成改进版本
    """

    def __init__(
        self,
        llm_client: Any,  # LLM 客户端（如 DolphinLanguage）
        initial_size: int = 3,
        constraints: PromptModificationConstraint = None
    ):
        self.llm_client = llm_client
        self.initial_size = initial_size
        self.constraints = constraints or PromptModificationConstraint()
        self._original_content: str | None = None
        self._original_length: int = 0

    def initialize(self, target: str, context: dict) -> list[Candidate]:
        """
        生成初始 prompt 变体

        Args:
            target: 原始 agent 内容（.dph 文件内容）
            context: 上下文信息
                - agent_path: agent 文件路径
                - failed_cases: 失败的测试用例
                - knowledge: 业务知识
                - error_types: 错误类型（来自 SemanticJudge）

        Returns:
            初始候选列表（使用 temp_file 执行模式）
        """
        self._original_content = target
        self._original_length = len(target)

        # 提取需要优化的部分
        section_to_optimize = self._extract_section(target, self.constraints.target_section)

        # 分析错误类型，生成针对性的改进方向
        error_types = context.get('error_types', [])
        improvement_directions = self._generate_improvement_directions(error_types, context)

        # 生成初始变体
        candidates = []
        for i, direction in enumerate(improvement_directions[:self.initial_size]):
            modified_content = self._generate_variant(
                original=target,
                section=section_to_optimize,
                direction=direction,
                context=context
            )

            # 验证修改是否合法
            if self._validate_modification(modified_content, context):
                # 创建临时文件执行上下文
                agent_path = Path(context.get('agent_path', 'agent.dph'))
                execution_context = ExecutionContext(
                    mode='temp_file',
                    base_path=agent_path.parent,
                    file_template=str(agent_path.name),
                    cleanup_policy='auto',
                    variables={}
                )

                candidates.append(Candidate(
                    content=modified_content,
                    execution_context=execution_context,
                    metadata={
                        'direction': direction,
                        'iteration': 0,
                        'modification_type': 'initial'
                    }
                ))

        return candidates

    def evolve(
        self,
        selected: list[Candidate],
        evaluations: list[EvaluationResult],
        context: dict
    ) -> list[Candidate]:
        """
        基于评估结果演化出新的 prompt 变体

        策略：
        1. 提取最佳候选的改进模式
        2. 结合 SemanticJudge 的反馈
        3. 生成深度改进版本
        """
        if not selected:
            return []

        # 找到最佳候选
        best_idx = max(range(len(evaluations)), key=lambda i: evaluations[i].score)
        best_candidate = selected[best_idx]
        best_eval = evaluations[best_idx]

        # 提取改进模式
        patterns = self._extract_improvement_patterns(best_candidate, best_eval)

        # 如果仍有错误，生成针对性改进
        if best_eval.detail and hasattr(best_eval.detail, 'error_types'):
            remaining_errors = best_eval.detail.error_types
            new_directions = self._generate_improvement_directions(remaining_errors, context)
        else:
            # 尝试进一步优化
            new_directions = self._generate_refinement_directions(best_candidate, context)

        # 生成新一代候选
        new_candidates = []
        for direction in new_directions[:len(selected)]:
            modified_content = self._generate_variant(
                original=best_candidate.content,
                section=self._extract_section(
                    best_candidate.content,
                    self.constraints.target_section
                ),
                direction=direction,
                context=context,
                parent_patterns=patterns
            )

            if self._validate_modification(modified_content, context):
                agent_path = Path(context.get('agent_path', 'agent.dph'))
                execution_context = ExecutionContext(
                    mode='temp_file',
                    base_path=agent_path.parent,
                    file_template=str(agent_path.name),
                    cleanup_policy='auto'
                )

                new_candidates.append(Candidate(
                    content=modified_content,
                    execution_context=execution_context,
                    parent_id=best_candidate.id,
                    metadata={
                        'direction': direction,
                        'iteration': best_candidate.metadata.get('iteration', 0) + 1,
                        'modification_type': 'evolved',
                        'parent_score': best_eval.score
                    }
                ))

        return new_candidates

    def _extract_section(self, content: str, section: str) -> str:
        """提取指定部分的内容"""
        if section == 'all':
            return content

        # 简化的 .dph 解析（实际应该更严谨）
        if section == 'system':
            # 提取 system prompt
            match = re.search(r'system\s*=\s*"""(.*?)"""', content, re.DOTALL)
            if match:
                return match.group(1)
        elif section == 'tools':
            # 提取 tools 部分
            match = re.search(r'tools\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if match:
                return match.group(1)

        return content

    def _generate_improvement_directions(
        self,
        error_types: list[str],
        context: dict
    ) -> list[str]:
        """根据错误类型生成改进方向"""
        directions = []

        # 根据错误类型映射到改进方向
        error_to_direction = {
            'logic_error': '加强逻辑推理能力，明确步骤',
            'tool_misuse': '优化工具使用说明和示例',
            'missing_info': '补充必要的领域知识',
            'wrong_format': '强化输出格式约束',
            'insufficient_context': '改进上下文理解指导'
        }

        for error_type in error_types:
            if error_type in error_to_direction:
                directions.append(error_to_direction[error_type])

        # 如果没有特定错误，使用通用改进方向
        if not directions:
            directions = [
                '优化角色定义和任务描述',
                '增强约束条件和注意事项',
                '改进示例和说明'
            ]

        return directions

    def _generate_refinement_directions(
        self,
        candidate: Candidate,
        context: dict
    ) -> list[str]:
        """生成进一步优化方向"""
        return [
            '进一步精简和明确表达',
            '增强关键步骤的说明',
            '优化信息组织结构'
        ]

    def _generate_variant(
        self,
        original: str,
        section: str,
        direction: str,
        context: dict,
        parent_patterns: list[str] = None
    ) -> str:
        """
        使用 LLM 生成 prompt 变体

        这里使用 LLM 根据改进方向生成新版本
        """
        # 构建 LLM prompt
        modification_prompt = f"""你是一个 Agent Prompt 优化专家。

当前任务：根据以下改进方向，优化 Agent 的 prompt。

原始内容：
```
{section}
```

改进方向：{direction}

业务知识：
{context.get('knowledge', '(无)')}

要求：
1. 保持原有功能不变
2. 针对性地应用改进方向
3. 确保表达清晰、简洁
4. 不要泄露测试答案
5. 长度不超过原内容的 130%

请直接输出优化后的内容，不要包含其他说明。
"""

        # 调用 LLM 生成（这里需要实际的 LLM 客户端）
        # 为了演示，先返回一个简单的模拟版本
        modified_section = self._mock_llm_generate(modification_prompt, direction, section)

        # 替换原内容中的对应部分
        if self.constraints.target_section == 'system':
            modified_content = re.sub(
                r'system\s*=\s*""".*?"""',
                f'system = """{modified_section}"""',
                original,
                flags=re.DOTALL
            )
        else:
            modified_content = original.replace(section, modified_section)

        return modified_content

    def _mock_llm_generate(self, prompt: str, direction: str, section: str) -> str:
        """
        模拟 LLM 生成（实际应该调用真实的 LLM）

        TODO: 替换为真实的 LLM 调用
        """
        # 简单的模拟：直接返回原内容（真实的 LLM 会生成改进版本）
        # 在实际使用时，这里会调用 LLM API 生成真正的优化内容
        return section.strip()

    def _extract_improvement_patterns(
        self,
        candidate: Candidate,
        evaluation: EvaluationResult
    ) -> list[str]:
        """从最佳候选中提取改进模式"""
        patterns = []

        # 提取有效的改进模式（基于 metadata 和 content）
        if candidate.metadata.get('direction'):
            patterns.append(candidate.metadata['direction'])

        # 如果评估结果中有 action_vector，提取关键词
        if evaluation.detail and hasattr(evaluation.detail, 'action_vector'):
            action_vector = evaluation.detail.action_vector
            if action_vector:
                patterns.extend(action_vector[:3])  # 取前3个行动建议

        return patterns

    def _validate_modification(self, content: str, context: dict) -> bool:
        """
        验证修改是否合法

        检查：
        1. 长度限制
        2. 禁止模式
        3. 基本格式
        """
        # 1. 检查长度
        if len(content) > self._original_length * self.constraints.max_length_ratio:
            return False

        # 2. 检查禁止模式（防止答案泄露）
        expected_answer = context.get('expected', '')
        if expected_answer and expected_answer.lower() in content.lower():
            # 如果修改后的内容包含答案，拒绝
            return False

        for pattern in self.constraints.forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return False

        # 3. 基本格式检查（.dph 文件应该包含必要的结构）
        # 放宽检查：只要包含 system、def、或者原内容的主要关键字即可
        has_structure = (
            'system' in content or
            'def ' in content or
            '"""' in content  # 至少有三引号字符串
        )

        if not has_structure:
            return False

        return True


def create_default_prompt_modifier(
    llm_client: Any,
    target_section: str = 'system',
    initial_size: int = 3
) -> PromptModifierGenerator:
    """创建默认配置的 PromptModifierGenerator"""
    constraints = PromptModificationConstraint(
        target_section=target_section,
        max_length_ratio=1.3,
        preserve_sections=[],
        forbidden_patterns=[
            r'答案是.*',
            r'correct answer is.*',
            r'expected.*result.*is.*',
        ]
    )

    return PromptModifierGenerator(
        llm_client=llm_client,
        initial_size=initial_size,
        constraints=constraints
    )
