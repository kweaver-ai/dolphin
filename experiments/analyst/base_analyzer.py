#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BaseAnalyzer: 所有分析器的基类

提供公共的数据访问和处理方法：
- benchmark数据获取
- 知识文件加载
- 结果提取
- 通用初始化
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List


class BaseAnalyzer:
    """分析器基类"""

    def __init__(self, data_loader):
        """
        初始化分析器基类

        Args:
            data_loader: ExperimentDataLoader实例
        """
        self.data_loader = data_loader
        self.experiment_path = data_loader.experiment_path
        self.experiment_name = data_loader.experiment_name
        self.root_dir = data_loader.root_dir
        self.dolphin_cmd = data_loader.dolphin_cmd
        self.reports_dir = data_loader.reports_dir

    def _get_benchmark_data(
        self,
        case_num: str,
        search_paths: Optional[List[Path]] = None,
        id_fields: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取benchmark数据 - 通用实现

        Args:
            case_num: case编号
            search_paths: 自定义搜索路径列表（可选，默认使用标准路径）
            id_fields: 用于匹配case的ID字段名列表（可选，默认为['test_id', 'id', 'question_id']）

        Returns:
            benchmark数据字典，如果找不到返回None
        """
        # 默认搜索路径
        if search_paths is None:
            case_num_padded = self._format_case_num(case_num)
            case_num_clean = case_num.lstrip("0") or "0"

            search_paths = [
                # 实验目录下的benchmark文件
                self.experiment_path / "benchmark" / f"test_{case_num_padded}.json",
                self.experiment_path / "benchmark" / f"test_{case_num_clean}.json",
                self.experiment_path / "tests" / f"test_{case_num_clean}.json",
                self.experiment_path / "tests" / f"case_{case_num_clean}.json",
                self.experiment_path / "benchmark.json",
                # 全局benchmark数据目录
                self.root_dir
                / "experiments"
                / "benchmark"
                / "data"
                / "watsons"
                / "benchmark.json",
                self.root_dir
                / "experiments"
                / "benchmark"
                / "data"
                / "bird_dev"
                / "benchmark.json",
                # 相对于当前文件的benchmark目录
                Path(__file__).parent.parent
                / "benchmark"
                / "data"
                / "watsons"
                / "benchmark.json",
            ]

        # 默认ID字段
        if id_fields is None:
            id_fields = ["test_id", "id", "question_id"]

        # 遍历搜索路径
        for benchmark_file in search_paths:
            if not benchmark_file.exists():
                continue

            try:
                with open(benchmark_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 处理不同数据格式
                if isinstance(data, dict):
                    return data
                elif isinstance(data, list):
                    case_num_int = int(case_num.lstrip("0") or "0")
                    # 尝试不同的ID字段匹配
                    for item in data:
                        for id_field in id_fields:
                            if (
                                item.get(id_field) == case_num_int
                                or item.get(id_field) == case_num_int - 1
                            ):
                                return item
                    # 如果没有找到匹配的item，继续搜索下一个文件
                    continue

            except Exception as e:
                print(f"读取benchmark文件失败 {benchmark_file}: {e}")
                continue

        print(f"错误: 未找到case {case_num}的benchmark数据")
        return None

    def _load_knowledge(
        self, knowledge_path: Optional[str], run_name: Optional[str] = None
    ) -> str:
        """
        加载业务知识

        Args:
            knowledge_path: 知识文件或文件夹路径
            run_name: run名称（用于相对路径查找）

        Returns:
            知识内容字符串
        """
        if not knowledge_path:
            return ""

        # 处理路径：相对路径优先在实验环境中查找
        path = Path(knowledge_path)
        if not path.is_absolute():
            # 如果是相对路径，尝试以下路径：
            possible_paths = []

            # 1) run 目录（如有 run_name）
            if run_name:
                run_dir = self._find_run_directory(run_name)
                if run_dir:
                    run_path = run_dir / knowledge_path
                    if run_path.exists():
                        possible_paths.append(run_path)  # 优先级最高

            # 2) 设计目录（根据实验名推断）
            design_base = (
                self.experiment_name.split("_")[0] if self.experiment_name else None
            )
            if design_base:
                design_path = (
                    self.root_dir
                    / "experiments"
                    / "design"
                    / design_base
                    / knowledge_path
                )
                possible_paths.append(design_path)

            # 3) 实验根目录、项目根目录、当前工作目录
            possible_paths.extend(
                [
                    self.experiment_path / knowledge_path,  # 实验环境目录
                    self.root_dir / knowledge_path,  # 项目根目录
                    Path.cwd() / knowledge_path,  # 当前工作目录
                ]
            )

            for test_path in possible_paths:
                if test_path.exists():
                    path = test_path
                    print(f"🔍 找到知识文件: {test_path}")
                    break
            else:
                print(f"警告: 找不到知识文件: {knowledge_path}")
                print(f"已尝试路径: {[str(p) for p in possible_paths]}")
                return ""

        try:
            if path.is_file():
                # 单个文件
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                print(f"✅ 成功加载知识文件: {path} ({len(content)} 字符)")
                return content
            elif path.is_dir():
                # 文件夹：合并所有文件
                all_content = []
                for file_path in path.rglob("*.md"):  # 只读取markdown文件
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            file_content = f.read()
                            all_content.append(
                                f"=== {file_path.name} ===\n{file_content}\n"
                            )
                    except Exception as e:
                        print(f"警告: 读取文件 {file_path} 失败: {e}")

                combined_content = "\n".join(all_content)
                print(f"✅ 成功加载知识目录: {path} ({len(combined_content)} 字符)")
                return combined_content
            else:
                print(f"错误: 路径不存在: {path}")
                return ""
        except Exception as e:
            print(f"错误: 加载知识文件失败: {e}")
            return ""

    def _extract_result_from_log(
        self, log_content: str, start_marker: str, end_marker: str
    ) -> Optional[str]:
        """
        从日志内容中提取结果

        Args:
            log_content: 日志内容
            start_marker: 开始标记
            end_marker: 结束标记

        Returns:
            提取的结果，如果找不到返回None
        """
        try:
            start_pos = log_content.find(start_marker)
            if start_pos == -1:
                return None

            end_pos = log_content.find(end_marker, start_pos)
            if end_pos == -1:
                return None

            # 提取标记之间的内容
            content_start = start_pos + len(start_marker)
            extracted_content = log_content[content_start:end_pos].strip()

            return extracted_content if extracted_content else None

        except Exception as e:
            print(f"Warning: Failed to extract result from log: {e}")
            return None

    def _find_run_directory(self, run_name: str) -> Optional[Path]:
        """
        查找run目录，支持多种命名格式

        Args:
            run_name: run名称

        Returns:
            run目录路径，如果找不到返回None
        """
        # 尝试不同的run目录命名格式
        possible_names = [
            run_name,  # 原始名称
            run_name.replace("run", "run_"),  # run001 -> run_001
            f"run_{run_name.replace('run', '').zfill(3)}",  # run1 -> run_001
            f"run_{run_name.replace('run_', '').zfill(3)}",  # run_1 -> run_001
        ]

        for name in possible_names:
            test_dir = self.experiment_path / name
            if test_dir.exists():
                return test_dir

        print(f"错误: 找不到run目录: {run_name}")
        print(f"已尝试: {', '.join(possible_names)}")
        return None

    def _format_case_num(self, case_num: str) -> str:
        """
        格式化case编号为3位补零格式

        Args:
            case_num: case编号字符串

        Returns:
            格式化后的case编号（如：001, 002, 123）
        """
        return f"{int(case_num):03d}"

    def _create_output_directory(self, subdir: str) -> Path:
        """
        创建输出目录

        Args:
            subdir: 子目录名称

        Returns:
            创建的目录路径
        """
        output_dir = self.experiment_path / subdir
        output_dir.mkdir(exist_ok=True, parents=True)
        return output_dir
