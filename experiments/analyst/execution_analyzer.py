#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能体执行分析器

负责分析智能体的执行过程，包括：
- 预处理实验日志
- 获取benchmark数据
- 调用analysis.dph进行执行过程分析
- 对比智能体执行轨迹与预期结果
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
import time

from dolphin.core.common.constants import (
    DOLPHIN_VARIABLES_OUTPUT_START,
    DOLPHIN_VARIABLES_OUTPUT_END,
)

try:
    from .base_analyzer import BaseAnalyzer
except ImportError:
    from base_analyzer import BaseAnalyzer


class ExecutionAnalyzer(BaseAnalyzer):
    """智能体执行分析器"""

    def __init__(self, data_loader):
        """
        初始化执行分析器

        Args:
            data_loader: ExperimentDataLoader实例
        """
        # 调用父类初始化
        super().__init__(data_loader)

    def analyze_execution(
        self, run_name, case_num, save_to_file=True, knowledge_path=None
    ):
        """
        分析智能体在单个case上的执行过程

        Args:
            run_name: run名称
            case_num: case编号
            save_to_file: 是否保存到文件
            knowledge_path: 业务知识文件或文件夹路径

        Returns:
            执行分析结果
        """
        print(f"🔍 开始分析智能体执行过程 - Run: {run_name}, Case: {case_num}")
        if knowledge_path:
            print(f"📚 加载业务知识: {knowledge_path}")

        # 预处理实验日志并保存到临时文件
        processed_log_path = self._preprocess_execution_log(run_name, case_num)
        if not processed_log_path:
            return None
        print(f"✅ 成功预处理执行日志")

        # 获取benchmark数据
        benchmark = self._get_benchmark_data(case_num)
        if not benchmark:
            return None
        print(f"✅ 成功获取benchmark数据 (question_id: {benchmark['question_id']})")

        # 加载业务知识
        knowledge_content = ""
        if knowledge_path:
            print(f"🔍 正在加载业务知识: {knowledge_path}")
            knowledge_content = self._load_knowledge(knowledge_path, run_name)
            if knowledge_content:
                print(f"✅ 成功加载业务知识 ({len(knowledge_content)} 字符)")
            else:
                print("⚠️ 业务知识加载失败")

        # 执行智能体分析
        print(f"🔧 调用 analysis.dph，知识内容长度: {len(knowledge_content)}")
        analysis_result = self._run_execution_analysis(
            processed_log_path, benchmark, knowledge_content
        )
        if not analysis_result:
            return None

        print("✅ 智能体执行分析完成")

        # 保存分析结果到文件
        if save_to_file and analysis_result:
            self._save_analysis_result(run_name, case_num, analysis_result)

        # 清理临时文件
        try:
            processed_log_path.unlink()
        except:
            pass

        return analysis_result

    def _preprocess_execution_log(self, run_name, case_num):
        """预处理智能体执行日志，提取关键执行信息"""
        # 使用新的日志文件路径格式
        case_num_padded = f"{int(case_num):03d}"
        log_file = (
            self.root_dir
            / "experiments"
            / "env"
            / self.experiment_name
            / run_name
            / "console"
            / f"case_{case_num_padded}.log"
        )

        # 如果新路径不存在，尝试旧路径格式
        if not log_file.exists():
            run_num = run_name.split("_")[-1].lstrip("0") or "0"
            case_num_clean = case_num.lstrip("0") or "0"
            log_file = (
                self.root_dir
                / "experiments"
                / "env"
                / self.experiment_name
                / run_name
                / "log"
                / f"experiment_run_{run_num}_case_{case_num_clean}.log"
            )

        if not log_file.exists():
            print(f"错误: 执行日志文件不存在: {log_file}")
            return None

        try:
            # 读取完整执行日志
            with open(log_file, "r", encoding="utf-8") as f:
                full_content = f.read()

            # 截取到Final result:之前的主要执行轨迹
            content = full_content
            final_result_pos = content.find("Final result:")
            if final_result_pos != -1:
                content = content[:final_result_pos]

            content = content.strip()

            # 提取关键执行信息作为META数据
            meta_lines = []
            meta_lines.append("\n\n==== EXECUTION META (extracted) ====")

            # 1) 提取智能体最终答案
            try:
                ans_match = re.search(
                    r"Final result:\s*\{.*?'answer':\s*'(.*?)',\s*'think'",
                    full_content,
                    re.DOTALL,
                )
                if ans_match:
                    raw_answer = ans_match.group(1)
                    clean_answer = raw_answer.replace("\\n", "\n")
                    meta_lines.append("[agent_answer]\n" + clean_answer.strip())
            except Exception:
                pass

            # 2) 提取最终SQL查询（如果存在）
            try:
                # 去除ANSI颜色码
                ansi_escape = re.compile(r"\x1B(?:[@-Z\\\\-_]|\[[0-?]*[ -/]*[@-~])")
                no_ansi = ansi_escape.sub("", full_content)

                # 匹配最后一个SQL查询
                sql_matches = list(
                    re.finditer(r'"sql"\s*:\s*"(.*?)"', no_ansi, re.DOTALL)
                )
                if sql_matches:
                    last_sql = sql_matches[-1].group(1)
                    last_sql = last_sql.replace("\\n", "\n")
                    meta_lines.append("[executed_sql]\n" + last_sql.strip())
            except Exception:
                pass

            # 3) 提取工具调用链
            try:
                tool_calls = []
                tool_matches = re.finditer(r"🛠️\s*(\w+):", content)
                for match in tool_matches:
                    tool_calls.append(match.group(1))
                if tool_calls:
                    meta_lines.append("[tool_chain]\n" + " -> ".join(tool_calls))
            except Exception:
                pass

            # 4) 提取思考过程（如果存在）
            try:
                think_match = re.search(r"'think':\s*'(.*?)'", full_content, re.DOTALL)
                if think_match:
                    think_content = think_match.group(1).replace("\\n", "\n")
                    # 只保留前500字符避免过长
                    if len(think_content) > 500:
                        think_content = think_content[:500] + "..."
                    meta_lines.append("[agent_thinking]\n" + think_content.strip())
            except Exception:
                pass

            # 合并内容和META数据
            if meta_lines and len(meta_lines) > 1:
                content = content + "\n" + "\n".join(meta_lines)

            # 保存到临时文件
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, suffix=".log"
            ) as tmp_file:
                tmp_file.write(content)
                return Path(tmp_file.name)

        except Exception as e:
            print(f"错误: 预处理执行日志失败: {e}")
            return None

    # _get_benchmark_data method moved to BaseAnalyzer

    def _run_execution_analysis(
        self, execution_log_path, benchmark, knowledge_content=""
    ):
        """调用analysis.dph进行智能体执行分析"""
        analysis_log_file = None
        try:
            analysis_file = Path(__file__).parent / "dolphins" / "analysis.dph"
            if not analysis_file.exists():
                print(f"错误: analysis.dph文件不存在: {analysis_file}")
                return None

            # 构建dolphin命令
            cmd_parts = [
                str(self.dolphin_cmd),
                "--folder",
                Path(__file__).parent / "dolphins",
                "--agent",
                "analysis",
                "--exp_log_path",
                str(execution_log_path),
                "--benchmark",
                json.dumps(benchmark, ensure_ascii=False),
                "--busi_knowledge",
                knowledge_content,
                "--output-variables",
                "analysis_result",
            ]

            # 创建临时日志文件
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            analysis_log_file = self.reports_dir / f"execution_analysis_{ts}.log"

            print("🔧 执行智能体分析...")

            # 执行分析命令
            with open(analysis_log_file, "w", encoding="utf-8") as log_f:
                try:
                    result = subprocess.run(
                        cmd_parts,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        cwd=str(self.root_dir),
                        timeout=500,
                    )
                    exit_code = result.returncode
                except Exception as e:
                    exit_code = 1
                    print(f"Warning: Failed to run analysis command: {e}")
                    return None

            # 等待日志文件写入完成
            time.sleep(0.1)

            if exit_code != 0:
                print(f"错误: 智能体执行分析失败，退出码: {exit_code}")
                return None

            # 读取分析结果
            try:
                with open(analysis_log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()

                # 提取分析结果
                extracted = self._extract_analysis_result(log_content)
                if extracted:
                    # 成功提取结果，清理临时文件
                    try:
                        analysis_log_file.unlink(missing_ok=True)
                    except:
                        pass
                    return extracted

                print("Warning: Failed to extract analysis result from log")
                return "智能体执行分析完成，但无法提取分析结果。"

            except Exception as e:
                print(f"Warning: Failed to read analysis log file: {e}")
                return None

        except Exception as e:
            print(f"错误: 执行智能体分析失败: {e}")
            return None
        finally:
            # 确保临时日志文件被清理
            if analysis_log_file and analysis_log_file.exists():
                try:
                    analysis_log_file.unlink(missing_ok=True)
                except:
                    pass

    def _extract_analysis_result(self, log_content: str):
        """从DOLPHIN_VARIABLES_OUTPUT标记中提取分析结果"""
        if not log_content:
            return None

        try:
            # 使用基类的通用方法提取变量输出部分
            variables_section = self._extract_result_from_log(
                log_content,
                DOLPHIN_VARIABLES_OUTPUT_START,
                DOLPHIN_VARIABLES_OUTPUT_END,
            )
            if not variables_section:
                return None

            # 解析JSON
            variables = json.loads(variables_section)

            # 提取分析结果
            analysis_result = variables.get("analysis_result", {}).get("answer")
            if isinstance(analysis_result, str) and analysis_result.strip():
                return analysis_result.strip()
            return None

        except Exception as e:
            print(f"Warning: Failed to extract analysis result from log: {e}")
            return None

    # _load_knowledge method moved to BaseAnalyzer

    def _save_analysis_result(self, run_name, case_num, analysis_result):
        """保存分析结果到文件"""
        # 使用基类方法查找run目录
        run_dir = self._find_run_directory(run_name)
        if not run_dir:
            return

        # 创建 analysis 目录
        analysis_dir = run_dir / "analysis"
        analysis_dir.mkdir(exist_ok=True)

        # 保存分析结果
        case_num_padded = f"{int(case_num):03d}"
        result_file = analysis_dir / f"case_{case_num_padded}.txt"

        try:
            with open(result_file, "w", encoding="utf-8") as f:
                f.write(f"=== Analysis Result for Case {case_num_padded} ===\n")
                f.write(f"Run: {run_name}\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n" + "=" * 60 + "\n\n")
                f.write("===ANALYSIS_START===\n")
                f.write(analysis_result)
                f.write("\n===ANALYSIS_END===\n")
            print(f"💾 分析结果已保存到: {result_file}")
        except Exception as e:
            print(f"Warning: 保存分析结果失败: {e}")

    def load_analysis_result(self, run_name, case_num):
        """加载已保存的分析结果"""
        run_dir = self._find_run_directory(run_name)
        if not run_dir:
            return None

        # 查找分析结果文件
        case_num_padded = f"{int(case_num):03d}"
        result_file = run_dir / "analysis" / f"case_{case_num_padded}.txt"

        if not result_file.exists():
            return None

        try:
            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()
                # 首先尝试从===ANALYSIS_START===和===ANALYSIS_END===中提取
                start_marker = "===ANALYSIS_START==="
                end_marker = "===ANALYSIS_END==="
                start_pos = content.find(start_marker)
                if start_pos != -1:
                    end_pos = content.find(end_marker, start_pos)
                    if end_pos != -1:
                        # 提取标记之间的内容
                        return content[start_pos + len(start_marker) : end_pos].strip()

                # 如果没有找到标记，使用旧的方式
                separator = "=" * 60 + "\n\n"
                if separator in content:
                    return content.split(separator, 1)[1]
                return content
        except Exception as e:
            print(f"Warning: 加载分析结果失败: {e}")
            return None
