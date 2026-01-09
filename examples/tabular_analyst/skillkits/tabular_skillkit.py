import os
import json
from typing import List, Optional
import pandas as pd
from pathlib import Path

from dolphin.core import SkillFunction, Skillkit, get_logger

logger = get_logger()


class TabularSkillkit(Skillkit):
    """Tabular data analysis skillkit"""

    SUPPORTED_EXTENSIONS = [".csv", ".xlsx", ".xls", ".json", ".parquet"]

    def __init__(self):
        super().__init__()
        self.max_sample_rows = 5  # Max sample rows
        self.max_column_preview = 10  # Max column preview length

    def getName(self) -> str:
        return "tabular_skillkit"

    def _validate_file_path(self, file_path: str) -> None:
        """Validate file path and format"""
        if not file_path:
            raise ValueError("File path cannot be empty")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format: {path.suffix}. Supported: {self.SUPPORTED_EXTENSIONS}"
            )

    def _read_dataframe(self, file_path: str) -> pd.DataFrame:
        """Read file as DataFrame"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        try:
            if suffix == ".csv":
                return pd.read_csv(file_path)
            elif suffix in [".xlsx", ".xls"]:
                return pd.read_excel(file_path)
            elif suffix == ".json":
                return pd.read_json(file_path)
            elif suffix == ".parquet":
                return pd.read_parquet(file_path)
            else:
                raise ValueError(f"Unsupported file format: {suffix}")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {str(e)}")
            raise ValueError(f"Failed to read file: {str(e)}")

    def _get_column_info_basic(self, df: pd.DataFrame) -> dict:
        """Get basic column information"""
        columns_info = {}

        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null_count = int(df[col].count())  # Convert to Python int
            total_count = len(df)
            null_percentage = (
                ((total_count - non_null_count) / total_count * 100)
                if total_count > 0
                else 0
            )

            # 获取样本值
            sample_values = df[col].dropna().head(self.max_sample_rows).tolist()
            sample_values = [
                str(val)[: self.max_column_preview] for val in sample_values
            ]

            columns_info[col] = {
                "data_type": dtype,
                "non_null_count": non_null_count,
                "null_percentage": round(
                    float(null_percentage), 2
                ),  # Convert to Python float
                "sample_values": sample_values,
                "unique_count": (
                    int(df[col].nunique()) if non_null_count > 0 else 0
                ),  # Convert to Python int
            }

        return columns_info

    def get_tabular_columns(
        self, file_path: str, return_feat: Optional[List[str]] = None, **kwargs
    ) -> str:
        """
        Extract raw column metadata from tabular data files.

        Directly reads file and returns basic column information: column names, data types, and sample values.

        Args:
            file_path (str): Path to the tabular data file.
            return_feat (list[str], optional): List of specific features/columns to return. If None, returns all.
            **kwargs: Additional properties passed to the tool.

        Returns:
            str: Formatted string with raw column information.
        """
        try:
            # Validate file path
            self._validate_file_path(file_path)

            # Read data
            df = self._read_dataframe(file_path)

            if df.empty:
                return json.dumps(
                    {"error": "File is empty or contains no data"}, ensure_ascii=False
                )

            # Get column info
            columns_info = self._get_column_info_basic(df)

            # If specific columns are specified, return only their info
            if return_feat:
                columns_info = {
                    k: v for k, v in columns_info.items() if k in return_feat
                }
                if not columns_info:
                    return json.dumps(
                        {"error": f"No matching columns found for: {return_feat}"},
                        ensure_ascii=False,
                    )

            # Build result
            result = {
                "file_path": file_path,
                "total_rows": len(df),
                "total_columns": len(columns_info),
                "columns": columns_info,
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error in get_tabular_columns: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_column_info(self, file_path: str, **kwargs) -> str:
        """
        Intelligently analyze and interpret column information.

        Builds on get_tabular_columns() to provide simple file structure analysis and column meaning interpretation.

        Args:
            file_path (str): Path to the tabular data file.
            **kwargs: Additional properties passed to the tool.

        Returns:
            str: Analysis with file structure and column explanations.
        """
        try:
            # Validate file path
            self._validate_file_path(file_path)

            # Read data
            df = self._read_dataframe(file_path)

            if df.empty:
                return json.dumps(
                    {"error": "File is empty or contains no data"}, ensure_ascii=False
                )

            # Get basic column info
            basic_info = self._get_column_info_basic(df)

            # Intelligent analysis
            analysis = {
                "file_info": {
                    "path": file_path,
                    "format": Path(file_path).suffix.lower(),
                    "total_rows": int(len(df)),  # Convert to Python int
                    "total_columns": int(len(df.columns)),  # Convert to Python int
                    "memory_usage": f"{float(df.memory_usage(deep=True).sum()) / 1024:.2f} KB",  # Convert to Python float
                },
                "structure_analysis": {
                    "has_duplicates": bool(df.duplicated().any()),  # Convert to Python bool
                    "duplicate_rows": int(df.duplicated().sum()),  # Convert to Python int
                    "data_completeness": f"{float(df.count().sum()) / (len(df) * len(df.columns)) * 100:.1f}%",  # Convert to Python float
                },
                "column_analysis": {},
            }

            # Analyze each column
            for col in df.columns:
                col_info = basic_info[col]
                dtype = col_info["data_type"]

                # Intelligently infer column meaning
                column_insights = []

                # Data type analysis
                if dtype == "object":
                    # Could be string, categorical or mixed type
                    unique_ratio = (
                        col_info["unique_count"] / col_info["non_null_count"]
                        if col_info["non_null_count"] > 0
                        else 0
                    )
                    if unique_ratio < 0.1:
                        column_insights.append("Low cardinality - likely categorical")
                    elif unique_ratio > 0.8:
                        column_insights.append(
                            "High cardinality - likely unique identifiers"
                        )
                    else:
                        column_insights.append(
                            "Mixed cardinality - potential text data"
                        )
                elif dtype in ["int64", "float64"]:
                    # Numeric data analysis
                    if dtype == "int64":
                        column_insights.append(
                            "Integer data - could be counts, IDs, or discrete values"
                        )
                    else:
                        column_insights.append(
                            "Float data - likely measurements or calculated values"
                        )
                elif "datetime" in dtype.lower():
                    column_insights.append("Date/time data - temporal information")

                # Null value analysis
                if col_info["null_percentage"] > 50:
                    column_insights.append(
                        "High null percentage - may need data imputation"
                    )
                elif col_info["null_percentage"] > 10:
                    column_insights.append(
                        "Moderate null percentage - review data quality"
                    )

                # Unique value analysis
                if col_info["unique_count"] == len(df):
                    column_insights.append(
                        "All values unique - likely a primary key or ID column"
                    )

                analysis["column_analysis"][col] = {
                    **col_info,
                    "insights": column_insights,
                }

            return json.dumps(analysis, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error in get_column_info: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def getSkills(self) -> List[SkillFunction]:
        """Return all available skill functions"""
        return [
            SkillFunction(self.get_tabular_columns),
            SkillFunction(self.get_column_info),
        ]
