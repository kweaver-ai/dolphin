#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验分析协调器

负责协调不同的分析模块：
- GeneralReporter: 总体报告生成
- ExecutionAnalyzer: 智能体执行分析
- ExperimentAnalyzer: 数据加载和处理（重用现有逻辑）
"""

import argparse
import os
import sys
import json
import shlex
import time
import yaml
from pathlib import Path
from datetime import datetime

# 导入分析模块
from experiment_analyzer import ExperimentAnalyzer
from general_reporter import GeneralReporter
from execution_analyzer import ExecutionAnalyzer
from summary_analyzer import SummaryAnalyzer
from simulation_inject import SimulationInjector


class ExperimentCoordinator:
    """实验分析协调器"""

    def __init__(self, experiment_path):
        """
        初始化协调器

        Args:
            experiment_path: 实验目录路径
        """
        self.experiment_path = Path(experiment_path)

        # 创建数据加载器（重用现有的ExperimentAnalyzer作为数据加载器）
        self.data_loader = ExperimentAnalyzer(experiment_path)

        # 创建功能模块
        self.general_reporter = GeneralReporter(self.data_loader)
        self.execution_analyzer = ExecutionAnalyzer(self.data_loader)
        self.summary_analyzer = SummaryAnalyzer(self.data_loader)
        # 记录本次模拟所使用的benchmark目录（用于加载自定义转换/比较逻辑）
        self._benchmark_dir = None

    def run_general_analysis(self):
        """运行总体分析并生成报告"""
        print("🔍 启动总体分析模式...")

        # 加载实验数据
        if not self.data_loader.load_experiment_data():
            print("错误: 无法加载实验数据")
            return False

        # 生成总体报告
        try:
            report_path, csv_path = self.general_reporter.generate_report()
            return True
        except Exception as e:
            print(f"错误: 生成总体报告时出现异常: {e}")
            import traceback

            traceback.print_exc()
            return False

    def run_execution_analysis(self, run_name, case_num):
        """运行智能体执行分析"""
        print("🔍 启动智能体执行分析模式...")

        # 执行智能体分析
        analysis_result = self.execution_analyzer.analyze_execution(run_name, case_num)
        if analysis_result:
            print("\n" + "=" * 60)
            print("📋 智能体执行分析结果:")
            print("=" * 60)
            print("===ANALYSIS_START===")
            print(analysis_result)
            print("===ANALYSIS_END===")
            print("=" * 60)
            return True
        else:
            print("错误: 智能体执行分析失败")
            return False

    def run_summary_analysis(self, run_name, knowledge_path=None):
        """运行summary分析"""
        print("🔍 启动Summary分析模式...")
        if knowledge_path:
            print(f"📚 使用业务知识: {knowledge_path}")

        # 执行summary分析
        summary_result = self.summary_analyzer.analyze_summary(
            run_name, knowledge_path=knowledge_path
        )
        if summary_result:
            print("\n" + "=" * 60)
            print("📋 Summary分析结果:")
            print("=" * 60)
            print("===SUMMARY_START===")
            print(summary_result)
            print("===SUMMARY_END===")
            print("=" * 60)
            return True
        else:
            print("错误: Summary分析失败")
            return False

    def run_cross_run_analysis(
        self,
        max_accuracy,
        report_csv=None,
        knowledge_path=None,
        enable_summary=False,
        case=None,
    ):
        """
        运行跨run分析模式，筛选正确率低于阈值的cases进行分析

        Args:
            max_accuracy: 最高正确率阈值（百分比）
            report_csv: general report CSV文件路径（可选）
            knowledge_path: 业务知识文件或文件夹路径
            enable_summary: 是否在分析完成后生成汇总分析

        Returns:
            是否成功
        """
        import pandas as pd
        from pathlib import Path

        print(f"🔍 启动跨run分析模式 - 正确率阈值: {max_accuracy}%")
        if case:
            print(f"🎯 仅分析指定的 Case: {case}")
        if knowledge_path:
            print(f"📚 使用业务知识: {knowledge_path}")
        if enable_summary:
            print("📋 将在分析完成后生成跨run汇总报告")

        # 获取CSV文件路径
        if report_csv:
            csv_path = Path(report_csv)
        else:
            # 自动查找最新的general report CSV - 现在在实验目录的reports文件夹中
            reports_dir = self.experiment_path / "reports"
            if not reports_dir.exists():
                print(f"错误: 报告目录不存在: {reports_dir}")
                print(f"请先运行 --general 生成报告")
                return False

            csv_files = list(
                reports_dir.glob(f"{self.experiment_path.name}_general_report_*.csv")
            )
            if not csv_files:
                print(f"错误: 未找到general report CSV文件")
                print(f"搜索路径: {reports_dir}")
                print(f"请先运行 --general 生成报告")
                return False
            csv_path = max(csv_files, key=lambda f: f.stat().st_mtime)
            print(f"📊 使用最新的报告文件: {csv_path.name}")

        # 读取CSV文件
        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
        except Exception as e:
            print(f"错误: 无法读取CSV文件: {e}")
            return False

        # 检查是否有整体正确率列
        if "整体正确率" not in df.columns:
            print("警告: CSV文件中没有'整体正确率'列，将根据现有数据计算")
            # 计算整体正确率
            run_cols = [col for col in df.columns if col.startswith("run_")]
            if not run_cols:
                print("错误: 找不到run列")
                return False

            accuracies = []
            for _, row in df.iterrows():
                correct_count = sum(1 for col in run_cols if row[col] == "✓")
                total_count = sum(1 for col in run_cols if row[col] in ["✓", "✗"])
                if total_count > 0:
                    accuracy = correct_count / total_count * 100
                    accuracies.append(accuracy)
                else:
                    accuracies.append(None)
            df["整体正确率"] = [
                f"{acc:.1f}%" if acc is not None else "N/A" for acc in accuracies
            ]

        # 解析可选的单个 case 过滤（支持 1 / 001 / case_001）
        def _parse_case_to_index(case_str):
            try:
                s = case_str.strip().lower()
                for prefix in ["case_", "test_"]:
                    if s.startswith(prefix):
                        s = s[len(prefix) :]
                        break
                # 去掉前导零
                s = s.lstrip("0") or "0"
                return int(s)
            except Exception:
                # 兼容直接从日志尾部的 Final result 文本中解析
                try:
                    import re

                    m = re.search(
                        r"Final result: .*?'answer':\s*'([^']+)'", output, re.S
                    )
                    if m:
                        return m.group(1).strip()
                except Exception:
                    pass

                return None

        case_index: int | None = _parse_case_to_index(case) if case else None
        if case and case_index is None:
            print(f"错误: 无法解析 case 参数: {case}")
            return False

        # 先按 case 过滤（若有），再按正确率阈值过滤
        filtered_cases = []
        for _, row in df.iterrows():
            if case_index is not None:
                # 如果指定了具体的case，只处理该case（不管正确率）
                if int(row.get("题目编号", -1)) == case_index:
                    accuracy_str = row["整体正确率"]
                    accuracy = (
                        float(accuracy_str.rstrip("%")) if accuracy_str != "N/A" else 0
                    )
                    filtered_cases.append(
                        {
                            "case_num": str(row["题目编号"]).zfill(3),
                            "accuracy": accuracy,
                            "topic": row.get("题目类型", ""),
                            "query": row.get("题目内容", ""),
                        }
                    )
            else:
                # 没有指定case时，按正确率阈值过滤
                accuracy_str = row["整体正确率"]
                if accuracy_str != "N/A":
                    accuracy = float(accuracy_str.rstrip("%"))
                    if accuracy <= max_accuracy:
                        filtered_cases.append(
                            {
                                "case_num": str(row["题目编号"]).zfill(3),
                                "accuracy": accuracy,
                                "topic": row.get("题目类型", ""),
                                "query": row.get("题目内容", ""),
                            }
                        )

        if not filtered_cases:
            if case_index is not None:
                print(
                    f"❌ 未找到 Case {str(case_index).zfill(3)}，请检查case编号是否正确"
                )
            else:
                print(f"✅ 没有正确率低于{max_accuracy}%的cases")
            return True

        if case_index is not None:
            print(f"📊 准备分析 Case {filtered_cases[0]['case_num']}:")
            print(f"  - 正确率: {filtered_cases[0]['accuracy']:.1f}%")
            print(f"  - 题目: {filtered_cases[0]['query'][:100]}...")
        else:
            print(f"📊 找到 {len(filtered_cases)} 个正确率低于{max_accuracy}%的cases:")
            for case in filtered_cases[:10]:  # 显示前10个
                print(
                    f"  - Case {case['case_num']}: {case['accuracy']:.1f}% - {case['query'][:50]}..."
                )
            if len(filtered_cases) > 10:
                print(f"  ... 还有 {len(filtered_cases) - 10} 个cases")

        print("=" * 60)

        # 获取所有runs
        run_dirs = sorted(
            [
                d
                for d in self.experiment_path.iterdir()
                if d.is_dir() and d.name.startswith("run_")
            ]
        )
        if not run_dirs:
            print("错误: 未找到任何run目录")
            return False

        print(f"将对 {len(run_dirs)} 个runs中的 {len(filtered_cases)} 个cases进行分析")
        print("=" * 60)

        # 对每个case在所有run中进行分析
        total_analyses = len(filtered_cases) * len(run_dirs)
        analysis_count = 0
        success_count = 0

        for case_info in filtered_cases:
            case_num = case_info["case_num"]
            print(f"\n📋 分析 Case {case_num} (正确率: {case_info['accuracy']:.1f}%)")
            print(f"题目: {case_info['query'][:100]}...")
            print("-" * 40)

            for run_dir in run_dirs:
                run_name = run_dir.name
                analysis_count += 1
                print(
                    f"[{analysis_count}/{total_analyses}] {run_name} - Case {case_num}...",
                    end=" ",
                )

                # 检查是否已有分析结果
                existing_result = None
                # 无论是否提供业务知识，只要已有分析报告则跳过；
                # 如需强制重新分析，请删除对应的分析报告文件。
                existing_result = self.execution_analyzer.load_analysis_result(
                    run_name, case_num
                )

                if existing_result:
                    print("✓ (已缓存)")
                    success_count += 1
                    continue

                # 执行新的分析
                try:
                    analysis_result = self.execution_analyzer.analyze_execution(
                        run_name,
                        case_num,
                        save_to_file=True,
                        knowledge_path=knowledge_path,
                    )
                    if analysis_result:
                        print("✓")
                        success_count += 1
                    else:
                        print("✗")
                except Exception as e:
                    print(f"✗ (错误: {e})")

        # 总结
        print("\n" + "=" * 60)
        print("📊 跨run分析完成")
        print("=" * 60)
        print(f"总计: {total_analyses} 个分析任务")
        print(f"成功: {success_count} 个")
        print(f"失败: {total_analyses - success_count} 个")
        print(f"成功率: {success_count/total_analyses*100:.1f}%")

        # 如果启用了summary功能，进行跨run汇总分析
        if enable_summary and success_count > 0:
            print("\n" + "=" * 60)
            print("📋 开始跨run汇总分析...")
            print("=" * 60)

            summary_success = self._run_cross_run_summary(
                filtered_cases, run_dirs, knowledge_path
            )
            if summary_success:
                print("✅ 跨run汇总分析完成")
            else:
                print("❌ 跨run汇总分析失败")
                return False

        return True

    def run_batch_execution_analysis(
        self, run_name, failed_only=True, knowledge_path=None
    ):
        """
        批量运行智能体执行分析

        Args:
            run_name: run名称
            failed_only: 是否仅分析失败的cases（默认True）
            knowledge_path: 业务知识文件或文件夹路径

        Returns:
            是否成功
        """
        print(f"🔍 启动批量执行分析模式 - Run: {run_name}")
        if knowledge_path:
            print(f"📚 使用业务知识: {knowledge_path}")

        # 获取要分析的cases
        cases_to_analyze = self._get_cases_to_analyze(run_name, failed_only)

        if not cases_to_analyze:
            if failed_only:
                print("✅ 没有失败的cases需要分析")
            else:
                print("⚠️ 没有找到任何cases")
            return True

        print(
            f"📊 将分析 {len(cases_to_analyze)} 个cases: {', '.join(cases_to_analyze)}"
        )
        print("=" * 60)

        # 依次分析每个case
        results = []
        for i, case_num in enumerate(cases_to_analyze, 1):
            print(f"\n[{i}/{len(cases_to_analyze)}] 分析 Case {case_num}...")
            print("-" * 40)

            # 无论是否提供业务知识，只要已有分析报告则跳过；
            # 如需强制重新分析，请删除对应的分析报告文件。
            existing_result = self.execution_analyzer.load_analysis_result(
                run_name, case_num
            )

            if existing_result:
                print("✅ 找到已有的分析结果，跳过重新分析（删除分析报告可重新生成）")
                results.append((case_num, "CACHED", existing_result))
                continue

            # 执行新的分析
            analysis_result = self.execution_analyzer.analyze_execution(
                run_name, case_num, save_to_file=True, knowledge_path=knowledge_path
            )
            if analysis_result:
                print("\n📋 分析结果:")
                print("===ANALYSIS_START===")
                print(analysis_result)
                print("===ANALYSIS_END===")
                results.append((case_num, "SUCCESS", analysis_result))
            else:
                print("❌ 分析失败")
                results.append((case_num, "FAILED", None))

        # 总结
        print("\n" + "=" * 60)
        print("📊 批量分析完成")
        print("=" * 60)
        success_count = sum(1 for _, status, _ in results if status == "SUCCESS")
        cached_count = sum(1 for _, status, _ in results if status == "CACHED")
        failed_count = sum(1 for _, status, _ in results if status == "FAILED")
        print(f"总计: {len(results)} 个cases")
        print(f"新分析: {success_count} 个")
        print(f"已缓存: {cached_count} 个")
        print(f"失败: {failed_count} 个")

        return success_count > 0

    def _get_cases_to_analyze(self, run_name, failed_only=True):
        """
        获取要分析的cases列表

        Args:
            run_name: run名称
            failed_only: 是否仅获取失败的cases

        Returns:
            case编号列表
        """
        # 加载实验数据
        if not self.data_loader.load_experiment_data():
            print("错误: 无法加载实验数据")
            return []

        # 尝试不同的run目录命名格式
        run_dir = None
        possible_names = [
            run_name,  # 原始名称
            run_name.replace("run", "run_"),  # run001 -> run_001
            f"run_{run_name.replace('run', '').zfill(3)}",  # run1 -> run_001
            f"run_{run_name.replace('run_', '').zfill(3)}",  # run_1 -> run_001
        ]

        for name in possible_names:
            test_dir = self.experiment_path / name
            if test_dir.exists():
                run_dir = test_dir
                break

        if not run_dir:
            print(f"错误: 找不到run目录: {run_name}")
            print(f"已尝试: {', '.join(possible_names)}")
            return []

        # 尝试不同的结果文件名
        result_file = None
        possible_files = [
            run_dir / "result.yaml",
            run_dir / "run_summary.yaml",
            run_dir / "results.yaml",
        ]

        for file in possible_files:
            if file.exists():
                result_file = file
                break

        if not result_file:
            print(f"错误: 在 {run_dir} 中找不到结果文件")
            print(f"已尝试: result.yaml, run_summary.yaml, results.yaml")
            return []

        try:
            import yaml

            with open(result_file, "r", encoding="utf-8") as f:
                results = yaml.safe_load(f)

            cases_to_analyze = []

            # 根据文件类型处理数据
            if result_file.name == "run_summary.yaml":
                # run_summary.yaml 格式 - cases 可能在 benchmarks 字段下
                cases_data = results.get("benchmarks", results.get("cases", []))
            else:
                # result.yaml 格式
                cases_data = results if isinstance(results, list) else []

            # 遍历所有cases
            for idx, case_result in enumerate(cases_data):
                # 获取case编号
                case_id = (
                    case_result.get("test_id")
                    or case_result.get("case_id")
                    or case_result.get("id")
                )
                if case_id is None:
                    # 如果没有明确的ID，使用索引+1作为case编号
                    case_id = idx + 1
                case_num = str(case_id).lstrip("test_").lstrip("case_").zfill(3)

                # 判断是否正确
                is_correct = case_result.get("is_correct", False) or case_result.get(
                    "correct", False
                )

                # 根据条件决定是否添加到分析列表
                if failed_only:
                    if not is_correct:
                        cases_to_analyze.append(case_num)
                else:
                    cases_to_analyze.append(case_num)

            return sorted(cases_to_analyze)

        except Exception as e:
            print(f"错误: 读取结果文件失败: {e}")
            return []

    def _run_cross_run_summary(self, filtered_cases, run_dirs, knowledge_path=None):
        """
        执行跨run的汇总分析

        Args:
            filtered_cases: 筛选出的case列表
            run_dirs: run目录列表
            knowledge_path: 业务知识文件或文件夹路径

        Returns:
            是否成功
        """
        try:
            # 收集所有分析内容
            all_analysis_content = []

            print("🔍 收集分析内容...")
            for case_info in filtered_cases:
                case_num = case_info["case_num"]
                print(f"📋 收集 Case {case_num} 的分析内容...")

                case_analysis_content = []
                for run_dir in run_dirs:
                    run_name = run_dir.name
                    analysis_file = run_dir / "analysis" / f"case_{case_num}.txt"

                    if analysis_file.exists():
                        try:
                            with open(analysis_file, "r", encoding="utf-8") as f:
                                file_content = f.read()

                            # 提取分析内容
                            extracted_content = (
                                self._extract_analysis_content_from_file(
                                    file_content, f"{run_name}_case_{case_num}.txt"
                                )
                            )
                            if extracted_content:
                                case_analysis_content.append(extracted_content)

                        except Exception as e:
                            print(f"  ⚠️ 读取 {run_name}/case_{case_num}.txt 失败: {e}")
                            continue

                if case_analysis_content:
                    # 合并该case的所有run分析
                    case_combined = f"\n\n=== Case {case_num} 跨Run分析汇总 ===\n"
                    case_combined += f"题目: {case_info['query'][:100]}...\n"
                    case_combined += f"正确率: {case_info['accuracy']:.1f}%\n"
                    case_combined += "=" * 50 + "\n\n"
                    case_combined += "\n\n".join(case_analysis_content)

                    all_analysis_content.append(case_combined)
                    print(f"  ✅ 收集到 {len(case_analysis_content)} 个run的分析内容")
                else:
                    print(f"  ⚠️ Case {case_num} 没有找到有效的分析内容")

            if not all_analysis_content:
                print("❌ 没有收集到任何分析内容")
                return False

            print(f"✅ 总共收集到 {len(all_analysis_content)} 个case的分析内容")

            # 合并所有分析内容
            combined_content = "\n\n" + "=" * 80 + "\n\n".join(all_analysis_content)

            # 调用summary分析
            print("🔧 开始汇总分析...")
            summary_result = self._call_summary_analysis(
                combined_content, knowledge_path
            )

            if summary_result:
                # 保存汇总结果到实验目录下的analysis文件夹
                analysis_dir = self.experiment_path / "analysis"
                analysis_dir.mkdir(exist_ok=True, parents=True)

                from datetime import datetime

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # 生成case列表字符串，限制长度避免文件名过长
                case_nums = [str(case_info["case_num"]) for case_info in filtered_cases]
                case_str = "_".join(case_nums[:10])  # 最多取前10个case，避免文件名过长
                if len(filtered_cases) > 10:
                    case_str += f"_and_{len(filtered_cases)-10}_more"
                summary_file = (
                    analysis_dir / f"cross_run_summary_cases_{case_str}_{timestamp}.txt"
                )

                with open(summary_file, "w", encoding="utf-8") as f:
                    f.write("=" * 80 + "\n")
                    f.write("跨Run汇总分析报告\n")
                    f.write(
                        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write(f"分析的Cases: {len(filtered_cases)} 个\n")
                    f.write(f"涉及的Runs: {len(run_dirs)} 个\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(summary_result)
                    f.write("\n\n")

                print(f"✅ 汇总报告已保存: {summary_file}")
                return True
            else:
                print("❌ 汇总分析失败")
                return False

        except Exception as e:
            print(f"错误: 跨run汇总分析失败: {e}")
            return False

    def _extract_analysis_content_from_file(self, file_content, file_name):
        """
        从分析文件中提取内容

        Args:
            file_content: 文件内容
            file_name: 文件名（用于标识）

        Returns:
            提取的分析内容
        """
        try:
            start_marker = "===ANALYSIS_START==="
            end_marker = "===ANALYSIS_END==="

            start_pos = file_content.find(start_marker)
            if start_pos == -1:
                return None

            end_pos = file_content.find(end_marker, start_pos)
            if end_pos == -1:
                return None

            # 提取标记之间的内容
            content_start = start_pos + len(start_marker)
            extracted_content = file_content[content_start:end_pos].strip()

            if not extracted_content:
                return None

            # 添加文件标识
            formatted_content = f"--- 来自: {file_name} ---\n{extracted_content}"
            return formatted_content

        except Exception as e:
            print(f"错误: 从 {file_name} 提取分析内容时出错: {e}")
            return None

    def _call_summary_analysis(self, analysis_content, knowledge_path=None):
        """
        调用summary分析功能

        Args:
            analysis_content: 分析内容
            knowledge_path: 业务知识路径

        Returns:
            汇总分析结果
        """
        try:
            # 创建临时文件夹用于分析
            import tempfile
            import subprocess
            from datetime import datetime

            # 创建临时的 summary_analyzer 来加载知识和提取结果
            from summary_analyzer import SummaryAnalyzer

            temp_summary_analyzer = SummaryAnalyzer(self.data_loader)

            # 加载业务知识
            knowledge_content = ""
            if knowledge_path:
                knowledge_content = temp_summary_analyzer._load_knowledge(
                    knowledge_path
                )
                if knowledge_content:
                    print(f"✅ 成功加载业务知识 ({len(knowledge_content)} 字符)")

            # 构建dolphin命令
            cmd_parts = [
                str(self.data_loader.dolphin_cmd),
                "--folder",
                str(Path(__file__).parent / "dolphins"),
                "--agent",
                "summary",
                "--analysis_content",
                analysis_content,
                "--busi_knowledge",
                knowledge_content,
                "--output-variables",
                "suggestions",
            ]

            # 执行分析命令
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=500,
                cwd=str(self.data_loader.root_dir),
            )

            if result.returncode == 0:
                # 提取分析结果
                extracted = temp_summary_analyzer._extract_summary_result(result.stdout)
                if extracted:
                    return extracted
                else:
                    print("警告: 无法从输出中提取汇总结果")
                    return "汇总分析完成，但无法提取分析结果。"
            else:
                print(f"错误: 汇总分析失败，退出码: {result.returncode}")
                if result.stderr:
                    print(f"错误信息: {result.stderr}")
                return None

        except Exception as e:
            print(f"错误: 调用汇总分析时出错: {e}")
            return None

    def run_simulation_inject(
        self,
        case_id,
        entrypoint=None,
        inject_var="injects",
        knowledge_path=None,
        max_iterations=5,
        timeout_seconds=500,
    ):
        """入口：委托 SimulationInjector 执行具体逻辑"""
        injector = SimulationInjector(
            experiment_path=self.experiment_path,
            data_loader=self.data_loader,
            cross_run_analysis_callback=self.run_cross_run_analysis,
        )
        return injector.run_simulation_inject(
            case_id=case_id,
            entrypoint=entrypoint,
            inject_var=inject_var,
            knowledge_path=knowledge_path,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
        )

    def run_batch_simulation_inject(
        self,
        accuracy_threshold=10.0,
        entrypoint=None,
        inject_var="injects",
        knowledge_path=None,
        max_iterations=5,
        timeout_seconds=500,
    ):
        """入口：委托 SimulationInjector 执行具体逻辑（批量）"""
        injector = SimulationInjector(
            experiment_path=self.experiment_path,
            data_loader=self.data_loader,
            cross_run_analysis_callback=self.run_cross_run_analysis,
        )
        return injector.run_batch_simulation_inject(
            accuracy_threshold=accuracy_threshold,
            entrypoint=entrypoint,
            inject_var=inject_var,
            knowledge_path=knowledge_path,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
        )

    # 注：simulation-inject 相关实现已迁移至 SimulationInjector
