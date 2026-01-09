#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
SimulationInjector: 将 simulation-inject 的具体实现从 ExperimentCoordinator 中解耦，
以独立类的方式提供单个case与批量case的智能注入优化能力（纯语义驱动）。
"""

from typing import Optional, Callable
from pathlib import Path
from datetime import datetime
import time
import json
import shlex
import re

from dolphin.core.common.constants import (
    DOLPHIN_VARIABLES_OUTPUT_START,
    DOLPHIN_VARIABLES_OUTPUT_END,
)

try:
    from .injects_optimizer import InjectsOptimizer
    from .semantic_judge import SemanticJudge
    from .semantic_gradient import SemanticGradient, aggregate_gradients
    from .base_analyzer import BaseAnalyzer
except ImportError:
    from injects_optimizer import InjectsOptimizer
    from semantic_judge import SemanticJudge
    from semantic_gradient import SemanticGradient, aggregate_gradients
    from base_analyzer import BaseAnalyzer


class SimulationInjector(BaseAnalyzer):
    def __init__(
        self,
        experiment_path: Path,
        data_loader,
        cross_run_analysis_callback: Optional[Callable[..., bool]] = None,
    ):
        # 调用父类初始化
        super().__init__(data_loader)

        # SimulationInjector特有属性
        self._benchmark_dir: Optional[Path] = None
        # 可选：用于在缺失跨run汇总分析时触发生成
        self._cross_run_analysis_cb = cross_run_analysis_callback

    # ===== Public API =====
    def run_simulation_inject(
        self,
        case_id,
        entrypoint: Optional[str] = None,
        inject_var: str = "injects",
        knowledge_path: Optional[str] = None,
        max_iterations: int = 5,
        timeout_seconds: int = 500,
        top_n: int = 5,
    ) -> bool:
        """
        单样本作为批次语义优化的退化情形：以一个 case 运行批次优化。
        """
        return self._semantic_batch_optimize(
            case_ids=[str(case_id).lstrip("case_").lstrip("test_").zfill(3)],
            entrypoint=entrypoint,
            inject_var=inject_var,
            knowledge_path=knowledge_path,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            top_n=top_n,
        )

    def run_batch_simulation_inject(
        self,
        accuracy_threshold: float = 10.0,
        entrypoint: Optional[str] = None,
        inject_var: str = "injects",
        knowledge_path: Optional[str] = None,
        max_iterations: int = 5,
        timeout_seconds: int = 500,
        top_n: int = 5,
    ) -> bool:
        """批次语义优化：按阈值筛选case后，做跨case的聚合优化。"""
        import pandas as pd

        print(f"🚀 启动批次语义优化 (multi-case semantic batch)")
        print(f"📊 准确率阈值: {accuracy_threshold}% | 最大迭代: {max_iterations}")
        reports_dir = self.experiment_path / "reports"
        if not reports_dir.exists():
            print(f"错误: 报告目录不存在: {reports_dir}")
            print("请先运行 --general 生成报告")
            return False
        csv_files = list(
            reports_dir.glob(f"{self.experiment_path.name}_general_report_*.csv")
        )
        if not csv_files:
            print("错误: 未找到general report CSV文件")
            print("请先运行 --general 生成报告")
            return False
        csv_path = max(csv_files, key=lambda f: f.stat().st_mtime)
        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
        except Exception as e:
            print(f"错误: 无法读取CSV文件: {e}")
            return False

        case_ids: list[str] = []
        for _, row in df.iterrows():
            if "整体正确率" in df.columns:
                accuracy_str = row["整体正确率"]
                if accuracy_str != "N/A":
                    accuracy = float(accuracy_str.rstrip("%"))
                else:
                    run_cols = [col for col in df.columns if col.startswith("run_")]
                    correct_count = sum(1 for col in run_cols if row[col] == "✓")
                    total_count = sum(1 for col in run_cols if row[col] in ["✓", "✗"])
                    accuracy = (
                        (correct_count / total_count * 100) if total_count > 0 else 0
                    )
            else:
                run_cols = [col for col in df.columns if col.startswith("run_")]
                correct_count = sum(1 for col in run_cols if row[col] == "✓")
                total_count = sum(1 for col in run_cols if row[col] in ["✓", "✗"])
                accuracy = (correct_count / total_count * 100) if total_count > 0 else 0
            if accuracy <= accuracy_threshold:
                case_ids.append(str(row.get("case", "")).zfill(3))

        if not case_ids:
            print(f"✅ 没有正确率低于 {accuracy_threshold}% 的cases")
            return True

        return self._semantic_batch_optimize(
            case_ids=case_ids,
            entrypoint=entrypoint,
            inject_var=inject_var,
            knowledge_path=knowledge_path,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            top_n=top_n,
        )

    def _prepare_enhanced_evaluate_context(
        self, benchmark_item: dict, case_result: dict, analysis_content: str
    ) -> dict:
        """准备增强的评估上下文，包含完整的 benchmark 信息"""
        evaluate_context = {
            # 1. 保留所有 benchmark item 原始字段
            "benchmark_item": benchmark_item,
            # 2. 预测结果信息
            "predicted_result": case_result["last_result"],
            "predicted_execution_process": case_result.get("execution_log", ""),
            # 3. 跨运行分析上下文
            "analysis_content": analysis_content,
            # 4. 元数据信息
            "evaluation_timestamp": datetime.now().isoformat(),
            # 5. 结构化的期望结果信息
            "expected_info": {
                "raw_expected": benchmark_item.get(
                    "choice_answer",
                    benchmark_item.get("answer", benchmark_item.get("Answer", "")),
                ),
            },
            # 6. 优化相关信息（新增）
            "optimization_context": {
                "current_inject": case_result.get("current_inject", ""),
                "iteration": case_result.get("iteration", 0),
                "inject_history": case_result.get("inject_history", []),
            },
        }

        return evaluate_context

    # ===== Helpers =====
    def _find_case_specific_summary_file(self, analysis_dir, case_id):
        """查找包含指定case_id的汇总分析文件"""
        summary_files = list(analysis_dir.glob("cross_run_summary_cases_*.txt"))
        case_specific_files = []

        for file in summary_files:
            filename = file.name
            try:
                # 提取cases部分: cross_run_summary_cases_{case_str}_{timestamp}.txt
                case_part = filename.split("_cases_")[1].split("_")[0]
                # 处理包含 "and_X_more" 的情况
                if "and" in case_part:
                    case_part = case_part.split("and")[0].rstrip("_")

                case_list = case_part.split("_")
                if case_id in case_list:
                    case_specific_files.append(file)
            except Exception:
                # 解析失败，跳过该文件
                continue

        if case_specific_files:
            # 选择最新的包含当前case_id的文件
            latest_summary = max(case_specific_files, key=lambda f: f.stat().st_mtime)
            return latest_summary

        return None

    def _get_or_generate_analysis(self, case_id, knowledge_path: Optional[str]) -> str:
        analysis_content = ""
        analysis_dir = self.experiment_path / "analysis"

        if analysis_dir.exists():
            latest_summary = self._find_case_specific_summary_file(
                analysis_dir, case_id
            )
            if latest_summary:
                print(f"✅ 找到包含当前case的跨run汇总分析报告: {latest_summary.name}")
                try:
                    analysis_content = latest_summary.read_text(encoding="utf-8")
                    print(f"✅ 成功加载汇总分析报告 ({len(analysis_content)} 字符)")
                    return analysis_content
                except Exception as e:
                    print(f"⚠️ 读取汇总分析报告失败: {e}")

        # 若无汇总、尝试通过回调生成
        print("⚠️ 未找到跨run汇总分析报告，执行新的跨run分析...")
        if self._cross_run_analysis_cb:
            ok = self._cross_run_analysis_cb(
                max_accuracy=100,
                knowledge_path=knowledge_path,
                enable_summary=True,
                case=case_id,
            )
            if not ok:
                print("错误: 跨run分析失败")
                return ""
            # 重试加载
            if analysis_dir.exists():
                latest_summary = self._find_case_specific_summary_file(
                    analysis_dir, case_id
                )
                if latest_summary:
                    print(f"✅ 找到新生成的汇总分析报告: {latest_summary.name}")
                    try:
                        analysis_content = latest_summary.read_text(encoding="utf-8")
                        print(f"✅ 成功加载汇总分析报告 ({len(analysis_content)} 字符)")
                        return analysis_content
                    except Exception as e:
                        print(f"⚠️ 读取汇总分析报告失败: {e}")

        return analysis_content

    def _execute_without_inject(
        self, original_cmd, case_num, timeout_seconds=500
    ) -> Optional[str]:
        import subprocess

        cmd = original_cmd.copy()

        # 强制包含 answer 输出变量
        try:
            if "--output-variables" in cmd:
                ov_idx = cmd.index("--output-variables")
                if ov_idx + 1 < len(cmd):
                    ov_val = cmd[ov_idx + 1]
                    raw = ov_val.replace("\n", " ").split()
                    names = [n for n in raw if n]
                    if "answer" not in names:
                        names.append("answer")
                    del cmd[ov_idx : ov_idx + 2]
                    cmd.insert(ov_idx, "--output-variables")
                    for i, n in enumerate(names, start=1):
                        cmd.insert(ov_idx + i, n)
            else:
                cmd.extend(["--output-variables", "answer"])
        except Exception:
            pass

        log_dir = self.experiment_path / "simulation_logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"case_{case_num}_baseline.log"

        timed_out = False
        result = None
        start_ts = time.time()
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.root_dir),
                    timeout=(
                        timeout_seconds
                        if (timeout_seconds and timeout_seconds > 0)
                        else None
                    ),
                )
        except subprocess.TimeoutExpired as e:
            timed_out = True
            print(f"⚠️ Baseline执行超时: {e}")
        except Exception as e:
            print(f"  ⚠️ Baseline执行异常: {e}")
            return None
        finally:
            elapsed = time.time() - start_ts
            print(f"⏱️ Baseline执行耗时: {elapsed:.2f} 秒")
            if not timed_out and result is not None:
                print(f"⏎ 子进程退出码: {result.returncode}")

        # 尝试从日志中提取结构化答案
        answer = self._extract_answer_from_log(log_file)
        if answer is not None:
            if timed_out:
                print("⚠️ 虽然命令超时，但已在日志中检测到完整答案，将其视为成功。")
            return answer

        # 如果提取失败，报告错误
        if timed_out:
            print("⚠️ 命令超时且未在日志中找到可用答案")
        elif result is not None and result.returncode != 0:
            print(
                f"  ⚠️ Baseline命令执行失败，返回码: {result.returncode}，且未能从日志中提取答案"
            )
        else:
            print("  ⚠️ Baseline命令执行完成，但未能从日志中提取答案")

        return None

    def _semantic_batch_optimize(
        self,
        case_ids: list[str],
        entrypoint: Optional[str],
        inject_var: str,
        knowledge_path: Optional[str],
        max_iterations: int,
        timeout_seconds: int,
        top_n: int = 5,
    ) -> bool:
        # 参数与环境检查
        print(
            f"📦 批次样本: {len(case_ids)} -> {', '.join(case_ids[:10])}{' ...' if len(case_ids)>10 else ''}"
        )
        if not inject_var or not inject_var.strip():
            print("错误: inject_var 参数不能为空")
            return False
        if entrypoint and not self._validate_entrypoint_exists(entrypoint):
            print(f"错误: 指定的 entrypoint '{entrypoint}' 不存在")
            return False
        if entrypoint and not self._validate_inject_var_in_agent(
            entrypoint, inject_var
        ):
            print(f"错误: 变量 '${inject_var}' 在 agent '{entrypoint}' 中不存在")
            return False

        # 确保simulation_logs目录存在
        simulation_logs_dir = self.experiment_path / "simulation_logs"
        simulation_logs_dir.mkdir(exist_ok=True)

        judge = SemanticJudge(self.data_loader, simulation_logs_dir)
        knowledge_base = self._load_knowledge_for_inject(knowledge_path) or ""
        full_analysis_content = self._get_or_generate_analysis(
            case_ids[0], knowledge_path
        )
        if not full_analysis_content:
            print("错误: 无法获取分析内容")
            return False

        # 准备每个样本的基础信息（不执行baseline）
        cases = []
        for cid in case_ids:
            original_cmd = self._get_case_execution_command(cid)
            if not original_cmd:
                print(f"⚠️ 跳过 Case {cid}: 无法获取执行命令")
                continue
            bench = self._get_benchmark_data(cid)
            if not bench:
                print(f"⚠️ 跳过 Case {cid}: 无法获取benchmark数据")
                continue
            expected = bench.get(
                "choice_answer", bench.get("answer", bench.get("Answer", ""))
            )
            cases.append(
                {
                    "case_num": cid,
                    "original_cmd": original_cmd,
                    "benchmark_item": bench,  # 保存完整benchmark信息
                    "expected": expected,
                    "last_result": None,  # 将在第-1轮（baseline轮）执行
                    "last_score": 0.0,
                    "done": False,
                }
            )

        if not cases:
            print("错误: 无可优化的case")
            return False

        # 统一迭代：第-1轮为baseline，第0轮开始为注入优化
        inject_history: list[str] = []
        plateau = 0
        patience = 5
        batch_loss = 0.0

        # Phase 1: Baseline execution and initial gradient calculation
        print("\n🔄 Baseline")
        current_gradients = []
        for c in cases:
            print(f"🎯 执行案例 {c['case_num']} baseline...")
            result = self._execute_without_inject(
                c["original_cmd"], c["case_num"], timeout_seconds
            )
            if not result:
                print(f"⚠️ 跳过 Case {c['case_num']}: Baseline 执行失败或无有效输出")
                continue
            c["last_result"] = result
            c["done"] = self._compare_result_with_benchmark(result, c["expected"])

            # Evaluate baseline to get initial gradients using enhanced context
            print(f"🔧 为案例 {c['case_num']} 评估语义梯度（增强版）...")
            print(f"   使用完整跨run分析上下文 ({len(full_analysis_content)} 字符)")

            # 准备增强评估上下文
            case_result_info = {"last_result": result}
            evaluate_context = self._prepare_enhanced_evaluate_context(
                c["benchmark_item"], case_result_info, full_analysis_content
            )

            grad_raw = judge.evaluate_enhanced(evaluate_context, knowledge_base)
            if grad_raw is None:
                print(
                    f"错误: SemanticJudge 增强评估失败（case {c['case_num']}），中止优化。"
                )
                return False
            try:
                grad = SemanticGradient.from_judge_result(grad_raw)
                c["last_score"] = grad.score
                current_gradients.append(grad)
            except ValueError as e:
                print(f"错误: SemanticGradient解析失败（case {c['case_num']}）: {e}")
                return False

            # analysis_content just used for baseline, so we set it to empty
            evaluate_context["analysis_content"] = ""

        # Calculate initial loss
        valid_cases = [c for c in cases if c["last_result"] is not None]
        if not valid_cases:
            print("错误: 无有效的案例结果")
            return False

        batch_loss = sum(1.0 - c["last_score"] for c in valid_cases) / len(valid_cases)
        print(f"📉 初始语义损失: {batch_loss:.4f}")
        print(f"✅ Baseline完成: {len(valid_cases)} 个案例，初始损失 {batch_loss:.4f}")

        # Phase 2: Training loop - standard ML training paradigm
        for it in range(max_iterations):
            print(f"\n🔄 注入优化 {it + 1}/{max_iterations}")

            # Step 1: Parameter update - generate injection based on current gradients
            agg_inject = aggregate_gradients(
                current_gradients, top_n=top_n, history=inject_history
            )
            if not agg_inject:
                print("错误: 无法从梯度聚合出有效注入（无候选/无动作），中止优化。")
                return False

            # 检查是否与历史重复（双重保险）
            if agg_inject in inject_history:
                print(f"⚠️ 聚合结果与历史重复，尝试增加多样性...")
                # 尝试使用更多候选
                agg_inject_alt = aggregate_gradients(
                    current_gradients, top_n=min(top_n * 2, 5), history=inject_history
                )
                if (
                    agg_inject_alt
                    and agg_inject_alt != agg_inject
                    and agg_inject_alt not in inject_history
                ):
                    agg_inject = agg_inject_alt
                    print(f"✅ 采用替代聚合策略")
                else:
                    print(f"⚠️ 无法避免重复，继续使用当前结果（可能导致早停）")

            inject_history.append(agg_inject)
            print(
                f"🧮 聚合注入 (top{top_n}, 历史感知): {agg_inject[:160]}..."
                if len(agg_inject) > 160
                else f"🧮 聚合注入 (top{top_n}, 历史感知): {agg_inject}"
            )

            # Step 2: Forward pass - execute with injection
            # Step 3: Loss calculation & Backward pass - evaluate results and calculate new gradients
            new_gradients = []
            for c in valid_cases:
                # 关键修复：每次迭代都重新计算所有样本的梯度
                # 即使case已完成，也需要基于当前注入内容重新评估梯度

                # 智能执行策略：平衡性能与准确性
                skip_execution = False

                # 性能优化：对于已完成且得分很高的cases，可以考虑跳过执行
                if c["done"] and c.get("last_score", 0) > 0.9 and it > 1:
                    # 高置信度的完成案例，降低执行频率
                    skip_execution = it % 2 == 0  # 偶数轮跳过执行
                    if skip_execution:
                        print(
                            f"🚀 案例 {c['case_num']} 高置信度完成，跳过执行以优化性能"
                        )

                if c["done"] and not skip_execution:
                    # 已完成但需要重新执行以获得当前参数下的结果
                    print(f"🔧 案例 {c['case_num']} 已完成，重新执行以更新梯度...")
                    res = self._execute_with_inject(
                        original_cmd=c["original_cmd"],
                        inject_content=agg_inject,
                        inject_var=inject_var,
                        entrypoint=entrypoint,
                        case_num=c["case_num"],
                        iteration=it,
                        timeout_seconds=timeout_seconds,
                    )
                    if res is not None:
                        c["last_result"] = res
                    else:
                        res = c["last_result"]
                        print(f"⚠️ 重新执行失败，使用历史结果")
                elif c["done"] and skip_execution:
                    # 使用上次的执行结果，但重新计算梯度
                    res = c["last_result"]
                else:
                    # 未完成的cases，必须执行
                    res = self._execute_with_inject(
                        original_cmd=c["original_cmd"],
                        inject_content=agg_inject,
                        inject_var=inject_var,
                        entrypoint=entrypoint,
                        case_num=c["case_num"],
                        iteration=it,
                        timeout_seconds=timeout_seconds,
                    )
                    if res is None:
                        # 执行失败时使用上次结果重新评估梯度
                        res = c["last_result"]
                        print(
                            f"⚠️ 案例 {c['case_num']} 执行失败，使用上次结果重新评估梯度"
                        )
                    else:
                        # 更新执行结果
                        c["last_result"] = res

                # 重要：无论case状态如何，都要重新计算梯度
                print(f"🔧 为案例 {c['case_num']} 重新计算梯度（基于当前注入参数）...")
                current_analysis = "" if it > 0 else full_analysis_content
                if it == 0:
                    print(f"   使用完整跨run分析上下文 ({len(current_analysis)} 字符)")
                else:
                    print(f"   使用简化上下文，专注当前执行结果评估")

                # 准备增强评估上下文，包含当前注入内容信息
                case_result_info = {
                    "last_result": res,
                    "current_inject": agg_inject,  # 添加当前注入信息
                    "iteration": it,
                    "inject_history": (
                        inject_history[:-1] if inject_history else []
                    ),  # 历史（不包含当前）
                }
                evaluate_context = self._prepare_enhanced_evaluate_context(
                    c["benchmark_item"], case_result_info, current_analysis
                )

                cg_raw = judge.evaluate_enhanced(evaluate_context, knowledge_base)
                if cg_raw is None:
                    print(
                        f"错误: SemanticJudge 增强评估失败（case {c['case_num']}），中止优化。"
                    )
                    return False

                try:
                    cg = SemanticGradient.from_judge_result(cg_raw)
                    c["last_score"] = cg.score
                    new_gradients.append(cg)
                except ValueError as e:
                    print(
                        f"错误: SemanticGradient解析失败（case {c['case_num']}）: {e}"
                    )
                    return False

                # 检查是否新完成
                if not c["done"] and self._compare_result_with_benchmark(
                    res, c["expected"]
                ):
                    c["done"] = True
                    self._save_successful_inject(c["case_num"], agg_inject, it)
                    print(f"✅ 案例 {c['case_num']} 在第 {it+1} 次迭代中成功完成")

            # Update gradients for next iteration
            current_gradients = new_gradients

            # Step 4: Calculate loss and check convergence
            new_loss = sum(1.0 - c["last_score"] for c in valid_cases) / len(
                valid_cases
            )
            print(f"📉 批次语义损失: {new_loss:.4f} (prev: {batch_loss:.4f})")

            # Convergence check
            if new_loss < batch_loss - 1e-3:
                batch_loss = new_loss
                plateau = 0
            else:
                plateau += 1

            # Early stopping conditions
            if all(c["done"] for c in valid_cases):
                print("✅ 全部case已正确，提前结束")
                break
            if plateau >= patience:
                print("⚠️ 多轮无显著改进，提前结束")
                break

        success = sum(1 for c in cases if c["done"])
        total_cases = len([c for c in cases if c["last_result"] is not None])
        print(
            f"\n📊 批次优化完成: {success}/{total_cases} 成功，最终批次损失 {batch_loss:.4f}"
        )
        self._save_batch_semantic_summary(cases, inject_history)
        return success > 0

    def _save_batch_semantic_summary(
        self, cases: list[dict], inject_history: list[str]
    ):
        try:
            analysis_dir = self.experiment_path / "analysis"
            analysis_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fp = analysis_dir / f"batch_semantic_summary_{ts}.json"
            payload = {
                "timestamp": ts,
                "total_cases": len(cases),
                "success_cases": [c["case_num"] for c in cases if c["done"]],
                "failed_cases": [c["case_num"] for c in cases if not c["done"]],
                "final_scores": {c["case_num"]: c["last_score"] for c in cases},
                "inject_history": inject_history,
            }
            fp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"📄 批次语义总结已保存: {fp}")
        except Exception as e:
            print(f"⚠️ 保存批次语义总结失败: {e}")

    def _extract_answer_from_log(self, log_file: Path) -> Optional[str]:
        def _pick_string(val):
            if isinstance(val, dict):
                for k in ("answer", "result", "value", "block_answer"):
                    v = val.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip() if "failed to call LLM" not in v else ""
                return ""
            if isinstance(val, str) and val.strip():
                return val.strip() if "failed to call LLM" not in val else ""
            return ""

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                output = f.read()
        except FileNotFoundError:
            return None

        start_marker = DOLPHIN_VARIABLES_OUTPUT_START
        end_marker = DOLPHIN_VARIABLES_OUTPUT_END

        s = output.find(start_marker)
        e = output.find(end_marker)
        if s != -1 and e != -1:
            json_content = output[s + len(start_marker) : e].strip()
            try:
                variables = json.loads(json_content)
            except json.JSONDecodeError:
                return None
            ans = _pick_string(variables.get("answer"))
            if ans:
                return ans
            fr = _pick_string(variables.get("final_result"))
            if fr:
                return fr
            stages = variables.get("_all_stages")
            if isinstance(stages, list) and stages:
                last = stages[-1]
                val = _pick_string(last)
                if val:
                    return val
            return ""
        return None

    def _execute_with_inject(
        self,
        original_cmd,
        inject_content,
        inject_var,
        entrypoint,
        case_num,
        iteration,
        timeout_seconds=500,
    ) -> Optional[str]:
        import subprocess

        cmd = original_cmd.copy()
        cmd.extend([f"--{inject_var}", inject_content])

        # 关键修复：必须使用支持injects变量的agent
        target_agent = entrypoint if entrypoint else "my_agent"

        # 验证目标agent是否支持injects变量
        if not self._validate_inject_var_in_agent(target_agent, inject_var):
            print(
                f"⚠️ Agent '{target_agent}' 不支持 {inject_var} 变量，尝试使用 my_agent"
            )
            target_agent = "my_agent"
            if not self._validate_inject_var_in_agent(target_agent, inject_var):
                print(f"❌ 无法找到支持 {inject_var} 变量的agent")
                return None

        # 替换agent参数
        for i, arg in enumerate(cmd):
            if arg == "--agent":
                if i + 1 < len(cmd):
                    old_agent = cmd[i + 1]
                    cmd[i + 1] = target_agent
                    print(f"🔄 替换agent: {old_agent} -> {target_agent}")
                break
        else:
            print("⚠️ 在inject命令中未找到 --agent 参数")

        # 强制包含 answer 输出变量
        try:
            if "--output-variables" in cmd:
                ov_idx = cmd.index("--output-variables")
                if ov_idx + 1 < len(cmd):
                    ov_val = cmd[ov_idx + 1]
                    raw = ov_val.replace("\n", " ").split()
                    names = [n for n in raw if n]
                    if "answer" not in names:
                        names.append("answer")
                    del cmd[ov_idx : ov_idx + 2]
                    cmd.insert(ov_idx, "--output-variables")
                    for i, n in enumerate(names, start=1):
                        cmd.insert(ov_idx + i, n)
            else:
                cmd.extend(["--output-variables", "answer"])
        except Exception:
            pass

        log_dir = self.experiment_path / "simulation_logs"
        log_dir.mkdir(exist_ok=True)
        log_file = (
            log_dir / f"case_{case_num}_iter_{iteration}.log"
        )  # iter is 0-based, so +1 removed

        if entrypoint:
            print("📌 entrypoint命令:")
            print(f"  {shlex.join(cmd)}")

        timed_out = False
        result = None
        start_ts = time.time()
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.root_dir),
                    timeout=(
                        timeout_seconds
                        if (timeout_seconds and timeout_seconds > 0)
                        else None
                    ),
                )
        except subprocess.TimeoutExpired as e:
            timed_out = True
            print(f"⚠️ 执行注入命令超时: {e}")
        except Exception as e:
            print(f"执行注入命令失败: {e}")
            return None
        finally:
            elapsed = time.time() - start_ts
            print(f"⏱️ entrypoint执行耗时: {elapsed:.2f} 秒")
            if not timed_out and result is not None:
                print(f"⏎ 子进程退出码: {result.returncode}")

        if not timed_out and result is not None and result.returncode != 0:
            print(f"执行注入命令失败，退出码: {result.returncode}")

        answer = self._extract_answer_from_log(log_file)
        if answer is not None:
            if timed_out:
                print("⚠️ 虽然命令超时，但已在日志中检测到完整答案，将其视为成功。")
            return answer
        if timed_out:
            print("⚠️ 命令超时且未在日志中找到可用答案")
            return None
        if result is not None and result.returncode == 0:
            print("⚠️ 注入命令执行完成，但未能从日志中提取答案")
            return None
        return None

    def _compare_result_with_benchmark(self, result, expected) -> bool:
        try:
            import re
            import importlib.util

            raw_result = str(result).strip()
            raw_expected = str(expected).strip()
            result_l = raw_result.lower()
            expected_l = raw_expected.lower()

            def _is_choice_label(s: str) -> bool:
                return bool(re.fullmatch(r"[a-z](?:,[a-z])+|[a-z]", s))

            if _is_choice_label(expected_l):
                converted = None
                try:
                    if self._benchmark_dir:
                        init_path = Path(self._benchmark_dir) / "init.py"
                        if init_path.exists():
                            spec = importlib.util.spec_from_file_location(
                                "benchmark_init_module", str(init_path)
                            )
                            if spec and spec.loader:
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                if hasattr(mod, "_convert_predicted") and callable(
                                    getattr(mod, "_convert_predicted")
                                ):
                                    converted = getattr(mod, "_convert_predicted")(
                                        raw_result
                                    )
                                    if isinstance(converted, str):
                                        converted = converted.strip().lower()
                except Exception:
                    converted = None

                if not converted:
                    m = re.search(r"```\s*([a-z](?:,[a-z])*)\s*```", raw_result.lower())
                    if m:
                        converted = m.group(1)
                    else:
                        m2 = re.search(r"([a-z](?:,[a-z])*)\s*$", raw_result.lower())
                        if m2:
                            converted = m2.group(1)

                if converted:
                    return converted == expected_l

            if result_l == expected_l:
                return True

            result_clean = re.sub(r"[^\w\s]", "", result_l)
            expected_clean = re.sub(r"[^\w\s]", "", expected_l)
            if result_clean == expected_clean:
                return True

            if len(expected_clean) > 5 and expected_clean in result_clean:
                return True

            return False
        except Exception as e:
            print(f"比较结果失败: {e}")
            return False

    def _save_successful_inject(self, case_num, inject_content, iteration):
        try:
            analysis_dir = self.experiment_path / "analysis"
            analysis_dir.mkdir(exist_ok=True)
            success_file = analysis_dir / f"successful_inject_case_{case_num}.txt"
            with open(success_file, "w", encoding="utf-8") as f:
                f.write("成功的注入内容\n")
                f.write(f"Case: {case_num}\n")
                f.write(f"成功迭代: 第{iteration}次\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                f.write("注入内容:\n")
                f.write(inject_content)
                f.write("\n\n" + "=" * 60 + "\n")
        except Exception as e:
            print(f"保存成功注入内容失败: {e}")

    def _save_optimization_summary(
        self,
        case_num,
        optimizer: InjectsOptimizer,
        iterations: int,
        success: bool,
        baseline_loss: Optional[float] = None,
        baseline_result: Optional[str] = None,
    ):
        try:
            analysis_dir = self.experiment_path / "analysis"
            analysis_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_file = (
                analysis_dir / f"optimization_summary_case_{case_num}_{timestamp}.json"
            )

            summary = optimizer.get_optimization_summary()
            summary.update(
                {
                    "case_id": case_num,
                    "success": success,
                    "total_iterations": iterations,
                    "timestamp": timestamp,
                    "baseline_loss": baseline_loss,
                    "baseline_result": (
                        baseline_result[:500] if baseline_result else None
                    ),
                    "final_improvement": (
                        (
                            (baseline_loss - summary.get("best_loss", baseline_loss))
                            / baseline_loss
                            * 100
                        )
                        if baseline_loss and baseline_loss > 0
                        else 0
                    ),
                    "optimizer_config": {
                        "learning_rate": getattr(
                            optimizer, "initial_learning_rate", None
                        ),
                        "momentum": getattr(optimizer, "momentum", None),
                        "patience": getattr(optimizer, "patience", None),
                    },
                }
            )

            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

            print(f"📊 优化总结已保存: {summary_file.name}")
        except Exception as e:
            print(f"⚠️ 保存优化总结失败: {e}")

    def _load_knowledge_for_inject(self, knowledge_path: Optional[str]) -> str:
        """使用基类的知识加载方法"""
        return self._load_knowledge(knowledge_path)

    def _get_case_execution_command(self, case_num) -> Optional[list]:
        try:
            import json as _json
            import shlex

            # 查找最新的run目录
            run_dirs = sorted(
                [
                    d
                    for d in self.experiment_path.iterdir()
                    if d.is_dir() and d.name.startswith("run_")
                ]
            )
            if not run_dirs:
                return None

            run_dir = run_dirs[0]

            # 优先查找 cmds/case_XXX.sh 文件
            case_formatted = str(case_num).zfill(3)  # 确保是3位数格式
            cmd_sh_file = run_dir / "cmds" / f"case_{case_formatted}.sh"

            if cmd_sh_file.exists():
                # 读取shell脚本并解析dolphin命令
                with open(cmd_sh_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # 查找dolphin命令行（包含多行字符串）
                lines = content.split("\n")
                cmd_parts = []
                in_dolphin_cmd = False
                in_multiline_string = False
                string_delimiter = None

                for line in lines:
                    stripped = line.strip()

                    # 检查是否开始dolphin命令
                    if stripped.endswith("/bin/dolphin \\"):
                        in_dolphin_cmd = True
                        cmd_parts.append(stripped.rstrip(" \\"))
                        continue

                    # 如果在dolphin命令中
                    if in_dolphin_cmd:
                        # 检查是否开始多行字符串
                        if not in_multiline_string and (
                            stripped.startswith("'") or stripped.startswith('"')
                        ):
                            if stripped.startswith("'"):
                                string_delimiter = "'"
                                in_multiline_string = True
                                # 检查是否在同一行结束
                                if stripped.endswith("' \\") or (
                                    stripped.endswith("'")
                                    and not stripped.endswith("' \\")
                                ):
                                    in_multiline_string = False
                            elif stripped.startswith('"'):
                                string_delimiter = '"'
                                in_multiline_string = True
                                if stripped.endswith('" \\') or (
                                    stripped.endswith('"')
                                    and not stripped.endswith('" \\')
                                ):
                                    in_multiline_string = False

                        # 如果在多行字符串中
                        elif in_multiline_string:
                            if stripped.endswith(
                                string_delimiter + " \\"
                            ) or stripped.endswith(string_delimiter):
                                in_multiline_string = False
                                string_delimiter = None

                        # 添加当前行到命令部分
                        if stripped.endswith(" \\"):
                            cmd_parts.append(stripped.rstrip(" \\"))
                        else:
                            cmd_parts.append(stripped)
                            # 如果不是多行字符串，结束命令收集
                            if not in_multiline_string:
                                break

                if cmd_parts:
                    # 使用专门的bash脚本解析逻辑
                    try:
                        parsed_cmd = self._parse_bash_command_with_multiline_strings(
                            cmd_parts
                        )
                        if parsed_cmd and len(parsed_cmd) > 10:
                            print(f"🔍 bash解析出的命令参数数量: {len(parsed_cmd)}")
                            print(f"🔍 前5个参数: {parsed_cmd[:5]}")

                            # 验证关键参数
                            for i, arg in enumerate(parsed_cmd):
                                if arg == "--agent" and i + 1 < len(parsed_cmd):
                                    print(
                                        f"🔍 找到 --agent 参数在位置 {i}，值为: {parsed_cmd[i+1]}"
                                    )
                                    break

                            # 检查choice_question
                            for i, arg in enumerate(parsed_cmd):
                                if arg == "--choice_question" and i + 1 < len(
                                    parsed_cmd
                                ):
                                    choice_q_value = parsed_cmd[i + 1]
                                    print(
                                        f"🔍 找到 --choice_question 参数，内容长度: {len(choice_q_value)} 字符"
                                    )
                                    if "选项：" in choice_q_value:
                                        print("✅ choice_question包含完整选项")
                                    else:
                                        print("⚠️ choice_question缺少选项部分")
                                    break

                            return parsed_cmd
                        else:
                            print("⚠️ bash解析失败，回退到传统方法")
                    except Exception as e:
                        print(f"⚠️ bash解析失败: {e}，回退到传统方法")

                    # 回退：尝试shlex解析
                    try:
                        full_cmd = " ".join(cmd_parts)
                        parsed_cmd = shlex.split(full_cmd, posix=True)

                        print(f"🔍 使用shlex解析出的命令参数数量: {len(parsed_cmd)}")
                        if len(parsed_cmd) > 10:
                            return parsed_cmd
                        else:
                            print("⚠️ shlex解析结果参数过少，回退到手动解析")

                    except Exception as e:
                        print(f"⚠️ shlex解析失败: {e}，回退到手动解析")

                    # 方法2: 回退到改进的手动解析（保持多行结构）
                    parsed_cmd = []

                    # 首先确保包含dolphin可执行文件路径
                    dolphin_path = None
                    for part in cmd_parts:
                        if "/bin/dolphin" in part:
                            dolphin_path = part.strip()
                            break

                    if dolphin_path:
                        parsed_cmd.append(dolphin_path)

                    # 然后解析参数
                    i = 0
                    while i < len(cmd_parts):
                        part = cmd_parts[i].strip()
                        if not part:
                            i += 1
                            continue

                        # 跳过已经处理的dolphin路径
                        if "/bin/dolphin" in part:
                            i += 1
                            continue

                        # 检查是否是参数开始
                        if part.startswith("--"):
                            parsed_cmd.append(part)
                            i += 1
                            # 收集参数值
                            if i < len(cmd_parts):
                                value_part = cmd_parts[i].strip()

                                # 特殊处理带引号的多行值
                                if value_part.startswith("'"):
                                    # 多行字符串值，需要收集直到匹配的引号
                                    value_lines = [value_part]
                                    if (
                                        not value_part.endswith("'")
                                        or value_part.count("'") == 1
                                    ):
                                        # 需要收集更多行
                                        i += 1
                                        while i < len(cmd_parts):
                                            next_line = cmd_parts[i].strip()
                                            value_lines.append(next_line)
                                            if next_line.endswith("'"):
                                                break
                                            i += 1

                                    # 重建完整值并移除外层引号
                                    full_value = "\n".join(value_lines)
                                    if full_value.startswith(
                                        "'"
                                    ) and full_value.endswith("'"):
                                        full_value = full_value[1:-1]
                                    parsed_cmd.append(full_value)
                                else:
                                    parsed_cmd.append(value_part)
                                i += 1
                        else:
                            # 可能是延续的参数值
                            if parsed_cmd and not part.startswith("--"):
                                parsed_cmd.append(part)
                            i += 1

                    if parsed_cmd:
                        print(f"🔍 手动解析出的命令参数数量: {len(parsed_cmd)}")
                        print(f"🔍 前5个参数: {parsed_cmd[:5]}")

                        # 验证关键参数
                        for i, arg in enumerate(parsed_cmd):
                            if arg == "--agent" and i + 1 < len(parsed_cmd):
                                print(
                                    f"🔍 找到 --agent 参数在位置 {i}，值为: {parsed_cmd[i+1]}"
                                )
                                break

                        # 检查choice_question
                        for i, arg in enumerate(parsed_cmd):
                            if arg == "--choice_question" and i + 1 < len(parsed_cmd):
                                choice_q_value = parsed_cmd[i + 1]
                                print(
                                    f"🔍 找到 --choice_question 参数，内容长度: {len(choice_q_value)} 字符"
                                )
                                if "选项：" in choice_q_value or "\n" in choice_q_value:
                                    print("✅ choice_question包含完整内容")
                                else:
                                    print("⚠️ choice_question可能不完整")
                                break

                        return parsed_cmd
                    else:
                        # 如果解析失败，回退到使用shell脚本
                        print(
                            f"⚠️ 无法解析shell脚本中的命令，使用原始脚本: {cmd_sh_file}"
                        )
                        return ["bash", str(cmd_sh_file)]

            # 兜底：查找 cmd.json 文件
            cmd_file = run_dir / "cmd.json"
            if cmd_file.exists():
                with open(cmd_file, "r", encoding="utf-8") as f:
                    cmd_data = _json.load(f)

                # 查找指定case的命令
                case_key_variants = [f"test_{case_num}", f"case_{case_num}", case_num]
                for key in case_key_variants:
                    cmd = cmd_data.get(key)
                    if cmd:
                        return cmd

                # 兜底：返回全局命令
                return cmd_data.get("default")

            return None
        except Exception as e:
            print(f"获取执行命令失败: {e}")
            return None

    def _validate_entrypoint_exists(self, entrypoint: str) -> bool:
        try:
            run_dirs = sorted(
                [
                    d
                    for d in self.experiment_path.iterdir()
                    if d.is_dir() and d.name.startswith("run_")
                ]
            )
            if not run_dirs:
                return False
            run_dir = run_dirs[0]
            dolphins_dir = run_dir / "dolphins"
            if not dolphins_dir.exists():
                return False
            agent_file = dolphins_dir / f"{entrypoint}.dph"
            return agent_file.exists()
        except Exception as e:
            print(f"验证entrypoint失败: {e}")
            return False

    def _validate_inject_var_in_agent(self, entrypoint: str, inject_var: str) -> bool:
        try:
            run_dirs = sorted(
                [
                    d
                    for d in self.experiment_path.iterdir()
                    if d.is_dir() and d.name.startswith("run_")
                ]
            )
            if not run_dirs:
                return False
            run_dir = run_dirs[0]
            dolphins_dir = run_dir / "dolphins"
            agent_file = dolphins_dir / f"{entrypoint}.dph"
            if not agent_file.exists():
                return False
            with open(agent_file, "r", encoding="utf-8") as f:
                content = f.read()
            var_reference = f"${inject_var}"
            return var_reference in content
        except Exception as e:
            print(f"验证inject_var失败: {e}")
            return False

    def _parse_bash_command_with_multiline_strings(self, cmd_parts: list) -> list:
        """
        专门解析bash脚本中的多行字符串命令
        处理形如 --choice_question '多行\n内容' 的情况
        """
        # 将所有行重新组合，保持原始的换行和空格
        full_text = "\n".join(cmd_parts)

        # 手动分析参数结构
        result = []
        i = 0
        lines = cmd_parts

        # 首先找到dolphin可执行文件
        for line in lines:
            if "/bin/dolphin" in line:
                result.append(line.strip())
                break

        # 然后逐行解析参数
        current_param = None
        current_value = ""
        in_multiline_string = False
        string_delimiter = None

        for line in lines:
            line_stripped = line.strip()

            # 跳过dolphin可执行文件行
            if "/bin/dolphin" in line:
                continue

            # 检查是否是新参数
            if line_stripped.startswith("--") and not in_multiline_string:
                # 保存之前的参数值
                if current_param is not None:
                    if current_value.strip():
                        result.append(current_value.strip())
                    current_value = ""

                # 开始新参数
                current_param = line_stripped
                result.append(current_param)
                continue

            # 处理参数值
            if current_param is not None:
                # 检查是否开始多行字符串
                if not in_multiline_string and (
                    "'" in line_stripped or '"' in line_stripped
                ):
                    # 检测字符串开始
                    if line_stripped.startswith("'"):
                        in_multiline_string = True
                        string_delimiter = "'"
                        current_value = line_stripped[1:]  # 移除开头的引号

                        # 检查是否在同一行结束
                        if current_value.endswith("'") and len(current_value) > 0:
                            current_value = current_value[:-1]  # 移除结尾引号
                            in_multiline_string = False
                            string_delimiter = None
                    elif line_stripped.startswith('"'):
                        in_multiline_string = True
                        string_delimiter = '"'
                        current_value = line_stripped[1:]

                        if current_value.endswith('"') and len(current_value) > 0:
                            current_value = current_value[:-1]
                            in_multiline_string = False
                            string_delimiter = None
                    else:
                        current_value = line_stripped
                elif in_multiline_string:
                    # 继续多行字符串
                    if line_stripped.endswith(string_delimiter + " \\"):
                        # 字符串结束但有续行符，移除续行符和引号
                        current_value += "\n" + line_stripped[:-3]  # 移除 ' \
                        in_multiline_string = False
                        string_delimiter = None
                    elif line_stripped.endswith(string_delimiter):
                        # 字符串结束
                        current_value += "\n" + line_stripped[:-1]  # 移除结尾引号
                        in_multiline_string = False
                        string_delimiter = None
                    else:
                        # 继续多行
                        current_value += "\n" + line_stripped
                else:
                    # 普通参数值（可能有续行符）
                    if line_stripped.endswith(" \\"):
                        current_value = line_stripped[:-2].strip()  # 移除续行符
                    else:
                        current_value = line_stripped

        # 保存最后一个参数值
        if current_param is not None and current_value.strip():
            result.append(current_value.strip())

        return result
