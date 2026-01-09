#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SemanticJudge: 基于跨 run 的失败分析，产出“语义梯度”诊断与候选注入。

实现方式：复用 dolphin CLI 与专用 agent（semantic_judge.dph），
输入 analysis_content（跨 run 汇总）、expected 的脱敏版本、actual 输出与可选业务知识，
输出结构化 JSON：score、error_types、action_vector、candidate_injects、rationale 等。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime
import subprocess

from dolphin.core.common.constants import (
    DOLPHIN_VARIABLES_OUTPUT_START,
    DOLPHIN_VARIABLES_OUTPUT_END,
)


class SemanticJudge:
    def __init__(self, data_loader, simulation_logs_dir=None):
        """
        Args:
            data_loader: ExperimentAnalyzer 实例（作为数据上下文与 dolphin 入口）
            simulation_logs_dir: 可选的simulation_logs目录路径，如果提供则优先使用
        """
        self.data_loader = data_loader
        self.root_dir = data_loader.root_dir
        self.dolphin_cmd = data_loader.dolphin_cmd
        self.reports_dir = data_loader.reports_dir

        # 如果提供了simulation_logs_dir，优先使用；否则回退到reports_dir
        # 这样可以保持向后兼容性，同时允许更好的日志组织
        if simulation_logs_dir:
            # 确保simulation_logs目录存在
            Path(simulation_logs_dir).mkdir(exist_ok=True)
            self.log_dir = simulation_logs_dir
            print(f"🔧 SemanticJudge日志将保存到: {simulation_logs_dir}")
        else:
            self.log_dir = self.reports_dir
            print(f"🔧 SemanticJudge日志将保存到: {self.reports_dir} (向后兼容模式)")

    @staticmethod
    def redact_expected(expected: str) -> str:
        """对期望答案做脱敏，避免泄露精确实体/数值。

        - 百分比 -> [PCT]
        - 连续数字（>=2位） -> [NUM]
        - 单字母/选项（A/B/C等）保留，但不应被模型引用为答案
        """
        if not expected:
            return ""
        s = str(expected)
        s = re.sub(r"\d+%", "[PCT]", s)
        s = re.sub(r"\d{2,}", "[NUM]", s)
        return s

    def evaluate(
        self, analysis_content: str, expected: str, actual: str, knowledge: str = ""
    ) -> dict | None:
        """
        运行语义裁判，返回诊断 JSON。
        返回字段建议：
          - score: 0~1
          - correct: bool
          - error_types: list[str]
          - missing_constraints: list[str]
          - action_vector: list[str]
          - candidate_injects: list[str]
          - rationale: str
        """
        judge_file = Path(__file__).parent / "dolphins" / "semantic_judge.dph"
        if not judge_file.exists():
            raise FileNotFoundError(f"semantic_judge.dph 不存在: {judge_file}")

        expected_redacted = self.redact_expected(expected)

        cmd_parts = [
            str(self.dolphin_cmd),
            "--folder",
            Path(__file__).parent / "dolphins",
            "--agent",
            "semantic_judge",
            "--analysis_content",
            analysis_content or "",
            "--expected_redacted",
            expected_redacted or "",
            "--actual_output",
            actual or "",
            "--busi_knowledge",
            knowledge or "",
            "--output-variables",
            "gradient",
        ]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"semantic_judge_{ts}.log"

        with open(log_file, "w", encoding="utf-8") as f:
            result = subprocess.run(
                cmd_parts,
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=str(self.root_dir),
                text=True,
            )

        if result.returncode != 0:
            # Do not fallback; surface failure to caller
            return None

        # 解析日志中的 DOLPHIN_VARIABLES_OUTPUT 区域
        try:
            with open(log_file, "r", encoding="utf-8") as rf:
                output = rf.read()
            gradient_str = self._extract_var_from_log(output, var_name="gradient")
            if not gradient_str:
                return None
            gradient = json.loads(gradient_str)
            # 基础字段容错
            gradient.setdefault("score", 0.0)
            gradient.setdefault("correct", False)
            gradient.setdefault("error_types", [])
            gradient.setdefault("missing_constraints", [])
            gradient.setdefault("action_vector", [])
            gradient.setdefault("candidate_injects", [])
            gradient.setdefault("rationale", "")
            return gradient
        except Exception:
            return None

    def evaluate_enhanced(
        self, evaluate_context: dict, knowledge: str = ""
    ) -> dict | None:
        """
        增强版语义评估，接收完整的评估上下文
        """
        judge_file = Path(__file__).parent / "dolphins" / "semantic_judge.dph"
        if not judge_file.exists():
            raise FileNotFoundError(f"semantic_judge.dph 不存在: {judge_file}")

        # 提取关键信息
        analysis_content = evaluate_context.get("analysis_content", "")
        predicted_result = evaluate_context.get("predicted_result", "")
        benchmark_context = self._prepare_benchmark_context(evaluate_context)

        # 提取期望答案信息
        expected_info = evaluate_context.get("expected_info", {})
        expected_redacted = self.redact_expected(expected_info.get("raw_expected", ""))

        cmd_parts = [
            str(self.dolphin_cmd),
            "--folder",
            Path(__file__).parent / "dolphins",
            "--agent",
            "semantic_judge",
            "--analysis_content",
            analysis_content or "",
            "--benchmark_context",
            benchmark_context or "",
            "--expected_redacted",
            expected_redacted or "",
            "--expected_info",
            json.dumps(expected_info, ensure_ascii=False),
            "--actual_output",
            predicted_result or "",
            "--busi_knowledge",
            knowledge or "",
            "--output-variables",
            "gradient",
        ]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"semantic_judge_enhanced_{ts}.log"

        with open(log_file, "w", encoding="utf-8") as f:
            result = subprocess.run(
                cmd_parts,
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=str(self.root_dir),
                text=True,
            )

        if result.returncode != 0:
            return None

        # 解析日志中的 DOLPHIN_VARIABLES_OUTPUT 区域
        try:
            with open(log_file, "r", encoding="utf-8") as rf:
                output = rf.read()
            gradient_str = self._extract_var_from_log(output, var_name="gradient")
            if not gradient_str:
                return None
            gradient = json.loads(gradient_str)
            # 基础字段容错
            gradient.setdefault("score", 0.0)
            gradient.setdefault("correct", False)
            gradient.setdefault("error_types", [])
            gradient.setdefault("missing_constraints", [])
            gradient.setdefault("action_vector", [])
            gradient.setdefault("candidate_injects", [])
            gradient.setdefault("rationale", "")
            return gradient
        except Exception:
            return None

    def _prepare_benchmark_context(self, evaluate_context: dict) -> str:
        return json.dumps(
            evaluate_context.get("benchmark_item", {}), ensure_ascii=False
        )

    @staticmethod
    def _extract_var_from_log(log_content: str, var_name: str) -> str | None:
        start_marker = DOLPHIN_VARIABLES_OUTPUT_START
        end_marker = DOLPHIN_VARIABLES_OUTPUT_END
        s = log_content.find(start_marker)
        if s == -1:
            return None
        e = log_content.find(end_marker, s)
        if e == -1:
            return None
        json_content = log_content[s + len(start_marker) : e].strip()
        try:
            variables = json.loads(json_content)
        except Exception:
            return None
        val = variables.get(var_name)
        # If the variable is already a structured object (dict/list),
        # return its JSON string so the caller can json.loads it.
        if isinstance(val, (dict, list)):
            try:
                return json.dumps(val, ensure_ascii=False)
            except Exception:
                return None
        if isinstance(val, str):
            return val
        return None
