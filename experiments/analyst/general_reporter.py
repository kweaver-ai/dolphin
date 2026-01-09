#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
总体报告生成器

负责生成实验的总体分析报告，包括：
- 配置对比分析
- 准确率统计
- 延迟性能分析
- Token消耗分析
- 调用链分析
- 深度分析（使用general.dph）
"""

import os
import pandas as pd
import yaml
import json
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from dolphin.core.common.constants import (
    DOLPHIN_VARIABLES_OUTPUT_START,
    DOLPHIN_VARIABLES_OUTPUT_END,
)

try:
    from .base_analyzer import BaseAnalyzer
except ImportError:
    from base_analyzer import BaseAnalyzer


class GeneralReporter(BaseAnalyzer):
    """总体报告生成器"""

    def __init__(self, data_loader):
        """
        初始化报告生成器

        Args:
            data_loader: ExperimentDataLoader实例，用于加载实验数据
        """
        # 调用父类初始化
        super().__init__(data_loader)

    def generate_report(self):
        """生成总体分析报告"""
        print("🔍 开始生成总体分析报告...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"{self.experiment_name}_general_report_{timestamp}"

        # 分析数据
        config_df = self.data_loader.analyze_configs()
        accuracy_df = self.data_loader.analyze_accuracy()
        factor_groups = self.data_loader.analyze_by_factors()
        individual_variables = self.data_loader.analyze_individual_variables()
        run_labels = self.data_loader.generate_run_labels()
        results_df = self.data_loader.create_detailed_comparison()
        consecutive_patterns = self.data_loader.detect_consecutive_errors(results_df)
        latency_df = self.data_loader.analyze_latency()
        token_df = self.data_loader.analyze_token_consumption()
        impact_df = self.data_loader.analyze_config_impact(config_df, accuracy_df)
        call_chain_summary = self.data_loader.analyze_all_call_chains()

        # 生成深度分析
        print("📊 正在调用LLM进行深度分析...")
        deep_analysis = self._generate_deep_analysis(
            config_df,
            accuracy_df,
            latency_df,
            token_df,
            factor_groups,
            call_chain_summary,
        )

        # 日志分析
        log_analyses = {}
        for run in self.data_loader.runs:
            run_dir = self.experiment_path / run["run_id"]
            log_analyses[run["run_id"]] = self.data_loader.analyze_case_logs(run_dir)

        # 生成文本报告
        report_path = self._write_report(
            report_name,
            config_df,
            accuracy_df,
            latency_df,
            token_df,
            factor_groups,
            impact_df,
            run_labels,
            results_df,
            consecutive_patterns,
            call_chain_summary,
            deep_analysis,
            log_analyses,
            individual_variables,
        )

        # 生成CSV详细数据
        csv_path = self.reports_dir / f"{report_name}.csv"
        results_df.to_csv(csv_path, index=False, encoding="utf-8")

        print("✅ 总体分析报告生成完成!")
        print(f"📊 查看报告: {report_path}")
        print(f"📈 详细数据: {csv_path}")

        return report_path, csv_path

    def _generate_deep_analysis(
        self,
        config_df,
        accuracy_df,
        latency_df,
        token_df,
        factor_groups,
        call_chain_summary,
    ):
        """生成深度分析内容"""
        # 准备实验数据结构
        experiments = []
        for _, config_row in config_df.iterrows():
            run_id = config_row["Run ID"]

            # 查找对应的准确率、延迟、token数据
            acc_row = (
                accuracy_df[accuracy_df["Run ID"] == run_id].iloc[0]
                if not accuracy_df[accuracy_df["Run ID"] == run_id].empty
                else None
            )
            lat_row = (
                latency_df[latency_df["Run ID"] == run_id].iloc[0]
                if not latency_df[latency_df["Run ID"] == run_id].empty
                else None
            )
            tok_row = (
                token_df[token_df["Run ID"] == run_id].iloc[0]
                if not token_df[token_df["Run ID"] == run_id].empty
                else None
            )

            exp_data = {
                "run_name": run_id,
                "Model Name": config_row.get("Model Name", ""),
                "Encoded Variables": config_row.get("Variables", ""),
                "Accuracy": (
                    float(acc_row["Accuracy"].rstrip("%")) / 100
                    if acc_row is not None
                    else 0
                ),
                "Latency P50 (seconds)": (
                    lat_row.get("P50 Latency", 0) if lat_row is not None else 0
                ),
                "Total Tokens": (
                    tok_row.get("Total All Tokens", 0) if tok_row is not None else 0
                ),
                "Tool Calls": (
                    tok_row.get("Total Tool Calls", 0) if tok_row is not None else 0
                ),
                "Interactions": 0,  # Will be filled after checking call_chain_summary structure
            }
            experiments.append(exp_data)

        # Fill in interactions from call_chain_summary if available
        if call_chain_summary and isinstance(call_chain_summary, dict):
            run_summaries = call_chain_summary.get("run_summaries", [])
            if isinstance(run_summaries, list):
                for exp_data in experiments:
                    run_id = exp_data["run_name"]
                    # Find the matching run in run_summaries
                    for run_summary in run_summaries:
                        if run_summary.get("run_id") == run_id:
                            exp_data["Interactions"] = run_summary.get(
                                "avg_interaction_rounds", 0
                            )
                            break

        # 计算汇总统计 - 确保所有值都是数值类型
        def to_numeric(val):
            """Convert value to numeric, handling strings and None"""
            if val is None:
                return 0
            if isinstance(val, str):
                # Remove commas and extract numeric part from string
                import re

                clean_val = val.replace(",", "")
                match = re.search(r"[\d.]+", clean_val)
                if match:
                    return float(match.group())
                return 0
            return float(val)

        accuracies = [e["Accuracy"] for e in experiments]
        latencies = [to_numeric(e["Latency P50 (seconds)"]) for e in experiments]
        tokens = [to_numeric(e["Total Tokens"]) for e in experiments]
        tool_calls = [to_numeric(e["Tool Calls"]) for e in experiments]
        interactions = [to_numeric(e["Interactions"]) for e in experiments]

        summary = {
            "accuracy_mean": np.mean(accuracies) if accuracies else 0,
            "accuracy_std": np.std(accuracies) if accuracies else 0,
            "latency_p50": np.median(latencies) if latencies else 0,
            "latency_p99": (
                np.percentile(latencies, 99)
                if latencies and len(latencies) > 1
                else max(latencies) if latencies else 0
            ),
            "total_tokens_mean": np.mean(tokens) if tokens else 0,
            "tool_calls_mean": np.mean(tool_calls) if tool_calls else 0,
            "interactions_mean": np.mean(interactions) if interactions else 0,
        }

        return self._call_general_agent(experiments, summary)

    def _call_general_agent(self, experiments, summary):
        """调用general.dph进行深度分析"""
        try:
            # 准备分析数据
            data_summary = {
                "total_experiments": len(experiments),
                "summary_metrics": summary,
                "experiments": experiments,
            }

            # 构建dolphin命令
            cmd_parts = [
                str(self.dolphin_cmd),
                "--folder",
                str(self.root_dir / "experiments" / "analyst" / "dolphins"),
                "--agent",
                "general",
                "--data",
                json.dumps(data_summary, ensure_ascii=False),
                "--query",
                "请分析这个实验的结果，重点分析：1)不同模型的性能差异和原因；2)不同配置(variables)对结果的影响；3)延迟性能分析；4)Token消耗效率分析；5)调用链和工具使用模式分析；6)交互轮数与成功率的关系；7)Token消耗与准确率的性价比分析；8)给出实用的改进建议。请提供专业的分析和洞察。",
                "--output-variables",
                "analysis_result",
            ]

            # 运行命令
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=500,
                cwd=str(self.root_dir),
            )

            if result.returncode == 0:
                # 解析输出
                output = result.stdout

                # 方法1: 查找DOLPHIN_VARIABLES_OUTPUT标记
                start_marker = DOLPHIN_VARIABLES_OUTPUT_START
                end_marker = DOLPHIN_VARIABLES_OUTPUT_END

                if start_marker in output and end_marker in output:
                    start_idx = output.index(start_marker) + len(start_marker)
                    end_idx = output.index(end_marker)
                    json_str = output[start_idx:end_idx].strip()

                    try:
                        variables = json.loads(json_str)
                        if "analysis_result" in variables:
                            result_data = variables["analysis_result"]
                            if (
                                isinstance(result_data, dict)
                                and "answer" in result_data
                            ):
                                return result_data["answer"]
                            elif isinstance(result_data, str):
                                return result_data
                    except json.JSONDecodeError:
                        pass

                # 方法2: 查找"Agent general:"开始的地方
                output_lines = output.split("\n")
                start_idx = -1
                for i, line in enumerate(output_lines):
                    if "Agent general:" in line:
                        start_idx = i + 1
                        break

                if start_idx > 0:
                    analysis_lines = output_lines[start_idx:]
                    if analysis_lines:
                        return "\n".join(analysis_lines)

                return "深度分析完成，但无法提取分析结果。"
            else:
                print(f"Warning: General agent failed: {result.stderr}")
                return "深度分析调用失败。"
        except Exception as e:
            print(f"Warning: Failed to call general agent: {e}")
            return "深度分析执行异常。"

    def _write_report(
        self,
        report_name,
        config_df,
        accuracy_df,
        latency_df,
        token_df,
        factor_groups,
        impact_df,
        run_labels,
        results_df,
        consecutive_patterns,
        call_chain_summary,
        deep_analysis,
        log_analyses,
        individual_variables,
    ):
        """写入报告文件"""
        report_path = self.reports_dir / f"{report_name}.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"实验总体分析报告\n")
            f.write(f"{'='*60}\n")
            f.write(f"实验名称: {self.experiment_name}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"实验路径: {self.experiment_path}\n\n")

            # 1. 实验配置对比
            f.write("1. 实验配置对比\n")
            f.write("-" * 30 + "\n")
            f.write(config_df.to_string(index=False))
            f.write("\n\n")

            # 1.0 Run标识符说明
            f.write("1.0 Run标识符说明\n")
            f.write("-" * 30 + "\n")
            f.write("Run ID后的[xxxx]标识符含义：\n")

            # 使用数据加载器的图例信息
            if (
                hasattr(self.data_loader, "run_label_legend")
                and self.data_loader.run_label_legend
            ):
                for code, meaning in sorted(self.data_loader.run_label_legend.items()):
                    f.write(f"  {code} = {meaning}\n")
            else:
                # 如果没有图例信息，从实际数据中推断
                unique_codes = set()
                for run_id, label in run_labels.items():
                    if "[" in label and "]" in label:
                        identifier = label.split("[")[1].split("]")[0]
                        for char in identifier:
                            if char.isupper():
                                unique_codes.add(char)

                # 根据配置信息推断标识符含义
                config_df = self.data_loader.analyze_configs()
                if "Model Name" in config_df.columns:
                    model_names = config_df["Model Name"].unique()
                    for code in sorted(unique_codes):
                        # 根据实际使用的模型来映射标识符
                        found_meaning = False
                        for model in model_names:
                            if "deepseek" in model.lower() and code == "D":
                                f.write(f"  D = DeepSeek模型\n")
                                found_meaning = True
                                break
                            elif "qwen" in model.lower() and code == "Q":
                                f.write(f"  Q = Qwen模型\n")
                                found_meaning = True
                                break
                            elif "gpt" in model.lower() and code == "G":
                                f.write(f"  G = GPT模型\n")
                                found_meaning = True
                                break
                            elif "kimi" in model.lower() and (
                                code == "K" or code == "A" or code == "B"
                            ):
                                f.write(f"  {code} = Kimi模型\n")
                                found_meaning = True
                                break

                        if not found_meaning:
                            f.write(f"  {code} = 未知配置项\n")
            f.write("\n")

            # 1.1 配置因子对准确率的影响分析
            f.write("1.1 配置因子对准确率的影响分析\n")
            f.write(impact_df.to_string(index=False))
            f.write("\n")

            # 2. 准确率对比
            f.write("2. 准确率对比\n")
            f.write("-" * 30 + "\n")
            accuracy_df_labeled = accuracy_df.copy()
            accuracy_df_labeled["Run ID"] = accuracy_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(accuracy_df_labeled.to_string(index=False))
            f.write("\n\n")

            # 3. 按配置因子分组的准确率对比
            f.write("3. 按配置因子分组的准确率对比\n")
            f.write("-" * 30 + "\n")

            # 输出factor_groups的内容
            for factor_name, groups in factor_groups.items():
                f.write(f"\n按 {factor_name} 分组:\n\n")
                for group_value, group_info in groups.items():
                    f.write(f"  {group_value}:\n")
                    for run_info in group_info:
                        run_id = run_info["run_id"]
                        accuracy = run_info["accuracy"]
                        total = run_info["total"]
                        correct = run_info["correct"]
                        avg_latency = run_info.get("avg_latency", 0)
                        tokens_per_case = run_info.get("tokens_per_case", 0)

                        run_label = run_labels.get(run_id, run_id)
                        f.write(f"    {run_label}: {accuracy:.2%} ({correct}/{total})")
                        if avg_latency > 0:
                            f.write(f" 延迟{avg_latency:.1f}s")
                        if tokens_per_case > 0:
                            f.write(f" tokens{int(tokens_per_case)}/case")
                        f.write("\n")

                    if len(group_info) > 1:
                        accuracies = [r["accuracy"] for r in group_info]
                        latencies = [r["avg_latency"] for r in group_info]
                        tokens_per_case = [
                            r.get("avg_tokens_per_case", 0) for r in group_info
                        ]
                        llm_calls = [r.get("avg_llm_calls", 0) for r in group_info]

                        avg_acc = sum(accuracies) / len(accuracies)
                        avg_lat = sum(latencies) / len(latencies)
                        avg_tok = sum(tokens_per_case) / len(tokens_per_case)
                        avg_llm = sum(llm_calls) / len(llm_calls)

                        # 计算标准差和方差
                        import numpy as np

                        std_acc = np.std(accuracies) if len(accuracies) > 1 else 0
                        var_acc = np.var(accuracies) if len(accuracies) > 1 else 0
                        std_lat = np.std(latencies) if len(latencies) > 1 else 0
                        var_lat = np.var(latencies) if len(latencies) > 1 else 0
                        std_tok = (
                            np.std(tokens_per_case) if len(tokens_per_case) > 1 else 0
                        )
                        var_tok = (
                            np.var(tokens_per_case) if len(tokens_per_case) > 1 else 0
                        )

                        f.write(
                            f"    平均准确率: {avg_acc:.2%} (±{std_acc:.2%}, 方差:{var_acc:.6f})\n"
                        )
                        f.write(
                            f"    平均延迟: {avg_lat:.1f}s (±{std_lat:.1f}s, 方差:{var_lat:.2f})\n"
                        )
                        f.write(
                            f"    平均tokens/case: {int(avg_tok)} (±{int(std_tok)}, 方差:{int(var_tok)})\n"
                        )
                        f.write(f"    平均LLM调用/case: {avg_llm:.1f}\n")
                    f.write("\n")
                f.write("\n")

            # 按单个变量分组分析
            if individual_variables:
                f.write("按单个变量分组分析:\n")
                for var_name, var_groups in individual_variables.items():
                    f.write(f"\n按 {var_name} 分组:\n\n")
                    for value, stats in var_groups.items():
                        f.write(f"  {var_name}={value}:\n")
                        for run_info in stats:
                            run_id = run_info["run_id"]
                            accuracy = run_info["accuracy"]
                            total = run_info["total"]
                            correct = run_info["correct"]
                            avg_latency = run_info.get("avg_latency", 0)
                            tokens_per_case = run_info.get("tokens_per_case", 0)

                            run_label = run_labels.get(run_id, run_id)
                            f.write(
                                f"    {run_label}: {accuracy:.2%} ({correct}/{total})"
                            )
                            if avg_latency > 0:
                                f.write(f" 延迟{avg_latency:.1f}s")
                            if tokens_per_case > 0:
                                f.write(f" tokens{int(tokens_per_case)}/case")
                            f.write("\n")

                        # 输出统计信息
                        if len(stats) > 1:
                            accuracies = [r["accuracy"] for r in stats]
                            latencies = [r["avg_latency"] for r in stats]
                            tokens_per_case = [
                                r.get("avg_tokens_per_case", 0) for r in stats
                            ]
                            llm_calls = [r.get("avg_llm_calls", 0) for r in stats]

                            avg_acc = sum(accuracies) / len(accuracies)
                            avg_lat = sum(latencies) / len(latencies)
                            avg_tok = sum(tokens_per_case) / len(tokens_per_case)
                            avg_llm = sum(llm_calls) / len(llm_calls)

                            # 计算标准差和方差
                            import numpy as np

                            std_acc = np.std(accuracies) if len(accuracies) > 1 else 0
                            var_acc = np.var(accuracies) if len(accuracies) > 1 else 0
                            std_lat = np.std(latencies) if len(latencies) > 1 else 0
                            var_lat = np.var(latencies) if len(latencies) > 1 else 0
                            std_tok = (
                                np.std(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )
                            var_tok = (
                                np.var(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )

                            f.write(
                                f"    平均准确率: {avg_acc:.2%} (±{std_acc:.2%}, 方差:{var_acc:.6f})\n"
                            )
                            f.write(
                                f"    平均延迟: {avg_lat:.1f}s (±{std_lat:.1f}s, 方差:{var_lat:.2f})\n"
                            )
                            f.write(
                                f"    平均tokens/case: {int(avg_tok)} (±{int(std_tok)}, 方差:{int(var_tok)})\n"
                            )
                            f.write(f"    平均LLM调用/case: {avg_llm:.1f}\n")
                    f.write("\n")
            f.write("\n")

            # 4. 连续错误模式分析
            if consecutive_patterns:
                f.write("4. 连续错误模式分析\n")
                f.write("-" * 30 + "\n")

                for run_id, patterns in consecutive_patterns.items():
                    run_label = run_labels.get(run_id, run_id)
                    if patterns:
                        f.write(f"\n{run_label} 发现连续错误模式:\n")
                        for pattern in patterns:
                            start = min(pattern)
                            end = max(pattern)
                            length = len(pattern)
                            f.write(
                                f"             题目 {start}-{end} ({length}个连续错误)\n"
                            )
                f.write("\n")

            # 5. 延迟性能分析
            f.write("5. 延迟性能分析\n")
            f.write("-" * 30 + "\n")
            latency_df_labeled = latency_df.copy()
            latency_df_labeled["Run ID"] = latency_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(latency_df_labeled.to_string(index=False))
            f.write("\n\n")

            # 6. Token消耗分析
            f.write("6. Token消耗分析\n")
            f.write("-" * 30 + "\n")
            token_df_labeled = token_df.copy()
            token_df_labeled["Run ID"] = token_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(token_df_labeled.to_string(index=False))
            f.write("\n\n")

            # 配置因子影响分析已移动到1.1节

            # 7. 调用链和工具使用分析
            if call_chain_summary:
                f.write("7. 调用链和工具使用分析\n")
                f.write("-" * 30 + "\n")
                global_summary = call_chain_summary.get("global_summary", {})
                f.write(f"总体统计:\n")
                f.write(f"  - 总运行数: {global_summary.get('total_runs', 0)}\n")
                f.write(f"  - 总案例数: {global_summary.get('total_cases', 0)}\n")
                f.write(
                    f"  - 平均交互轮数: {global_summary.get('avg_interaction_rounds_global', 0):.1f}\n"
                )

                # 输出每个run的详细调用链统计
                run_summaries = call_chain_summary.get("run_summaries", [])
                if run_summaries:
                    f.write("\n各Run调用链统计:\n")
                    for run_summary in run_summaries:
                        run_id = run_summary.get("run_id", "")
                        run_label = run_labels.get(run_id, run_id)
                        f.write(f"\n  {run_label}:\n")
                        f.write(
                            f"    - 总案例数: {run_summary.get('total_cases', 0)}\n"
                        )
                        f.write(
                            f"    - 平均交互轮数: {run_summary.get('avg_interaction_rounds', 0):.1f}\n"
                        )
                        f.write(
                            f"    - 最大交互轮数: {run_summary.get('max_interaction_rounds', 0)}\n"
                        )
                        f.write(
                            f"    - 最小交互轮数: {run_summary.get('min_interaction_rounds', 0)}\n"
                        )

                        # 工具使用统计
                        tool_stats = run_summary.get("tool_usage_stats", {})
                        if tool_stats:
                            f.write(f"    - 工具使用统计:\n")
                            for tool_name, count in tool_stats.items():
                                f.write(f"      * {tool_name}: {count}次\n")
                f.write("\n")

            # 8. 日志错误分析
            if log_analyses:
                f.write("8. 日志错误分析\n")
                f.write("-" * 30 + "\n")

                for run_id, analysis_result in log_analyses.items():
                    run_label = run_labels.get(run_id, run_id)
                    errors = analysis_result.get("errors", {})
                    warnings = analysis_result.get("warnings", {})

                    if errors or warnings:
                        f.write(f"\n{run_label} 日志分析:\n")

                        if errors:
                            f.write(
                                f"  错误 (共{sum(len(v) for v in errors.values())}个):\n"
                            )
                            for error_type, error_list in errors.items():
                                if error_list:
                                    f.write(
                                        f"    - {error_type}: {len(error_list)}个\n"
                                    )
                                    # 显示前3个错误示例
                                    for i, error in enumerate(error_list[:3]):
                                        case_id = error.get("case", "unknown")
                                        msg = error.get("message", "")[:100]
                                        f.write(f"      * Case {case_id}: {msg}...\n")

                        if warnings:
                            f.write(
                                f"  警告 (共{sum(len(v) for v in warnings.values())}个):\n"
                            )
                            for warning_type, warning_list in warnings.items():
                                if warning_list:
                                    f.write(
                                        f"    - {warning_type}: {len(warning_list)}个\n"
                                    )
                f.write("\n")

            # 9. 方差分析汇总
            f.write("9. 方差分析汇总\n")
            f.write("-" * 30 + "\n")

            # 计算各指标的方差
            if len(accuracy_df) > 1:
                accuracies = [
                    float(acc.rstrip("%")) / 100 for acc in accuracy_df["Accuracy"]
                ]
                f.write(
                    f"准确率方差: {np.var(accuracies):.6f} (标准差: {np.std(accuracies):.4f})\n"
                )

                if "Avg Latency" in latency_df.columns:
                    latencies = [
                        float(lat.replace("s", "")) for lat in latency_df["Avg Latency"]
                    ]
                    f.write(
                        f"延迟方差: {np.var(latencies):.2f} (标准差: {np.std(latencies):.2f}s)\n"
                    )

                if "Total All Tokens" in token_df.columns:
                    tokens = [
                        int(tok.replace(",", ""))
                        for tok in token_df["Total All Tokens"]
                    ]
                    f.write(
                        f"Token消耗方差: {np.var(tokens):.0f} (标准差: {np.std(tokens):.0f})\n"
                    )
            else:
                f.write("样本数不足，无法计算方差\n")
            f.write("\n")

            # 10. LLM深度分析
            f.write("10. LLM深度分析\n")
            f.write("-" * 30 + "\n")
            if deep_analysis:
                f.write(deep_analysis)
            else:
                f.write("⚠️ 深度分析不可用")
            f.write("\n\n")

        return report_path
