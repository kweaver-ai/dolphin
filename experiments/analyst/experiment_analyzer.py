#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
import os
import pandas as pd
import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import subprocess
import sys
import numpy as np  # Added import for numpy

# 注意：此文件现在主要作为数据加载器使用
# 新的架构中：
# - GeneralReporter: 负责总体报告生成
# - ExecutionAnalyzer: 负责智能体执行分析
# - ExperimentCoordinator: 负责协调和参数分发

try:
    from .base_analyzer import BaseAnalyzer
except ImportError:
    from base_analyzer import BaseAnalyzer


class ExperimentAnalyzer(BaseAnalyzer):
    CONFIG_FIELDS = [
        {
            "name": "Default LLM",
            "path": lambda config: config.get("default", "unknown"),
        },
        {
            "name": "Model Name",
            "path": lambda config: (
                config["llms"][config.get("default", "unknown")].get(
                    "model_name", "unknown"
                )
                if "llms" in config
                and config.get("default", "unknown") in config["llms"]
                else "unknown"
            ),
        },
        {
            "name": "Cloud",
            "path": lambda config: (
                config["llms"][config.get("default", "unknown")].get("cloud", "unknown")
                if "llms" in config
                and config.get("default", "unknown") in config["llms"]
                else "unknown"
            ),
        },
        {
            "name": "Type API",
            "path": lambda config: (
                config["llms"][config.get("default", "unknown")].get(
                    "type_api", "unknown"
                )
                if "llms" in config
                and config.get("default", "unknown") in config["llms"]
                else "unknown"
            ),
        },
        {
            "name": "Max Tokens",
            "path": lambda config: (
                config["llms"][config.get("default", "unknown")].get(
                    "max_tokens", "unknown"
                )
                if "llms" in config
                and config.get("default", "unknown") in config["llms"]
                else "unknown"
            ),
        },
        {
            "name": "Strategy",
            "path": lambda config: config.get("context_engineer", {}).get(
                "default_strategy", "unknown"
            ),
        },
    ]

    # Variable encoding rules - configurable and extensible
    VARIABLE_ENCODING_RULES = {
        # Boolean variables with True/False values
        "boolean_vars": {
            "explore_block_v2": {"True": "E", "False": "e"},
            "prompt_skillcall": {"True": "P", "False": "p"},
            "use_memory": {"True": "M", "False": "m"},
            "enable_cache": {"True": "C", "False": "c"},
            "verbose_mode": {"True": "V", "False": "v"},
            "debug_enabled": {"True": "D", "False": "d"},
        },
        # Categorical variables with multiple possible values
        "categorical_vars": {
            "model_type": {
                "gpt": "G",
                "claude": "C",
                "llama": "L",
                "qwen": "Q",
                "deepseek": "D",
            },
            "strategy": {
                "aggressive": "A",
                "conservative": "C",
                "balanced": "B",
                "adaptive": "D",
            },
            "mode": {
                "production": "P",
                "development": "D",
                "testing": "T",
                "experimental": "E",
            },
        },
        # Numeric variables (will be mapped to ranges)
        "numeric_vars": {
            "max_tokens": [
                (1000, "S"),  # Small
                (4000, "M"),  # Medium
                (8000, "L"),  # Large
                (float("inf"), "X"),  # Extra Large
            ],
            "temperature": [
                (0.3, "L"),  # Low
                (0.7, "M"),  # Medium
                (1.0, "H"),  # High
                (float("inf"), "X"),  # Extra High
            ],
            "timeout": [
                (30, "S"),  # Short
                (120, "M"),  # Medium
                (300, "L"),  # Long
                (float("inf"), "X"),  # Extra Long
            ],
        },
    }

    def __init__(self, experiment_path):
        """
        初始化实验分析器

        Args:
            experiment_path: experiments/env下的实验目录路径
        """

        # 使用父类初始化，但先创建data_loader对象
        class DataLoaderAdapter:
            def __init__(self, experiment_path):
                self.experiment_path = Path(experiment_path)
                self.experiment_name = self.experiment_path.name
                self.root_dir = Path(__file__).parent.parent.parent
                self.dolphin_cmd = self.root_dir / "bin" / "dolphin"
                self.reports_dir = self.experiment_path / "reports"
                self.reports_dir.mkdir(exist_ok=True, parents=True)

        # 调用父类初始化
        super().__init__(DataLoaderAdapter(experiment_path))

        # ExperimentAnalyzer特有属性
        self.runs = []

        # 注意：此类现在主要用作数据加载器
        # 分析功能已移至专门的模块中

    @classmethod
    def add_variable_encoding_rule(cls, var_type, var_name, encoding_dict):
        """
        动态添加变量编码规则，提高扩展性

        Args:
            var_type: 'boolean_vars', 'categorical_vars', or 'numeric_vars'
            var_name: 变量名
            encoding_dict: 编码映射字典或数值范围列表

        Examples:
            # 添加布尔变量
            ExperimentAnalyzer.add_variable_encoding_rule(
                'boolean_vars', 'new_feature', {'True': 'N', 'False': 'n'}
            )

            # 添加分类变量
            ExperimentAnalyzer.add_variable_encoding_rule(
                'categorical_vars', 'algorithm', {'dfs': 'D', 'bfs': 'B', 'astar': 'A'}
            )

            # 添加数值变量
            ExperimentAnalyzer.add_variable_encoding_rule(
                'numeric_vars', 'batch_size', [(16, 'S'), (64, 'M'), (256, 'L'), (float('inf'), 'X')]
            )
        """
        if var_type not in cls.VARIABLE_ENCODING_RULES:
            cls.VARIABLE_ENCODING_RULES[var_type] = {}
        cls.VARIABLE_ENCODING_RULES[var_type][var_name] = encoding_dict

    @classmethod
    def get_encoding_rules_info(cls):
        """
        获取当前所有编码规则的信息，便于查看和调试

        Returns:
            str: 格式化的编码规则信息
        """
        info = "当前变量编码规则:\n"
        info += "=" * 50 + "\n"

        for var_type, vars_dict in cls.VARIABLE_ENCODING_RULES.items():
            info += f"\n{var_type.upper()}:\n"
            info += "-" * 30 + "\n"

            for var_name, encoding in vars_dict.items():
                info += f"  {var_name}:\n"
                if isinstance(encoding, dict):
                    for value, code in encoding.items():
                        info += f"    {value} -> {code}\n"
                elif isinstance(encoding, list):
                    for threshold, code in encoding:
                        if threshold == float("inf"):
                            info += f"    >{encoding[-2][0]} -> {code}\n"
                        else:
                            info += f"    <={threshold} -> {code}\n"
                info += "\n"

        return info

    def load_experiment_data(self):
        """加载实验数据"""
        print(f"正在分析实验: {self.experiment_name}")
        print(f"实验路径: {self.experiment_path}")

        # 查找所有run目录
        run_dirs = sorted(
            [
                d
                for d in self.experiment_path.iterdir()
                if d.is_dir() and d.name.startswith("run_")
            ]
        )

        for run_dir in run_dirs:
            config_path = run_dir / "config" / "global.yaml"
            summary_path = run_dir / "run_summary.yaml"

            if config_path.exists() and summary_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                    with open(summary_path, "r", encoding="utf-8") as f:
                        summary = yaml.safe_load(f)

                    self.runs.append(
                        {
                            "run_id": run_dir.name,
                            "config": config,
                            "summary": summary,
                            "entrypoint": summary.get("entrypoint", "unknown"),
                            "variables": summary.get("variables", {}),
                        }
                    )
                    print(f"  ✓ 成功加载 {run_dir.name}")
                except Exception as e:
                    print(f"  ✗ 加载 {run_dir.name} 失败: {e}")
            else:
                print(f"  ✗ {run_dir.name} 缺少必要文件")

        print(f"成功读取 {len(self.runs)} 个实验结果\n")
        return len(self.runs) > 0

    def parse_variables_string(self, variables_str):
        """
        解析variables字符串，提取key=value对

        Args:
            variables_str: 形如 "key1=value1; key2=value2" 的字符串

        Returns:
            dict: 解析后的key-value字典
        """
        variables_dict = {}
        if not variables_str or variables_str == "None":
            return variables_dict

        # 处理不同的分隔符和格式
        # 支持 "key1=value1; key2=value2" 或 "key1=value1, key2=value2" 格式
        pairs = re.split(r"[;,]", variables_str)

        for pair in pairs:
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)  # 只分割第一个=号
                key = key.strip()
                value = value.strip()
                variables_dict[key] = value

        return variables_dict

    def encode_variable_value(self, var_name, var_value):
        """
        根据编码规则将变量值编码为简短标识符

        Args:
            var_name: 变量名
            var_value: 变量值

        Returns:
            str: 编码后的标识符，如果无法编码则返回None
        """
        # 处理布尔变量
        boolean_vars = self.VARIABLE_ENCODING_RULES.get("boolean_vars", {})
        if var_name in boolean_vars:
            return boolean_vars[var_name].get(str(var_value))

        # 处理分类变量
        categorical_vars = self.VARIABLE_ENCODING_RULES.get("categorical_vars", {})
        if var_name in categorical_vars:
            # 支持部分匹配（不区分大小写）
            value_lower = str(var_value).lower()
            for key, code in categorical_vars[var_name].items():
                if key.lower() in value_lower or value_lower in key.lower():
                    return code
            return categorical_vars[var_name].get(str(var_value))

        # 处理数值变量
        numeric_vars = self.VARIABLE_ENCODING_RULES.get("numeric_vars", {})
        if var_name in numeric_vars:
            try:
                num_value = float(var_value)
                ranges = numeric_vars[var_name]
                for threshold, code in ranges:
                    if num_value <= threshold:
                        return code
            except (ValueError, TypeError):
                pass

        # 如果没有匹配的编码规则，返回None
        return None

    def detect_varying_variables(self):
        """
        动态检测当前实验中哪些变量真正发生了变化

        Returns:
            dict: {变量名: [所有不同的值]}
        """
        all_variables = {}

        # 收集所有run的所有变量
        for run in self.runs:
            variables = run.get("variables", {})
            for var_name, var_value in variables.items():
                if var_name not in all_variables:
                    all_variables[var_name] = set()
                all_variables[var_name].add(str(var_value))

        # 只保留有变化的变量（值不止一个）
        varying_variables = {}
        for var_name, values in all_variables.items():
            if len(values) > 1:
                varying_variables[var_name] = sorted(list(values))

        return varying_variables

    def generate_dynamic_encoding_rules(self, varying_variables):
        """
        为变化的变量动态生成编码规则

        Args:
            varying_variables: {变量名: [不同值列表]}

        Returns:
            dict: 动态生成的编码规则
        """
        dynamic_rules = {}

        for var_name, values in varying_variables.items():
            # 为每个变量的不同值生成编码
            var_rules = {}

            # 对于布尔值，使用大小写字母
            if set(values) == {"True", "False"} or set(values) == {"true", "false"}:
                var_rules = {"True": var_name[0].upper(), "False": var_name[0].lower()}
                if "true" in values:
                    var_rules = {
                        "true": var_name[0].upper(),
                        "false": var_name[0].lower(),
                    }

            # 对于其他类型，使用数字或字母序列
            else:
                # 使用变量名首字母 + 数字，统一处理所有变量
                base_char = var_name[0].lower()
                for i, value in enumerate(values):
                    var_rules[value] = f"{base_char}{i+1}"

            dynamic_rules[var_name] = var_rules

        return dynamic_rules

    def generate_variable_code(self, variables_dict, dynamic_rules=None):
        """
        为variables字典生成编码字符串，优先使用动态规则

        Args:
            variables_dict: 变量字典
            dynamic_rules: 动态生成的编码规则

        Returns:
            str: 编码后的字符串
        """
        code_parts = []

        # 按变量名排序，确保一致的输出
        for var_name in sorted(variables_dict.keys()):
            var_value = variables_dict[var_name]
            code = None

            # 优先使用动态规则
            if dynamic_rules and var_name in dynamic_rules:
                code = dynamic_rules[var_name].get(str(var_value))

            # 如果动态规则没有，再尝试静态规则
            if not code:
                code = self.encode_variable_value(var_name, var_value)

            if code:
                code_parts.append(code)

        return "".join(code_parts)

    def analyze_configs(self):
        """分析实验配置 - 包含entrypoint、config和variables的完整配置"""
        config_table = []
        for run in self.runs:
            config = run["config"]
            entrypoint = run.get("entrypoint", "unknown")
            variables = run.get("variables", {})

            # Debug: 打印读取到的信息
            if entrypoint == "unknown":
                print(
                    f"Warning: entrypoint not found for {run['run_id']}, available keys: {list(run.keys())}"
                )

            # 处理variables，将其转换为可显示的字符串
            variables_str = ""
            if variables:
                var_parts = []
                for key, value in variables.items():
                    if isinstance(value, str) and len(value) > 50:
                        # 长字符串截断显示
                        var_parts.append(f"{key}={value[:47]}...")
                    else:
                        var_parts.append(f"{key}={value}")
                variables_str = "; ".join(var_parts)
            else:
                variables_str = "None"

            config_table.append(
                {
                    "Run ID": run["run_id"],
                    "Entrypoint": entrypoint,
                    **{
                        field["name"]: field["path"](config)
                        for field in self.CONFIG_FIELDS
                    },
                    "Variables": (
                        variables_str[:100] + "..."
                        if len(variables_str) > 100
                        else variables_str
                    ),
                }
            )

        df = pd.DataFrame(config_table)

        # 过滤掉值都是 "unknown" 的列
        columns_to_keep = ["Run ID"]  # 总是保留 Run ID
        for col in df.columns:
            if col == "Run ID":
                continue
            unique_values = df[col].unique()
            # 如果列的所有值都是 "unknown"，则不保留该列
            if not (len(unique_values) == 1 and unique_values[0] == "unknown"):
                columns_to_keep.append(col)

        return df[columns_to_keep]

    def generate_run_labels(self):
        """为每个run生成简洁的标识符[abcd]，表示配置的不同部分，动态检测变化的变量"""
        config_df = self.analyze_configs()

        # 动态检测变化的variables
        varying_variables = self.detect_varying_variables()
        dynamic_rules = self.generate_dynamic_encoding_rules(varying_variables)

        # 确定变化的因子
        varying_factors = []
        for col in config_df.columns:
            if col == "Run ID":
                continue
            if config_df[col].nunique() > 1:
                varying_factors.append(col)

        # 为每个因子的不同值分配简短字母代码
        factor_codes = {}
        legend = {}  # 保存标识符说明

        for factor in varying_factors:
            unique_values = sorted(config_df[factor].unique())
            codes = {}

            if factor == "Model Name":
                # 模型名称使用特定映射，避免与其他因子冲突
                for i, value in enumerate(unique_values):
                    if "deepseek" in value.lower():
                        codes[value] = "D"
                        legend["D"] = f"DeepSeek模型"
                    elif "qwen" in value.lower():
                        codes[value] = "Q"
                        legend["Q"] = f"Qwen模型"
                    elif "gpt" in value.lower():
                        codes[value] = "G"
                        legend["G"] = f"GPT模型"
                    elif "kimi" in value.lower():
                        codes[value] = "K"
                        legend["K"] = f"Kimi模型"
                    else:
                        # 使用后面的字母避免冲突
                        codes[value] = chr(77 + i)  # M, N, O...
                        legend[chr(77 + i)] = f"{value}"
            elif factor == "Default LLM":
                # LLM 配置使用数字和特殊字符，避免与Model Name冲突
                for i, value in enumerate(unique_values):
                    if "qwen" in value.lower() or "q" in value.lower():
                        codes[value] = "1"
                        legend["1"] = f"LLM配置: {value}"
                    elif "v3" in value.lower() or "deepseek" in value.lower():
                        codes[value] = "2"
                        legend["2"] = f"LLM配置: {value}"
                    elif "k2" in value.lower() or "kimi" in value.lower():
                        codes[value] = "3"
                        legend["3"] = f"LLM配置: {value}"
                    else:
                        codes[value] = str(4 + i)
                        legend[str(4 + i)] = f"LLM配置: {value}"
            elif factor == "Variables":
                # Variables字段使用动态编码系统
                for i, value in enumerate(unique_values):
                    # 解析variables字符串
                    variables_dict = self.parse_variables_string(value)

                    # 使用动态规则生成编码
                    variable_code = self.generate_variable_code(
                        variables_dict, dynamic_rules
                    )

                    if variable_code:
                        codes[value] = variable_code
                        # 更新图例信息 - 只为真正变化的变量添加图例
                        for var_name, var_value in variables_dict.items():
                            if var_name in varying_variables:
                                if var_name in dynamic_rules:
                                    code = dynamic_rules[var_name].get(str(var_value))
                                    if code and code not in legend:
                                        legend[code] = f"{var_name}={var_value}"
                    else:
                        # 如果无法编码，使用默认字母
                        codes[value] = chr(65 + i)
                        legend[chr(65 + i)] = (
                            f"Variables={value[:30]}{'...' if len(value) > 30 else ''}"
                        )
            elif factor == "Entrypoint":
                # Entrypoint使用特殊符号，避免冲突
                symbols = ["@", "#", "&", "*", "+", "~", "^", "%"]
                for i, value in enumerate(unique_values):
                    if i < len(symbols):
                        codes[value] = symbols[i]
                        legend[symbols[i]] = f"入口点: {value}"
                    else:
                        codes[value] = f"E{i}"
                        legend[f"E{i}"] = f"入口点: {value}"
            else:
                # 其他因子使用后段字母序列，避免冲突
                start_char = 80  # 从P开始，避免与常用编码冲突
                for i, value in enumerate(unique_values):
                    codes[value] = chr(start_char + i)
                    legend[chr(start_char + i)] = f"{factor}={value}"

            factor_codes[factor] = codes

        # 为每个run生成标识符
        run_labels = {}
        for _, row in config_df.iterrows():
            run_id = row["Run ID"]
            label_parts = []

            for factor in varying_factors:
                value = row[factor]
                if factor in factor_codes and value in factor_codes[factor]:
                    label_parts.append(factor_codes[factor][value])

            label = "".join(label_parts)
            run_labels[run_id] = f"{run_id}[{label}]"

        # 保存图例信息和动态规则信息
        self.run_label_legend = legend
        self.varying_variables = varying_variables
        self.dynamic_rules = dynamic_rules
        return run_labels

    def analyze_config_impact(self, config_df, accuracy_df):
        """分析配置差异对准确率的影响 - 基于entrypoint、model和variables"""
        # Merge config and accuracy
        merged = pd.merge(config_df, accuracy_df, on="Run ID")

        # Convert Accuracy to float for aggregation
        merged["Accuracy"] = merged["Accuracy"].str.rstrip("%").astype(float) / 100  # type: ignore

        # Group by the key experimental factors and compute avg accuracy
        factors = (
            ["Entrypoint"]
            + [field["name"] for field in self.CONFIG_FIELDS]
            + ["Variables"]
        )

        impact_analyses = []

        for factor in factors:
            if factor not in merged.columns or merged[factor].nunique() <= 1:
                continue

            impact = (
                merged.groupby(factor)["Accuracy"]
                .agg(["mean", "count", "std", "var"])
                .reset_index()
            )
            impact["Factor"] = factor
            impact["Value"] = impact[factor]

            for _, row in impact.iterrows():
                impact_analyses.append(
                    {
                        "Factor": row["Factor"],
                        "Value": (
                            str(row["Value"])[:50] + "..."
                            if len(str(row["Value"])) > 50
                            else str(row["Value"])
                        ),
                        "Avg Accuracy": f"{row['mean']:.2%}",
                        "Runs": int(row["count"]),
                        "Std Dev": (
                            f"{row['std']:.3f}" if pd.notna(row["std"]) else "0.000"
                        ),
                        "Variance": (
                            f"{row['var']:.6f}" if pd.notna(row["var"]) else "0.000000"
                        ),
                    }
                )

        return pd.DataFrame(impact_analyses)

    def analyze_accuracy(self):
        """分析准确率"""
        accuracy_table = []
        for run in self.runs:
            benchmarks = run["summary"]["benchmarks"]
            correct_count = sum(1 for b in benchmarks if b["is_correct"])
            total_count = len(benchmarks)
            accuracy = correct_count / total_count if total_count > 0 else 0

            accuracy_table.append(
                {
                    "Run ID": run["run_id"],
                    "Total Questions": total_count,
                    "Correct": correct_count,
                    "Incorrect": total_count - correct_count,
                    "Accuracy": f"{accuracy:.2%}",
                }
            )

        return pd.DataFrame(accuracy_table)

    def _create_token_lookup_dict(self):
        """创建 token 消耗查找字典"""
        token_df = self.analyze_token_consumption()
        token_dict = {}
        for _, row in token_df.iterrows():
            run_id = row["Run ID"]
            # 提取数值（去掉逗号分隔符）
            try:
                total_tokens = int(row["Total All Tokens"].replace(",", ""))
                avg_tokens_per_case = float(row["Avg Total/Case"])
                avg_llm_calls = float(row["Avg LLM Calls/Case"])
                input_output_ratio = (
                    float(row["Input/Output Ratio"])
                    if row["Input/Output Ratio"] != "N/A"
                    else 0
                )
            except:
                total_tokens = 0
                avg_tokens_per_case = 0
                avg_llm_calls = 0
                input_output_ratio = 0

            token_dict[run_id] = {
                "total_tokens": total_tokens,
                "avg_tokens_per_case": avg_tokens_per_case,
                "avg_llm_calls": avg_llm_calls,
                "input_output_ratio": input_output_ratio,
            }
        return token_dict

    def analyze_by_factors(self):
        """按所有变化因子分组分析，包括单独的variables分析"""
        # 获取配置数据框以确定哪些因子有变化
        config_df = self.analyze_configs()
        latency_df = self.analyze_latency()

        # 创建延迟查找字典
        latency_dict = {}
        for _, row in latency_df.iterrows():
            run_id = row["Run ID"]
            # 提取数值（去掉单位）
            avg_latency_str = row["Avg Latency"].replace("s", "")
            try:
                avg_latency = float(avg_latency_str)
            except:
                avg_latency = 0
            latency_dict[run_id] = avg_latency

        # 创建 token 消耗查找字典
        token_dict = self._create_token_lookup_dict()

        # 确定哪些配置字段有变化（不是所有值都相同）
        varying_factors = []
        for col in config_df.columns:
            if col == "Run ID":
                continue
            if config_df[col].nunique() > 1:  # 如果有超过1个不同值，说明这个因子有变化
                varying_factors.append(col)

        # 按每个变化因子分组分析
        factor_groups = {}

        for factor in varying_factors:
            factor_groups[factor] = defaultdict(list)

            for _, row in config_df.iterrows():
                run_id = row["Run ID"]
                factor_value = row[factor]

                # 找到对应的run数据
                run_data = next((r for r in self.runs if r["run_id"] == run_id), None)
                if run_data:
                    benchmarks = run_data["summary"]["benchmarks"]
                    correct_count = sum(1 for b in benchmarks if b["is_correct"])
                    total_count = len(benchmarks)
                    accuracy = correct_count / total_count if total_count > 0 else 0
                    avg_latency = latency_dict.get(run_id, 0)
                    token_stats = token_dict.get(run_id, {})

                    factor_groups[factor][factor_value].append(
                        {
                            "run_id": run_id,
                            "accuracy": accuracy,
                            "correct": correct_count,
                            "total": total_count,
                            "avg_latency": avg_latency,
                            "total_tokens": token_stats.get("total_tokens", 0),
                            "avg_tokens_per_case": token_stats.get(
                                "avg_tokens_per_case", 0
                            ),
                            "avg_llm_calls": token_stats.get("avg_llm_calls", 0),
                            "input_output_ratio": token_stats.get(
                                "input_output_ratio", 0
                            ),
                        }
                    )

        return factor_groups

    def analyze_individual_variables(self):
        """按单个变量分别分析，使用通用变量解析系统"""
        config_df = self.analyze_configs()
        latency_df = self.analyze_latency()

        # 创建延迟查找字典
        latency_dict = {}
        for _, row in latency_df.iterrows():
            run_id = row["Run ID"]
            avg_latency_str = row["Avg Latency"].replace("s", "")
            try:
                avg_latency = float(avg_latency_str)
            except:
                avg_latency = 0
            latency_dict[run_id] = avg_latency

        # 创建 token 消耗查找字典
        token_dict = self._create_token_lookup_dict()

        # 收集所有变量名
        all_variable_names = set()
        for run in self.runs:  # Use self.runs instead of config_df
            variables_dict = run.get("variables", {})
            all_variable_names.update(variables_dict.keys())

        # 为每个变量创建分组
        variable_groups = {}
        for var_name in all_variable_names:
            variable_groups[var_name] = defaultdict(list)

        for run in self.runs:  # Use self.runs directly
            run_id = run["run_id"]
            variables_dict = run.get("variables", {})

            # 找到对应的run数据
            run_data = run  # Already have it
            benchmarks = run_data["summary"]["benchmarks"]
            correct_count = sum(1 for b in benchmarks if b["is_correct"])
            total_count = len(benchmarks)
            accuracy = correct_count / total_count if total_count > 0 else 0
            avg_latency = latency_dict.get(run_id, 0)
            token_stats = token_dict.get(run_id, {})

            run_info = {
                "run_id": run_id,
                "accuracy": accuracy,
                "correct": correct_count,
                "total": total_count,
                "avg_latency": avg_latency,
                "total_tokens": token_stats.get("total_tokens", 0),
                "avg_tokens_per_case": token_stats.get("avg_tokens_per_case", 0),
                "avg_llm_calls": token_stats.get("avg_llm_calls", 0),
                "input_output_ratio": token_stats.get("input_output_ratio", 0),
            }

            # 将run_info添加到每个变量的对应值分组中
            for var_name in all_variable_names:
                var_value = variables_dict.get(var_name, "Unknown")
                # Handle list values properly
                if isinstance(var_value, list):
                    var_value = str(var_value)
                variable_groups[var_name][var_value].append(run_info)

        return variable_groups

    def analyze_logs(self, run_path):
        """分析日志文件来检测错误模式和异常"""
        log_dir = Path(run_path) / ".."
        if not log_dir.exists():
            print(f"日志目录不存在: {log_dir}")
            return {}

        error_patterns = [
            r"ERROR:.*",
            r"Exception:.*",
            r"Traceback.*",
            r"Failed.*",
            r"Connection.*error.*",
            r"Timeout.*",
            r"HTTP.*error.*",
            r"API.*error.*",
        ]

        warning_patterns = [r"WARNING:.*", r"WARN:.*", r"deprecated.*", r"retry.*"]

        errors = []
        warnings = []

        for log_file in log_dir.rglob("*.log"):
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()
                for pattern in error_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    errors.extend(matches)
                for pattern in warning_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    warnings.extend(matches)
        return {"errors": errors, "warnings": warnings}

    def analyze_case_logs(self, run_dir):
        """分析单个run的所有case日志文件"""
        run_path = Path(run_dir)

        # 优先检查新的console目录
        console_path = run_path / "console"
        if console_path.exists():
            run_path = console_path
        else:
            # 回退到旧的log目录
            run_path = run_path / "log"

        log_files = list(run_path.glob("*.log"))

        error_stats = defaultdict(int)
        warning_stats = defaultdict(int)
        file_size_stats = []
        case_analysis = {}

        error_patterns = [
            r"ERROR:.*",
            r"Exception:.*",
            r"Traceback.*",
            r"Failed.*",
            r"Connection.*error.*",
            r"Timeout.*",
            r"HTTP.*error.*",
            r"API.*error.*",
            r"ValueError.*",
            r"Failed to parse JSON.*",
        ]

        warning_patterns = [r"WARNING:.*", r"WARN:.*", r"deprecated.*", r"retry.*"]

        for log_file in log_files:
            # 支持新的case_XXX.log格式和旧的experiment_run_XXX.log格式
            if not (
                log_file.name.startswith("case_")
                or log_file.name.startswith("experiment_run_")
            ):
                continue

            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.read()

                errors = []
                warnings = []

                for pattern in error_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
                    errors.extend(matches)

                for pattern in warning_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
                    warnings.extend(matches)

                # 统计错误和警告
                for error in errors:
                    error_stats[error[:100]] += 1  # 截取前100个字符

                for warning in warnings:
                    warning_stats[warning[:100]] += 1

                file_size = log_file.stat().st_size
                file_size_stats.append((log_file.name, file_size))

                case_analysis[log_file.name] = {
                    "file_size": file_size,
                    "errors": errors,
                    "warnings": warnings,
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                }

            except Exception as e:
                print(f"  警告: 无法读取日志文件 {log_file}: {e}")

        return {
            "error_stats": error_stats,
            "warning_stats": warning_stats,
            "file_size_stats": file_size_stats,
            "case_analysis": case_analysis,
        }

    def analyze_call_chains(self, run_dir):
        """分析单个run下所有case的调用链"""
        history_dir = Path(run_dir) / "history"
        if not history_dir.exists():
            return {}

        call_chain_analysis = {}
        case_files = sorted(history_dir.glob("case_*.jsonl"))

        for case_file in case_files:
            case_name = case_file.stem
            try:
                with open(case_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                # 解析每行JSON
                steps = []
                for line in lines:
                    line = line.strip()
                    if line:
                        try:
                            step = json.loads(line)
                            steps.append(step)
                        except json.JSONDecodeError:
                            continue

                # 分析调用链
                call_chain_stats = self._analyze_single_case_chain(steps, case_name)
                call_chain_analysis[case_name] = call_chain_stats

            except Exception as e:
                print(f"  警告: 无法分析case文件 {case_file}: {e}")
                call_chain_analysis[case_name] = {
                    "error": str(e),
                    "total_steps": 0,
                    "agent_calls": {},
                    "tool_calls": {},
                    "interaction_rounds": 0,
                }

        return call_chain_analysis

    def _analyze_single_case_chain(self, steps, case_name):
        """分析单个case的调用链详情"""
        agent_calls = defaultdict(int)
        tool_calls = defaultdict(int)
        stage_stats = defaultdict(int)
        status_stats = defaultdict(int)

        total_execution_time = 0
        llm_rounds = 0
        skill_rounds = 0

        # 分析每个步骤
        for step in steps:
            agent_name = step.get("agent_name", "unknown")
            stage = step.get("stage", "unknown")
            status = step.get("status", "unknown")
            skill_info = step.get("skill_info")

            # 统计agent调用
            if agent_name:
                agent_calls[agent_name] += 1

            # 统计stage类型
            stage_stats[stage] += 1

            # 统计状态
            status_stats[status] += 1

            # 统计LLM轮数
            if stage == "llm":
                llm_rounds += 1

            # 统计技能/工具调用
            if stage == "skill" and skill_info:
                skill_rounds += 1
                if isinstance(skill_info, dict):
                    tool_name = skill_info.get("name", "unknown_tool")
                    tool_calls[tool_name] += 1

            # 计算执行时间
            start_time = step.get("start_time", 0)
            end_time = step.get("end_time", 0)
            if start_time and end_time:
                total_execution_time += end_time - start_time

        # 计算交互轮数（LLM + Skill的组合轮数）
        interaction_rounds = max(llm_rounds, skill_rounds)

        return {
            "total_steps": len(steps),
            "agent_calls": dict(agent_calls),
            "tool_calls": dict(tool_calls),
            "stage_stats": dict(stage_stats),
            "status_stats": dict(status_stats),
            "llm_rounds": llm_rounds,
            "skill_rounds": skill_rounds,
            "interaction_rounds": interaction_rounds,
            "total_execution_time": total_execution_time,
            "avg_step_time": total_execution_time / len(steps) if steps else 0,
        }

    def analyze_all_call_chains(self):
        """分析所有run的调用链，生成汇总统计"""
        all_call_chains = {}

        # 收集所有run的调用链数据
        for run in self.runs:
            run_dir = self.experiment_path / run["run_id"]
            call_chains = self.analyze_call_chains(run_dir)
            all_call_chains[run["run_id"]] = call_chains

        # 生成汇总统计
        return self._generate_call_chain_summary(all_call_chains)

    def _generate_call_chain_summary(self, all_call_chains):
        """生成调用链汇总分析"""
        # 按run汇总
        run_summaries = []

        # 全局统计
        global_agent_usage = defaultdict(int)
        global_tool_usage = defaultdict(int)
        global_interaction_stats = []

        for run_id, call_chains in all_call_chains.items():
            if not call_chains:
                continue

            # 计算本run的统计数据
            run_stats = {
                "run_id": run_id,
                "total_cases": len(call_chains),
                "avg_interaction_rounds": 0,
                "avg_llm_rounds": 0,
                "avg_skill_rounds": 0,
                "avg_total_steps": 0,
                "avg_execution_time": 0,
                "most_used_agents": {},
                "most_used_tools": {},
                "successful_cases": 0,
                "failed_cases": 0,
            }

            # 统计数据收集
            interaction_rounds = []
            llm_rounds = []
            skill_rounds = []
            total_steps = []
            execution_times = []
            run_agent_usage = defaultdict(int)
            run_tool_usage = defaultdict(int)

            for case_name, case_stats in call_chains.items():
                if "error" in case_stats:
                    run_stats["failed_cases"] += 1
                    continue

                run_stats["successful_cases"] += 1

                # 收集数值数据
                interaction_rounds.append(case_stats.get("interaction_rounds", 0))
                llm_rounds.append(case_stats.get("llm_rounds", 0))
                skill_rounds.append(case_stats.get("skill_rounds", 0))
                total_steps.append(case_stats.get("total_steps", 0))
                execution_times.append(case_stats.get("total_execution_time", 0))

                # 收集agent使用情况
                for agent, count in case_stats.get("agent_calls", {}).items():
                    run_agent_usage[agent] += count
                    global_agent_usage[agent] += count

                # 收集工具使用情况
                for tool, count in case_stats.get("tool_calls", {}).items():
                    run_tool_usage[tool] += count
                    global_tool_usage[tool] += count

            # 计算平均值
            if interaction_rounds:
                run_stats["avg_interaction_rounds"] = sum(interaction_rounds) / len(
                    interaction_rounds
                )
                run_stats["max_interaction_rounds"] = max(interaction_rounds)
                run_stats["min_interaction_rounds"] = min(interaction_rounds)
                run_stats["avg_llm_rounds"] = sum(llm_rounds) / len(llm_rounds)
                run_stats["avg_skill_rounds"] = sum(skill_rounds) / len(skill_rounds)
                run_stats["avg_total_steps"] = sum(total_steps) / len(total_steps)
                run_stats["avg_execution_time"] = sum(execution_times) / len(
                    execution_times
                )

                # 全局统计
                global_interaction_stats.extend(interaction_rounds)

            # 最常用的agents和tools (取前3个)
            run_stats["most_used_agents"] = dict(
                sorted(run_agent_usage.items(), key=lambda x: x[1], reverse=True)[:3]
            )
            run_stats["most_used_tools"] = dict(
                sorted(run_tool_usage.items(), key=lambda x: x[1], reverse=True)[:3]
            )

            run_summaries.append(run_stats)

        # 全局汇总
        global_summary = {
            "total_runs": len([r for r in run_summaries if r["successful_cases"] > 0]),
            "total_cases": sum(r["successful_cases"] for r in run_summaries),
            "avg_interaction_rounds_global": (
                sum(global_interaction_stats) / len(global_interaction_stats)
                if global_interaction_stats
                else 0
            ),
            "most_used_agents_global": dict(
                sorted(global_agent_usage.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "most_used_tools_global": dict(
                sorted(global_tool_usage.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "interaction_distribution": self._analyze_interaction_distribution(
                global_interaction_stats
            ),
        }

        return {
            "run_summaries": run_summaries,
            "global_summary": global_summary,
            "raw_data": all_call_chains,
        }

    def _analyze_interaction_distribution(self, interaction_rounds):
        """分析交互轮数分布"""
        if not interaction_rounds:
            return {}

        from collections import Counter

        distribution = Counter(interaction_rounds)

        return {
            "min_rounds": min(interaction_rounds),
            "max_rounds": max(interaction_rounds),
            "median_rounds": sorted(interaction_rounds)[len(interaction_rounds) // 2],
            "distribution": dict(distribution),
            "cases_with_1_round": distribution.get(1, 0),
            "cases_with_2_4_rounds": sum(distribution.get(i, 0) for i in range(2, 5)),
            "cases_with_5_plus_rounds": (
                sum(
                    distribution.get(i, 0)
                    for i in range(5, max(interaction_rounds) + 1)
                )
                if interaction_rounds
                else 0
            ),
        }

    def detect_consecutive_errors(self, results_df):
        """检测连续错误模式"""
        consecutive_patterns = {}

        for run_id in [col for col in results_df.columns if col.startswith("run_")]:
            errors = []
            for i, result in enumerate(results_df[run_id]):
                if result == "✗":
                    errors.append(i + 1)  # 题目编号从1开始

            # 找连续错误段
            consecutive_errors = []
            if errors:
                current_streak = [errors[0]]

                for i in range(1, len(errors)):
                    if errors[i] == errors[i - 1] + 1:
                        current_streak.append(errors[i])
                    else:
                        if len(current_streak) >= 5:  # 只记录长度>=5的连续错误
                            consecutive_errors.append(current_streak)
                        current_streak = [errors[i]]

                if len(current_streak) >= 5:
                    consecutive_errors.append(current_streak)

            consecutive_patterns[run_id] = consecutive_errors

        return consecutive_patterns

    def create_detailed_comparison(self):
        if not self.runs:
            return pd.DataFrame()

        # 获取所有题目（以第一个run为基准）
        all_questions = []
        base_benchmarks = self.runs[0]["summary"]["benchmarks"]

        for i, benchmark in enumerate(base_benchmarks):
            query = benchmark["Query"]
            topic = benchmark["Topic"]
            all_questions.append({"index": i + 1, "topic": topic, "query": query})

        # 创建结果矩阵
        results_data = []
        for i, question in enumerate(all_questions):
            row = {
                "题目编号": question["index"],
                "题目类型": question["topic"],
                "题目内容": (
                    question["query"][:80] + "..."
                    if len(question["query"]) > 80
                    else question["query"]
                ),
            }

            # 为每个run添加结果
            correct_count = 0
            total_runs = 0
            for run in self.runs:
                benchmarks = run["summary"]["benchmarks"]
                result = "-"

                # 尝试通过索引匹配题目
                if i < len(benchmarks):
                    if benchmarks[i]["Query"] == question["query"]:
                        result = "✓" if benchmarks[i]["is_correct"] else "✗"
                    else:
                        # 如果索引不匹配，尝试通过内容匹配
                        for benchmark in benchmarks:
                            if benchmark["Query"] == question["query"]:
                                result = "✓" if benchmark["is_correct"] else "✗"
                                # 未提取到有效answer，则继续扫描后续包含 _progress 的行

                row[run["run_id"]] = result

                # 统计正确率
                if result != "-":
                    total_runs += 1
                    if result == "✓":
                        correct_count += 1

            # 添加整体正确率列
            if total_runs > 0:
                accuracy = correct_count / total_runs * 100
                row["整体正确率"] = f"{accuracy:.1f}%"
            else:
                row["整体正确率"] = "N/A"

            results_data.append(row)

        return pd.DataFrame(results_data)

    def analyze_model_consistency(self, results_df):
        """分析相同模型的一致性"""
        # 按模型分组
        model_groups = defaultdict(list)

        for run in self.runs:
            config = run["config"]
            default_llm = config.get("default", "unknown")
            if "llms" in config and default_llm in config["llms"]:
                model_name = config["llms"][default_llm].get("model_name", "unknown")
            else:
                model_name = "unknown"

            model_groups[model_name].append(run["run_id"])

        consistency_analysis = []

        # 分析每个模型组内的一致性
        for model_name, run_ids in model_groups.items():
            if len(run_ids) > 1:
                # 对于每对run，计算差异
                for i in range(len(run_ids)):
                    for j in range(i + 1, len(run_ids)):
                        run1, run2 = run_ids[i], run_ids[j]
                        run1_label = self.run_labels.get(run1, run1)
                        run2_label = self.run_labels.get(run2, run2)

                        diff_count = 0
                        total_count = 0
                        examples = []

                        for _, row in results_df.iterrows():
                            if row[run1] != "-" and row[run2] != "-":
                                total_count += 1
                                if row[run1] != row[run2]:
                                    diff_count += 1
                                    if len(examples) < 10:  # 保存前10个差异示例
                                        examples.append(
                                            {
                                                "question_no": row["题目编号"],
                                                "run1_result": row[run1],
                                                "run2_result": row[run2],
                                                "content": (
                                                    row["题目内容"][:60] + "..."
                                                    if len(row["题目内容"]) > 60
                                                    else row["题目内容"]
                                                ),
                                            }
                                        )

                        consistency_rate = (
                            (total_count - diff_count) / total_count
                            if total_count > 0
                            else 0
                        )

                        consistency_analysis.append(
                            {
                                "model_name": model_name,
                                "run1": run1_label,
                                "run2": run2_label,
                                "total_questions": total_count,
                                "different_answers": diff_count,
                                "consistency_rate": consistency_rate,
                                "examples": examples,
                            }
                        )

        return consistency_analysis

    def analyze_latency(self):
        """分析真实的执行延迟 - 使用文件时间戳计算实际执行时间"""
        latency_table = []
        for run in self.runs:
            run_dir = self.experiment_path / run["run_id"]
            console_dir = run_dir / "console"
            if not console_dir.exists():
                continue

            latencies = []
            file_based_latencies = []

            for log_file in console_dir.glob("case_*.log"):
                try:
                    # 方法1：使用文件时间戳计算真实执行时间（包含LLM调用）
                    import os

                    stat_info = os.stat(log_file)
                    file_birth_time = getattr(
                        stat_info, "st_birthtime", stat_info.st_ctime
                    )  # 文件创建时间
                    file_modify_time = stat_info.st_mtime  # 文件修改时间

                    # 计算真实执行时间（从创建到修改完成）
                    real_execution_time = file_modify_time - file_birth_time
                    if real_execution_time > 0:
                        file_based_latencies.append(real_execution_time)

                    # 方法2：仍然保留progress分析作为对比（但不作为主要数据）
                    with open(log_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    match = re.search(
                        r"=== DOLPHIN_VARIABLES_OUTPUT_START ===\n(.*?)\n=== DOLPHIN_VARIABLES_OUTPUT_END ===",
                        content,
                        re.DOTALL,
                    )
                    if match:
                        output_json = json.loads(match.group(1))
                        progress = output_json.get("_all_stages", [])
                        if progress:
                            valid_progress = [
                                p
                                for p in progress
                                if p.get("start_time") and p.get("end_time")
                            ]
                            if valid_progress:
                                # 计算progress步骤的时间（仅作参考）
                                step_latencies = [
                                    p["end_time"] - p["start_time"]
                                    for p in valid_progress
                                    if p["end_time"] - p["start_time"] >= 0
                                ]
                                if step_latencies:
                                    progress_total = sum(step_latencies)
                                    latencies.append(progress_total)

                    print(
                        f"File-based timing for {log_file.name}: {real_execution_time:.1f}s (vs progress: {progress_total:.3f}s)"
                        if "progress_total" in locals()
                        else f"File-based timing for {log_file.name}: {real_execution_time:.1f}s"
                    )

                except Exception as e:
                    print(f"Error analyzing {log_file}: {e}")

            # 优先使用文件时间戳数据（更准确）
            if file_based_latencies:
                avg_latency = sum(file_based_latencies) / len(file_based_latencies)
                max_latency = max(file_based_latencies)
                min_latency = min(file_based_latencies)
                total_latency = sum(file_based_latencies)

                # 计算P50和P99延迟
                import numpy as np

                sorted_latencies = sorted(file_based_latencies)
                p50_latency = np.median(sorted_latencies)
                p99_latency = (
                    np.percentile(sorted_latencies, 99)
                    if len(sorted_latencies) > 1
                    else max_latency
                )

                latency_table.append(
                    {
                        "Run ID": run["run_id"],
                        "Avg Latency": f"{avg_latency:.1f}s",
                        "Max Latency": f"{max_latency:.1f}s",
                        "Min Latency": f"{min_latency:.1f}s",
                        "P50 Latency": p50_latency,
                        "P99 Latency": p99_latency,
                        "Total Latency": f"{total_latency:.1f}s",
                        "Total Cases": len(file_based_latencies),
                        "Notes": f"Real execution time (including LLM calls)",
                    }
                )
            elif latencies:  # 备用：如果文件时间戳不可用，使用progress数据
                avg_latency = sum(latencies) / len(latencies)
                max_latency = max(latencies)
                min_latency = min(latencies)
                total_latency = sum(latencies)

                # 计算P50和P99延迟
                import numpy as np

                sorted_latencies = sorted(latencies)
                p50_latency = np.median(sorted_latencies)
                p99_latency = (
                    np.percentile(sorted_latencies, 99)
                    if len(sorted_latencies) > 1
                    else max_latency
                )

                latency_table.append(
                    {
                        "Run ID": run["run_id"],
                        "Avg Latency": f"{avg_latency:.3f}s",
                        "Max Latency": f"{max_latency:.3f}s",
                        "Min Latency": f"{min_latency:.3f}s",
                        "P50 Latency": p50_latency,
                        "P99 Latency": p99_latency,
                        "Total Latency": f"{total_latency:.3f}s",
                        "Total Cases": len(latencies),
                        "Notes": f"Progress step timing (internal only)",
                    }
                )

        # 如果没有数据，创建一个默认的空表
        if not latency_table:
            print("Warning: No latency data found in any run")
            return pd.DataFrame(
                columns=[
                    "Run ID",
                    "Avg Latency",
                    "Max Latency",
                    "Min Latency",
                    "P50 Latency",
                    "P99 Latency",
                    "Total Latency",
                    "Total Cases",
                    "Notes",
                ]
            )

        return pd.DataFrame(latency_table)

    def analyze_token_consumption(self):
        """分析 token 消耗情况 - 从日志中提取 LLM token 使用统计"""
        token_table = []
        for run in self.runs:
            run_dir = self.experiment_path / run["run_id"]
            console_dir = run_dir / "console"
            if not console_dir.exists():
                continue

            case_token_stats = []

            for log_file in console_dir.glob("case_*.log"):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    match = re.search(
                        r"=== DOLPHIN_VARIABLES_OUTPUT_START ===\n(.*?)\n=== DOLPHIN_VARIABLES_OUTPUT_END ===",
                        content,
                        re.DOTALL,
                    )
                    if match:
                        output_json = json.loads(match.group(1))
                        progress = output_json.get("_all_stages", [])

                        case_input_tokens = 0
                        case_output_tokens = 0
                        case_total_tokens = 0
                        llm_calls = 0

                        for stage in progress:
                            # 只统计 LLM 阶段的 token 消耗
                            if stage.get("stage") == "llm":
                                llm_calls += 1
                                input_tokens = stage.get("estimated_input_tokens", 0)
                                output_tokens = stage.get("estimated_output_tokens", 0)

                                case_input_tokens += input_tokens
                                case_output_tokens += output_tokens
                                case_total_tokens += input_tokens + output_tokens

                        case_token_stats.append(
                            {
                                "case_file": log_file.name,
                                "input_tokens": case_input_tokens,
                                "output_tokens": case_output_tokens,
                                "total_tokens": case_total_tokens,
                                "llm_calls": llm_calls,
                            }
                        )

                except Exception as e:
                    print(f"Error analyzing tokens for {log_file}: {e}")

            # 计算本 run 的总体 token 统计
            if case_token_stats:
                total_input = sum(case["input_tokens"] for case in case_token_stats)
                total_output = sum(case["output_tokens"] for case in case_token_stats)
                total_all = sum(case["total_tokens"] for case in case_token_stats)
                total_llm_calls = sum(case["llm_calls"] for case in case_token_stats)
                total_cases = len(case_token_stats)

                avg_input_per_case = total_input / total_cases if total_cases > 0 else 0
                avg_output_per_case = (
                    total_output / total_cases if total_cases > 0 else 0
                )
                avg_total_per_case = total_all / total_cases if total_cases > 0 else 0
                avg_llm_calls_per_case = (
                    total_llm_calls / total_cases if total_cases > 0 else 0
                )

                token_table.append(
                    {
                        "Run ID": run["run_id"],
                        "Total Cases": total_cases,
                        "Total Input Tokens": f"{total_input:,}",
                        "Total Output Tokens": f"{total_output:,}",
                        "Total All Tokens": f"{total_all:,}",
                        "Avg Input/Case": f"{avg_input_per_case:.0f}",
                        "Avg Output/Case": f"{avg_output_per_case:.0f}",
                        "Avg Total/Case": f"{avg_total_per_case:.0f}",
                        "Total LLM Calls": total_llm_calls,
                        "Avg LLM Calls/Case": f"{avg_llm_calls_per_case:.1f}",
                        "Input/Output Ratio": (
                            f"{total_input/total_output:.2f}"
                            if total_output > 0
                            else "N/A"
                        ),
                    }
                )

        # 如果没有数据，创建一个默认的空表
        if not token_table:
            print("Warning: No token consumption data found in any run")
            return pd.DataFrame(
                columns=[
                    "Run ID",
                    "Total Cases",
                    "Total Input Tokens",
                    "Total Output Tokens",
                    "Total All Tokens",
                    "Avg Input/Case",
                    "Avg Output/Case",
                    "Avg Total/Case",
                    "Total LLM Calls",
                    "Avg LLM Calls/Case",
                    "Input/Output Ratio",
                ]
            )

        return pd.DataFrame(token_table)

    def call_analyst_agent(self, data, query):
        """调用总体分析agent（已迁移到GeneralReporter）"""
        print("Warning: call_analyst_agent方法已迁移到GeneralReporter类")
        return None

    def generate_deep_analysis(
        self,
        config_df,
        accuracy_df,
        latency_df,
        token_df,
        factor_groups,
        call_chain_summary=None,
    ):
        """
        使用分析师agent生成深度分析

        Args:
            config_df: 配置对比数据
            accuracy_df: 准确率数据
            latency_df: 延迟数据
            token_df: Token 消耗数据
            factor_groups: 因子分组数据
            call_chain_summary: 调用链分析摘要

        Returns:
            深度分析结果字符串
        """
        # 准备数据摘要
        data_summary = "实验配置和结果摘要：\n"

        # 配置信息
        data_summary += "\n配置对比：\n"
        for _, row in config_df.iterrows():
            data_summary += f"- {row['Run ID']}: entrypoint={row['Entrypoint']}, model={row['Model Name']}, variables={row['Variables'][:50]}...\n"

        # 准确率信息
        data_summary += "\n准确率结果：\n"
        for _, row in accuracy_df.iterrows():
            data_summary += f"- {row['Run ID']}: {row['Accuracy']} ({row['Correct']}/{row['Total Questions']})\n"

        # 延迟信息
        data_summary += "\n执行延迟：\n"
        for _, row in latency_df.iterrows():
            data_summary += f"- {row['Run ID']}: 平均{row['Avg Latency']}, 最大{row['Max Latency']}, 最小{row['Min Latency']}\n"

        # Token 消耗信息
        data_summary += "\nToken消耗：\n"
        for _, row in token_df.iterrows():
            data_summary += f"- {row['Run ID']}: 总计{row['Total All Tokens']} tokens, 平均{row['Avg Total/Case']}/case, LLM调用{row['Avg LLM Calls/Case']}/case\n"

        # 因子分组信息
        data_summary += "\n按因子分组：\n"
        for factor_name, factor_values in factor_groups.items():
            data_summary += f"- {factor_name}:\n"
            for value_name, runs_data in factor_values.items():
                accuracies = [r["accuracy"] for r in runs_data]
                avg_acc = sum(accuracies) / len(accuracies)
                data_summary += f"  {value_name}: 平均准确率{avg_acc:.2%}, 共{len(runs_data)}次运行\n"

        # 调用链分析信息
        if call_chain_summary:
            data_summary += "\n调用链分析：\n"
            global_summary = call_chain_summary.get("global_summary", {})

            data_summary += f"- 总运行数: {global_summary.get('total_runs', 0)}\n"
            data_summary += f"- 总案例数: {global_summary.get('total_cases', 0)}\n"
            data_summary += f"- 平均交互轮数: {global_summary.get('avg_interaction_rounds_global', 0):.1f}\n"

            # 最常用工具
            most_used_tools = global_summary.get("most_used_tools_global", {})
            if most_used_tools:
                data_summary += f"- 最常用工具: {', '.join(f'{tool}({count}次)' for tool, count in list(most_used_tools.items())[:3])}\n"

            # 交互轮数分布
            interaction_dist = global_summary.get("interaction_distribution", {})
            if interaction_dist:
                data_summary += f"- 交互轮数分布: 1轮{interaction_dist.get('cases_with_1_round', 0)}个, 2-4轮{interaction_dist.get('cases_with_2_4_rounds', 0)}个, 5+轮{interaction_dist.get('cases_with_5_plus_rounds', 0)}个\n"

            # 按run的调用链摘要
            run_summaries = call_chain_summary.get("run_summaries", [])
            for run_summary in run_summaries[:3]:  # 只显示前3个
                data_summary += f"  {run_summary['run_id']}: 平均{run_summary['avg_interaction_rounds']:.1f}轮, 成功{run_summary['successful_cases']}个案例\n"

        # 准备实验数据结构供GeneralAnalyzer使用
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
                "Latency P50": (
                    lat_row.get("P50 Latency", 0) if lat_row is not None else 0
                ),
                "Total Tokens": (
                    tok_row.get("Total All Tokens", 0) if tok_row is not None else 0
                ),
                "Tool Calls": (
                    tok_row.get("Total Tool Calls", 0) if tok_row is not None else 0
                ),
                "Interactions": (
                    call_chain_summary.get("run_summaries", {})
                    .get(run_id, {})
                    .get("avg_interaction_rounds", 0)
                    if call_chain_summary
                    else 0
                ),
            }
            experiments.append(exp_data)

        # 计算汇总统计
        accuracies = [e["Accuracy"] for e in experiments]
        latencies = [e["Latency P50"] for e in experiments]
        tokens = [e["Total Tokens"] for e in experiments]
        tool_calls = [e["Tool Calls"] for e in experiments]
        interactions = [e["Interactions"] for e in experiments]

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

        # 已迁移到GeneralReporter
        print("Warning: generate_deep_analysis方法已迁移到GeneralReporter类")
        return "深度分析功能已迁移到新的架构中。"

    def generate_report(self):
        """生成分析报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"{self.experiment_name}_analysis_{timestamp}"

        # 分析数据
        config_df = self.analyze_configs()
        accuracy_df = self.analyze_accuracy()
        factor_groups = self.analyze_by_factors()
        individual_variables = self.analyze_individual_variables()
        run_labels = self.generate_run_labels()
        results_df = self.create_detailed_comparison()
        consecutive_patterns = self.detect_consecutive_errors(results_df)
        latency_df = self.analyze_latency()
        token_df = self.analyze_token_consumption()
        impact_df = self.analyze_config_impact(config_df, accuracy_df)
        call_chain_summary = self.analyze_all_call_chains()

        # 生成深度分析
        print("正在调用分析师agent进行深度分析...")
        deep_analysis = self.generate_deep_analysis(
            config_df,
            accuracy_df,
            latency_df,
            token_df,
            factor_groups,
            call_chain_summary,
        )

        # 日志分析
        log_analyses = {}
        for run in self.runs:
            run_dir = self.experiment_path / run["run_id"]
            log_analyses[run["run_id"]] = self.analyze_case_logs(run_dir)

        # 生成文本报告
        report_path = self.reports_dir / f"{report_name}.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"实验分析报告\n")
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
            if hasattr(self, "run_label_legend"):
                for code, meaning in sorted(self.run_label_legend.items()):
                    f.write(f"  {code} = {meaning}\n")

            # 显示动态检测到的变化变量
            if hasattr(self, "varying_variables") and self.varying_variables:
                f.write(f"\n本次实验检测到的变化变量：\n")
                for var_name, values in self.varying_variables.items():
                    f.write(f"  {var_name}: {values}\n")
                    if (
                        hasattr(self, "dynamic_rules")
                        and var_name in self.dynamic_rules
                    ):
                        encoding_info = ", ".join(
                            [
                                f"{v}→{c}"
                                for v, c in self.dynamic_rules[var_name].items()
                            ]
                        )
                        f.write(f"    编码规则: {encoding_info}\n")
            f.write("\n")

            # 1.1 配置因子对准确率的影响分析
            f.write("1.1 配置因子对准确率的影响分析\n")
            f.write(impact_df.to_string(index=False))
            f.write("\n")

            # 2. 准确率对比
            f.write("2. 准确率对比\n")
            f.write("-" * 30 + "\n")
            # 创建带标识符的准确率表格
            accuracy_df_labeled = accuracy_df.copy()
            accuracy_df_labeled["Run ID"] = accuracy_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(accuracy_df_labeled.to_string(index=False))
            f.write("\n\n")

            # 3. 按配置因子分组的准确率对比
            f.write("3. 按配置因子分组的准确率对比\n")
            f.write("-" * 30 + "\n")

            # 先显示模型因子的分组对比
            for factor_name, factor_groups_data in factor_groups.items():
                if factor_name not in ["Variables"]:  # 先处理非Variables的因子
                    f.write(f"\n按 {factor_name} 分组:\n")
                    for factor_value, runs_data in factor_groups_data.items():
                        f.write(f"\n  {factor_value}:\n")
                        for run_data in runs_data:
                            run_id = run_data["run_id"]
                            run_label = run_labels.get(run_id, run_id)
                            f.write(
                                f"    {run_label}: {run_data['accuracy']:.2%} ({run_data['correct']}/{run_data['total']}) 延迟{run_data['avg_latency']:.1f}s tokens{run_data['avg_tokens_per_case']:.0f}/case\n"
                            )

                        if len(runs_data) > 1:
                            accuracies = [r["accuracy"] for r in runs_data]
                            latencies = [r["avg_latency"] for r in runs_data]
                            tokens_per_case = [
                                r["avg_tokens_per_case"] for r in runs_data
                            ]
                            llm_calls = [r["avg_llm_calls"] for r in runs_data]

                            avg_acc = sum(accuracies) / len(accuracies)
                            avg_latency = sum(latencies) / len(latencies)
                            avg_tokens = sum(tokens_per_case) / len(tokens_per_case)
                            avg_llm_calls_val = sum(llm_calls) / len(llm_calls)

                            # 计算标准差和方差
                            import numpy as np

                            std_acc = np.std(accuracies) if len(accuracies) > 1 else 0
                            var_acc = np.var(accuracies) if len(accuracies) > 1 else 0
                            std_latency = np.std(latencies) if len(latencies) > 1 else 0
                            var_latency = np.var(latencies) if len(latencies) > 1 else 0
                            std_tokens = (
                                np.std(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )
                            var_tokens = (
                                np.var(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )

                            f.write(
                                f"    平均准确率: {avg_acc:.2%} (±{std_acc:.2%}, 方差:{var_acc:.6f})\n"
                            )
                            f.write(
                                f"    平均延迟: {avg_latency:.1f}s (±{std_latency:.1f}s, 方差:{var_latency:.2f})\n"
                            )
                            f.write(
                                f"    平均tokens/case: {avg_tokens:.0f} (±{std_tokens:.0f}, 方差:{var_tokens:.0f})\n"
                            )
                            f.write(f"    平均LLM调用/case: {avg_llm_calls_val:.1f}\n")
                    f.write("\n")

            # 单独处理Variables - 按单个变量分别分析
            f.write("按单个变量分组分析:\n")
            for var_name, var_groups_data in individual_variables.items():
                f.write(f"\n按 {var_name} 分组:\n")
                for var_value, runs_data in var_groups_data.items():
                    if var_value != "Unknown":  # 跳过Unknown值
                        f.write(f"\n  {var_name}={var_value}:\n")
                        for run_data in runs_data:
                            run_id = run_data["run_id"]
                            run_label = run_labels.get(run_id, run_id)
                            f.write(
                                f"    {run_label}: {run_data['accuracy']:.2%} ({run_data['correct']}/{run_data['total']}) 延迟{run_data['avg_latency']:.1f}s tokens{run_data['avg_tokens_per_case']:.0f}/case\n"
                            )

                        if len(runs_data) > 1:
                            accuracies = [r["accuracy"] for r in runs_data]
                            latencies = [r["avg_latency"] for r in runs_data]
                            tokens_per_case = [
                                r["avg_tokens_per_case"] for r in runs_data
                            ]
                            llm_calls = [r["avg_llm_calls"] for r in runs_data]

                            avg_acc = sum(accuracies) / len(accuracies)
                            avg_latency = sum(latencies) / len(latencies)
                            avg_tokens = sum(tokens_per_case) / len(tokens_per_case)
                            avg_llm_calls_val = sum(llm_calls) / len(llm_calls)

                            # 计算标准差和方差
                            import numpy as np

                            std_acc = np.std(accuracies) if len(accuracies) > 1 else 0
                            var_acc = np.var(accuracies) if len(accuracies) > 1 else 0
                            std_latency = np.std(latencies) if len(latencies) > 1 else 0
                            var_latency = np.var(latencies) if len(latencies) > 1 else 0
                            std_tokens = (
                                np.std(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )
                            var_tokens = (
                                np.var(tokens_per_case)
                                if len(tokens_per_case) > 1
                                else 0
                            )

                            f.write(
                                f"    平均准确率: {avg_acc:.2%} (±{std_acc:.2%}, 方差:{var_acc:.6f})\n"
                            )
                            f.write(
                                f"    平均延迟: {avg_latency:.1f}s (±{std_latency:.1f}s, 方差:{var_latency:.2f})\n"
                            )
                            f.write(
                                f"    平均tokens/case: {avg_tokens:.0f} (±{std_tokens:.0f}, 方差:{var_tokens:.0f})\n"
                            )
                            f.write(f"    平均LLM调用/case: {avg_llm_calls_val:.1f}\n")
                f.write("\n")
            f.write("\n")

            # 4. 连续错误模式分析
            f.write("4. 连续错误模式分析\n")
            f.write("-" * 30 + "\n\n")
            # 计算最长的run_label长度用于对齐
            max_label_len = max(
                len(run_labels.get(run_id, run_id))
                for run_id in consecutive_patterns.keys()
            )
            for run_id, patterns in consecutive_patterns.items():
                run_label = run_labels.get(run_id, run_id)
                if patterns:
                    f.write(f"{run_label:{max_label_len}} 发现连续错误模式:\n")
                    for pattern in patterns:
                        f.write(
                            f"{' ' * (max_label_len + 2)}题目 {pattern[0]}-{pattern[-1]} ({len(pattern)}个连续错误)\n"
                        )
                else:
                    f.write(f"{run_label:{max_label_len}}: 无明显连续错误模式\n")

            # 5. 延迟分析
            f.write("\n5. 延迟分析\n")
            f.write("-" * 30 + "\n")
            # 创建带标识符的延迟表格
            latency_df_labeled = latency_df.copy()
            latency_df_labeled["Run ID"] = latency_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(latency_df_labeled.to_string(index=False))
            f.write("\n")

            # 5.1 Token 消耗分析
            f.write("\n5.1 Token 消耗分析\n")
            f.write("-" * 30 + "\n")
            # 创建带标识符的token表格
            token_df_labeled = token_df.copy()
            token_df_labeled["Run ID"] = token_df_labeled["Run ID"].apply(
                lambda x: run_labels.get(x, x)
            )
            f.write(token_df_labeled.to_string(index=False))
            f.write("\n")

            # 6. 调用链和工具使用分析
            f.write("\n6. 调用链和工具使用分析\n")
            f.write("-" * 30 + "\n")
            if call_chain_summary:
                global_summary = call_chain_summary.get("global_summary", {})
                run_summaries = call_chain_summary.get("run_summaries", [])

                f.write("7.1 全局调用链统计：\n")
                f.write(f"  总运行数: {global_summary.get('total_runs', 0)}\n")
                f.write(f"  总案例数: {global_summary.get('total_cases', 0)}\n")
                f.write(
                    f"  平均交互轮数: {global_summary.get('avg_interaction_rounds_global', 0):.2f}\n"
                )

                # 工具使用统计
                most_used_tools = global_summary.get("most_used_tools_global", {})
                if most_used_tools:
                    f.write(f"\n  最常用工具排名:\n")
                    for i, (tool, count) in enumerate(most_used_tools.items(), 1):
                        f.write(f"    {i}. {tool}: {count}次调用\n")

                # 交互轮数分布
                interaction_dist = global_summary.get("interaction_distribution", {})
                if interaction_dist:
                    f.write(f"\n  交互轮数分布:\n")
                    f.write(
                        f"    1轮完成: {interaction_dist.get('cases_with_1_round', 0)}个案例\n"
                    )
                    f.write(
                        f"    2-4轮完成: {interaction_dist.get('cases_with_2_4_rounds', 0)}个案例\n"
                    )
                    f.write(
                        f"    5轮以上: {interaction_dist.get('cases_with_5_plus_rounds', 0)}个案例\n"
                    )
                    f.write(f"    最少轮数: {interaction_dist.get('min_rounds', 0)}\n")
                    f.write(f"    最多轮数: {interaction_dist.get('max_rounds', 0)}\n")
                    f.write(
                        f"    中位数轮数: {interaction_dist.get('median_rounds', 0)}\n"
                    )

                f.write(f"\n7.2 按运行分组的调用链分析:\n")
                for run_summary in run_summaries:
                    run_id = run_summary["run_id"]
                    run_label = run_labels.get(run_id, run_id)
                    f.write(f"\n  {run_label}:\n")
                    f.write(f"    案例总数: {run_summary['total_cases']}\n")
                    f.write(f"    成功案例: {run_summary['successful_cases']}\n")
                    f.write(f"    失败案例: {run_summary['failed_cases']}\n")
                    f.write(
                        f"    平均交互轮数: {run_summary['avg_interaction_rounds']:.2f}\n"
                    )
                    f.write(f"    平均LLM轮数: {run_summary['avg_llm_rounds']:.2f}\n")
                    f.write(
                        f"    平均技能轮数: {run_summary['avg_skill_rounds']:.2f}\n"
                    )
                    f.write(f"    平均总步数: {run_summary['avg_total_steps']:.1f}\n")

                    # 最常用工具
                    most_used_tools_run = run_summary.get("most_used_tools", {})
                    if most_used_tools_run:
                        f.write(
                            f"    最常用工具: {', '.join(f'{tool}({count}次)' for tool, count in most_used_tools_run.items())}\n"
                        )
            else:
                f.write("调用链分析数据不可用\n")

            # 7. 日志错误分析
            f.write("\n7. 日志错误分析\n")
            f.write("-" * 30 + "\n")
            for run_id, log_analysis in log_analyses.items():
                run_label = run_labels.get(run_id, run_id)
                f.write(f"\n{run_label} 日志分析:\n")
                error_stats = log_analysis["error_stats"]
                warning_stats = log_analysis["warning_stats"]
                file_size_stats = log_analysis["file_size_stats"]

                f.write(f"  总日志文件数: {len(file_size_stats)}\n")
                f.write(f"  总错误数: {sum(error_stats.values())}\n")
                f.write(f"  总警告数: {sum(warning_stats.values())}\n")

                if error_stats:
                    f.write(f"  常见错误类型 (前5):\n")
                    for error, count in sorted(
                        error_stats.items(), key=lambda x: x[1], reverse=True
                    )[:5]:
                        f.write(f"    {count}次: {error}\n")

                if file_size_stats:
                    avg_size = sum(size for _, size in file_size_stats) / len(
                        file_size_stats
                    )
                    small_files = [
                        (name, size) for name, size in file_size_stats if size < 100
                    ]
                    f.write(f"  平均日志文件大小: {avg_size:.0f} bytes\n")
                    if small_files:
                        f.write(
                            f"  异常小的日志文件 (<100 bytes): {len(small_files)}个\n"
                        )

            # 8. 实验健康状态评估
            f.write("\n8. 实验健康状态评估\n")
            f.write("-" * 30 + "\n")

            # 识别异常run
            anomalous_runs = []
            for run_id, log_analysis in log_analyses.items():
                error_count = sum(log_analysis["error_stats"].values())
                consecutive_error_count = sum(
                    len(pattern) for pattern in consecutive_patterns.get(run_id, [])
                )

                if error_count > 50 or consecutive_error_count > 20:
                    anomalous_runs.append(
                        {
                            "run_id": run_id,
                            "error_count": error_count,
                            "consecutive_errors": consecutive_error_count,
                            "status": "CRITICAL" if error_count > 100 else "WARNING",
                        }
                    )

            if anomalous_runs:
                f.write("发现异常运行:\n")
                for anomaly in anomalous_runs:
                    run_id = anomaly["run_id"]
                    run_label = run_labels.get(run_id, run_id)
                    f.write(
                        f"  {run_label}: {anomaly['status']} - {anomaly['error_count']}个错误, {anomaly['consecutive_errors']}个连续错误\n"
                    )

                    # 添加具体的异常分析建议
                    if anomaly["error_count"] > 100:
                        f.write(
                            f"    建议: 检查{run_label}的系统日志，可能存在JSON解析、网络连接或API调用问题\n"
                        )
                    if anomaly["consecutive_errors"] > 50:
                        f.write(
                            f"    建议: {run_label}可能在某个时间点后系统性失败，建议重新运行\n"
                        )
            else:
                f.write("所有运行状态正常\n")

            # 9. 方差分析汇总
            f.write("\n9. 方差分析汇总\n")
            f.write("-" * 30 + "\n")
            f.write("各对比组的准确率方差统计:\n\n")

            # 汇总所有对比组的方差数据
            variance_summary = []

            # 处理配置因子分组
            for factor_name, factor_groups_data in factor_groups.items():
                if factor_name not in ["Variables"]:  # 先处理非Variables的因子
                    for factor_value, runs_data in factor_groups_data.items():
                        if len(runs_data) > 1:
                            accuracies = [r["accuracy"] for r in runs_data]
                            import numpy as np

                            var_acc = np.var(accuracies)
                            std_acc = np.std(accuracies)
                            avg_acc = sum(accuracies) / len(accuracies)
                            variance_summary.append(
                                {
                                    "factor": factor_name,
                                    "value": factor_value,
                                    "count": len(runs_data),
                                    "avg_accuracy": avg_acc,
                                    "variance": var_acc,
                                    "std_dev": std_acc,
                                }
                            )

            # 处理单个变量分组
            for var_name, var_groups_data in individual_variables.items():
                for var_value, runs_data in var_groups_data.items():
                    if var_value != "Unknown" and len(runs_data) > 1:
                        accuracies = [r["accuracy"] for r in runs_data]
                        import numpy as np

                        var_acc = np.var(accuracies)
                        std_acc = np.std(accuracies)
                        avg_acc = sum(accuracies) / len(accuracies)
                        variance_summary.append(
                            {
                                "factor": f"变量 {var_name}",
                                "value": f"{var_name}={var_value}",
                                "count": len(runs_data),
                                "avg_accuracy": avg_acc,
                                "variance": var_acc,
                                "std_dev": std_acc,
                            }
                        )

            # 按对比组分组，然后按方差排序输出
            from collections import defaultdict

            grouped_by_factor = defaultdict(list)
            for item in variance_summary:
                grouped_by_factor[item["factor"]].append(item)

            # 对每组内部按方差排序
            for factor in grouped_by_factor:
                grouped_by_factor[factor].sort(
                    key=lambda x: x["variance"], reverse=True
                )

            # 按组的最大方差排序整体组
            sorted_factors = sorted(
                grouped_by_factor.keys(),
                key=lambda f: max(item["variance"] for item in grouped_by_factor[f]),
                reverse=True,
            )

            f.write("按方差大小排序的对比组:\n")
            f.write(
                f"{'对比组':<30} {'组别':<40} {'样本数':<8} {'平均准确率':<12} {'方差':<12} {'标准差':<8}\n"
            )
            f.write("-" * 120 + "\n")

            for factor in sorted_factors:
                for i, item in enumerate(grouped_by_factor[factor]):
                    factor_display = (
                        item["factor"] if i == 0 else ""
                    )  # 只在第一行显示对比组名
                    value_display = (
                        item["value"][:39] + "..."
                        if len(item["value"]) > 39
                        else item["value"]
                    )
                    f.write(
                        f"{factor_display:<30} {value_display:<40} {item['count']:<8} {item['avg_accuracy']:<12.2%} {item['variance']:<12.6f} {item['std_dev']:<8.2%}\n"
                    )
                # 在每组之间加分隔线
                if factor != sorted_factors[-1]:
                    f.write("-" * 120 + "\n")

            if not variance_summary:
                f.write("没有找到包含多个样本的对比组。\n")

            # 找出方差最大和最小的组
            if len(variance_summary) > 1:
                max_var_group = variance_summary[0]
                min_var_group = variance_summary[-1]
                f.write(f"\n方差分析要点:\n")
                f.write(
                    f"• 最不稳定组: {max_var_group['factor']} - {max_var_group['value']} (方差: {max_var_group['variance']:.6f})\n"
                )
                f.write(
                    f"• 最稳定组: {min_var_group['factor']} - {min_var_group['value']} (方差: {min_var_group['variance']:.6f})\n"
                )
                f.write(
                    f"• 稳定性差异: {(max_var_group['variance'] - min_var_group['variance']):.6f}\n"
                )

            f.write("\n")
            f.write("10. AI深度分析结论\n")
            f.write("-" * 30 + "\n")
            if deep_analysis:
                f.write(deep_analysis)
                f.write("\n\n")
            else:
                f.write("深度分析不可用，显示基础分析结论：\n")

        print(f"✓ 分析报告已生成:")
        print(f"  文本报告: {report_path}")
        if deep_analysis:
            print(f"  ✓ 包含AI深度分析")
        else:
            print(f"  ⚠️ AI深度分析不可用")

        return report_path

    def debug_case(self, experiment_name, run_name, case_num):
        """智能体执行分析（已迁移到ExecutionAnalyzer）"""
        print("Warning: debug_case方法已迁移到ExecutionAnalyzer类")
        return None

    # ==========================================
    # 以下方法已迁移到专门的模块中：
    # - GeneralAnalyzer: 负责总体分析功能
    # - AnalysisDebugger: 负责调试分析功能
    #
    # 这些方法保留用于向后兼容，建议使用新的模块化接口
    # ==========================================

    def _preprocess_experiment_log(self, experiment_name, run_name, case_num):
        """预处理实验日志，提取Final result:之前的内容并保存到临时文件 [已迁移到AnalysisDebugger]"""
        import tempfile
        import re

        # 使用新的日志文件路径格式
        # console/case_XXX.log
        case_num_padded = f"{int(case_num):03d}"
        log_file = (
            self.root_dir
            / "experiments"
            / "env"
            / experiment_name
            / run_name
            / "console"
            / f"case_{case_num_padded}.log"
        )

        # 如果新路径不存在，尝试旧路径格式
        if not log_file.exists():
            # 提取run编号，去掉前导零
            run_num = run_name.split("_")[-1].lstrip("0") or "0"
            # 去掉case编号的前导零
            case_num_clean = case_num.lstrip("0") or "0"
            log_file = (
                self.root_dir
                / "experiments"
                / "env"
                / experiment_name
                / run_name
                / "log"
                / f"experiment_run_{run_num}_case_{case_num_clean}.log"
            )

        if not log_file.exists():
            print(f"错误: 日志文件不存在: {log_file}")
            return None

        try:
            # 读取原始日志（完整内容）
            with open(log_file, "r", encoding="utf-8") as f:
                full_content = f.read()

            # 截取到Final result:之前的主要轨迹内容，避免变量dump干扰
            content = full_content
            final_result_pos = content.find("Final result:")
            if final_result_pos != -1:
                content = content[:final_result_pos]

            content = content.strip()

            # 从完整日志中尝试提取关键信息，作为META附加到末尾，便于debug分析
            meta_lines = []
            meta_lines.append("\n\n==== META (extracted) ====")

            # 1) 提取最终答案文本（如存在）
            try:
                # 匹配 Final result: {... 'answer': '...'}
                ans_match = re.search(
                    r"Final result:\s*\{.*?'answer':\s*'(.*?)',\s*'think'",
                    full_content,
                    re.DOTALL,
                )
                if ans_match:
                    # 清洗转义和ANSI
                    raw_answer = ans_match.group(1)
                    clean_answer = raw_answer.replace("\\n", "\n")
                    meta_lines.append("[predicted_answer]\n" + clean_answer.strip())
            except Exception:
                pass

            # 2) 提取最近一次 executeSQL 的 SQL 文本（如存在）
            try:
                # 去除ANSI颜色，避免匹配失败
                ansi_escape = re.compile(r"\x1B(?:[@-Z\\\\-_]|\[[0-?]*[ -/]*[@-~])")
                no_ansi = ansi_escape.sub("", full_content)

                # 匹配最后一个\"sql\": "..."
                sql_matches = list(
                    re.finditer(r'"sql"\s*:\s*"(.*?)"', no_ansi, re.DOTALL)
                )
                if sql_matches:
                    last_sql = sql_matches[-1].group(1)
                    last_sql = last_sql.replace("\\n", "\n")
                    meta_lines.append("[predicted_sql]\n" + last_sql.strip())
            except Exception:
                pass

            # 3) 提取Custom arguments（如存在）
            try:
                cust_match = re.search(
                    r"Custom arguments:\s*(\{.*?\})", full_content, re.DOTALL
                )
                if cust_match:
                    meta_lines.append(
                        "[custom_arguments]\n" + cust_match.group(1).strip()
                    )
            except Exception:
                pass

            # 4) 若没有任何meta，移除占位
            if meta_lines and len(meta_lines) > 1:
                content = content + "\n" + "\n".join(meta_lines)

            # 创建临时文件
            temp_file = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".log", delete=False
            )
            temp_file.write(content)
            temp_file.close()

            return Path(temp_file.name)

        except Exception as e:
            print(f"错误: 预处理日志文件失败: {e}")
            return None

    def _get_experiment_log(self, experiment_name, run_name, case_num):
        """获取实验日志内容，截止到Final result:之前"""
        # 使用新的日志文件路径格式
        # console/case_XXX.log
        case_num_padded = f"{int(case_num):03d}"
        log_file = (
            self.root_dir
            / "experiments"
            / "env"
            / experiment_name
            / run_name
            / "console"
            / f"case_{case_num_padded}.log"
        )

        # 如果新路径不存在，尝试旧路径格式
        if not log_file.exists():
            # 提取run编号，去掉前导零
            run_num = run_name.split("_")[-1].lstrip("0") or "0"
            # 去掉case编号的前导零
            case_num_clean = case_num.lstrip("0") or "0"
            log_file = (
                self.root_dir
                / "experiments"
                / "env"
                / experiment_name
                / run_name
                / "log"
                / f"experiment_run_{run_num}_case_{case_num_clean}.log"
            )

        if not log_file.exists():
            print(f"错误: 日志文件不存在: {log_file}")
            return None

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 截取到Final result:之前的内容
            final_result_pos = content.find("Final result:")
            if final_result_pos != -1:
                content = content[:final_result_pos]

            return content.strip()
        except Exception as e:
            print(f"错误: 读取日志文件失败: {e}")
            return None

    # _get_benchmark_data method moved to BaseAnalyzer

    def _run_debug_analysis(self, exp_log_path, benchmark):
        """调用analysis.dph进行分析"""
        debug_log_file = None
        try:
            debug_file = Path(__file__).parent / "dolphins" / "analysis.dph"
            if not debug_file.exists():
                print(f"错误: analysis.dph文件不存在: {debug_file}")
                return None

            # 构建dolphin命令
            cmd_parts = [
                str(self.dolphin_cmd),
                "--folder",
                Path(__file__).parent / "dolphins",
                "--agent",
                "analysis",
                "--exp_log_path",
                str(exp_log_path),
                "--benchmark",
                json.dumps(benchmark, ensure_ascii=False),
                "--output-variables",
                "debug_result",
            ]

            # 创建临时日志文件
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            reports_dir = Path(__file__).parent.parent / "reports"
            reports_dir.mkdir(exist_ok=True)
            debug_log_file = reports_dir / f"dolphin_debug_{ts}.log"

            print("🔧 执行调试分析...")

            # 使用与run_experiment相同的方式调用
            with open(debug_log_file, "w", encoding="utf-8") as log_f:
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
                    print(f"Warning: Failed to run debug command: {e}")
                    return None

            # Wait a moment for log file to be written completely
            import time

            time.sleep(0.1)

            if exit_code != 0:
                print(f"错误: 调试分析执行失败，退出码: {exit_code}")
                return None

            # 读取日志文件并提取variables
            try:
                with open(debug_log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()

                # 提取debug_result
                extracted = self._extract_debug_result(log_content)
                if extracted:
                    # 成功提取结果，清理临时文件
                    try:
                        debug_log_file.unlink(missing_ok=True)
                    except:
                        pass
                    return extracted

                print("Warning: Failed to extract debug_result from log")
                return "调试分析完成，但无法提取调试结果。"

            except Exception as e:
                print(f"Warning: Failed to read debug log file: {e}")
                return None

        except Exception as e:
            print(f"错误: 执行调试分析失败: {e}")
            return None
        finally:
            # 确保临时日志文件被清理
            if debug_log_file and debug_log_file.exists():
                try:
                    debug_log_file.unlink(missing_ok=True)
                except:
                    pass

    def _extract_debug_result(self, log_content: str):
        """直接从DOLPHIN_VARIABLES_OUTPUT标记中提取debug_result变量。

        使用与experiments/bin/run中parse_variables_from_log相同的逻辑。
        """
        if not log_content:
            return None

        try:
            # Find the variables output section
            start_marker = "=== DOLPHIN_VARIABLES_OUTPUT_START ==="
            end_marker = "=== DOLPHIN_VARIABLES_OUTPUT_END ==="

            # 使用基类的通用方法提取变量输出部分
            variables_section = self._extract_result_from_log(
                log_content, start_marker, end_marker
            )
            if not variables_section:
                return None

            # Parse JSON
            variables = json.loads(variables_section)

            # Extract debug_result from variables
            debug_result = variables.get("debug_result").get("answer")
            if isinstance(debug_result, str) and debug_result.strip():
                return debug_result.strip()
            return None

        except Exception as e:
            print(f"Warning: Failed to extract debug_result from log: {e}")
            return None


def main():
    parser = argparse.ArgumentParser(description="实验结果分析工具")
    parser.add_argument(
        "experiment_path", help="实验目录路径 (experiments/env下的目录)"
    )
    parser.add_argument("--output-dir", help="输出目录 (默认: experiments/reports)")

    # 添加 --general 和 --analysis 选项
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--general", action="store_true", help="执行总体分析模式（使用general.dph）"
    )
    mode_group.add_argument(
        "--analysis", action="store_true", help="执行调试分析模式（使用analysis.dph）"
    )

    # 用于调试分析的参数
    parser.add_argument("--run", help="指定run名称（用于--analysis模式）")
    parser.add_argument("--case", help="指定case编号（用于--analysis模式）")

    args = parser.parse_args()

    # 构建完整路径
    if not os.path.isabs(args.experiment_path):
        # 相对路径，基于当前脚本位置构建
        script_dir = Path(__file__).parent.parent
        # 如果参数已经包含了experiments/env前缀，直接使用
        if args.experiment_path.startswith("experiments/env/"):
            experiment_name = args.experiment_path.split("experiments/env/")[-1]
            experiment_path = script_dir / "env" / experiment_name
        else:
            experiment_path = script_dir / "env" / args.experiment_path
    else:
        experiment_path = Path(args.experiment_path)

    if not experiment_path.exists():
        print(f"错误: 实验路径不存在: {experiment_path}")
        return 1

    # 创建分析器
    analyzer = ExperimentAnalyzer(experiment_path)

    # 根据模式选择不同的执行逻辑
    if args.analysis or (not args.general and (args.run or args.case)):
        # 调试分析模式（默认为兼容性）
        if not args.run or not args.case:
            print("错误: --analysis模式需要指定 --run 和 --case 参数")
            return 1

        experiment_name = experiment_path.name
        debug_result = analyzer.debug_case(experiment_name, args.run, args.case)
        if debug_result:
            print("\n" + "=" * 60)
            print("📋 调试分析结果:")
            print("=" * 60)
            print(debug_result)
            print("=" * 60)
            return 0
        else:
            print("错误: 调试分析失败")
            return 1
    else:
        # 总体分析模式（默认）
        if not analyzer.load_experiment_data():
            print("错误: 无法加载实验数据")
            return 1

        analyzer.generate_report()
        return 0


if __name__ == "__main__":
    exit(main())
