"""Strategy Module
Provides an abstract interface and concrete implementations for data processing strategies (a unified model based on category)
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.lib.skill_results.result_reference import ResultReference

from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


class BaseStrategy(ABC):
    """Base class for unified strategies.

    - Use category to distinguish usage scenarios (e.g., 'llm', 'app', 'export', etc.)
    - Subclasses must set the class attribute category and implement process()
    """

    # Subclasses should override to specify a concrete category, such as 'llm' or 'app'
    category: str = "generic"

    def get_category(self) -> str:
        return getattr(self, "category", "generic")

    def supports(self, category: str) -> bool:
        return self.get_category() == category

    @abstractmethod
    def process(self, result_reference: "ResultReference", **kwargs) -> Any:
        """Execute strategy processing and return final data (different categories may return different structures)"""
        raise NotImplementedError


# ======================== LLM Category Strategy (category='llm') ========================


class BaseLLMStrategy(BaseStrategy):
    """Base class for LLM strategies, providing general data transformation methods"""

    category = "llm"

    def _convert_to_string(self, data: Any) -> str:
        """Convert data to string format"""
        if isinstance(data, str):
            return data
        elif isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False, indent=2)
        else:
            return str(data)


class DefaultLLMStrategy(BaseLLMStrategy):

    def process(self, result_reference: "ResultReference", **kwargs) -> str:
        try:
            full_result = result_reference.get_full_result()
            if full_result is None:
                return "数据不存在"

            return self._convert_to_string(full_result)
        except Exception as e:
            logger.error(f"默认LLM策略处理failed: {e}")
            return f"数据处理failed: {str(e)}"


class SummaryLLMStrategy(BaseLLMStrategy):

    def process(self, result_reference: "ResultReference", **kwargs) -> str:
        try:
            full_result = result_reference.get_full_result()
            if full_result is None:
                return "数据不存在"

            max_tokens = kwargs.get("max_tokens", 2000)
            max_chars = max_tokens * 4

            result_str = self._convert_to_string(full_result)
            if len(result_str) <= max_chars:
                return result_str

            return self._generate_summary(result_str, max_chars)
        except Exception as e:
            logger.error(f"摘要LLM策略处理failed: {e}")
            return f"摘要生成failed: {str(e)}"

    def _generate_summary(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        start_chars = int(max_chars * 0.6)
        end_chars = int(max_chars * 0.2)
        start_part = text[:start_chars]
        end_part = text[-end_chars:] if end_chars > 0 else ""

        return f"{start_part}\n\n... (内容已截断) ...\n\n{end_part}"


class TruncateLLMStrategy(BaseLLMStrategy):

    def process(self, result_reference: "ResultReference", **kwargs) -> str:
        try:
            full_result = result_reference.get_full_result()
            if full_result is None:
                return "数据不存在"

            max_tokens = kwargs.get("max_tokens", 2000)
            max_chars = max_tokens * 4

            result_str = self._convert_to_string(full_result)
            if len(result_str) <= max_chars:
                return result_str

            truncated = result_str[:max_chars]
            return (
                f"{truncated}\n\n... (内容已截断，总长度: {len(result_str)} 字符) ..."
            )
        except Exception as e:
            logger.error(f"截取LLM策略处理failed: {e}")
            return f"数据截取failed: {str(e)}"


# ====================== APP Category Strategy (category='app') ======================


class DefaultAppStrategy(BaseStrategy):
    category = "app"

    def process(self, result_reference: "ResultReference", **kwargs) -> Dict[str, Any]:
        try:
            full_result = result_reference.get_full_result()
            return full_result
        except Exception as e:
            logger.error(f"默认APP策略处理failed: {e}")
            return {
                "error": f"数据处理failed: {str(e)}",
                "reference_id": result_reference.reference_id,
            }


class PaginationAppStrategy(BaseStrategy):
    category = "app"

    def process(self, result_reference: "ResultReference", **kwargs) -> Dict[str, Any]:
        try:
            full_result = result_reference.get_full_result()
            metadata = result_reference.get_metadata()
            if full_result is None:
                return {
                    "error": "数据不存在",
                    "reference_id": result_reference.reference_id,
                }

            page = kwargs.get("page", 1)
            page_size = kwargs.get("page_size", 20)

            if isinstance(full_result, list):
                return self._paginate_list(
                    full_result,
                    page,
                    page_size,
                    metadata,
                    result_reference.reference_id,
                )
            elif isinstance(full_result, dict):
                return self._paginate_dict(
                    full_result,
                    page,
                    page_size,
                    metadata,
                    result_reference.reference_id,
                )
            else:
                return {
                    "data": full_result,
                    "metadata": metadata,
                    "reference_id": result_reference.reference_id,
                    "strategy": "pagination",
                    "pagination": {
                        "page": 1,
                        "page_size": 1,
                        "total_pages": 1,
                        "total_items": 1,
                    },
                }
        except Exception as e:
            logger.error(f"分页APP策略处理failed: {e}")
            return {
                "error": f"分页处理failed: {str(e)}",
                "reference_id": result_reference.reference_id,
            }

    def _paginate_list(
        self,
        data: List[Any],
        page: int,
        page_size: int,
        metadata: Dict[str, Any],
        reference_id: str,
    ) -> Dict[str, Any]:
        total_items = len(data)
        total_pages = (total_items + page_size - 1) // page_size
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_data = data[start_idx:end_idx]
        return {
            "data": page_data,
            "metadata": metadata,
            "reference_id": reference_id,
            "strategy": "pagination",
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_items": total_items,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }

    def _paginate_dict(
        self,
        data: Dict[str, Any],
        page: int,
        page_size: int,
        metadata: Dict[str, Any],
        reference_id: str,
    ) -> Dict[str, Any]:
        items = list(data.items())
        total_items = len(items)
        total_pages = (total_items + page_size - 1) // page_size
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = items[start_idx:end_idx]
        page_data = dict(page_items)
        return {
            "data": page_data,
            "metadata": metadata,
            "reference_id": reference_id,
            "strategy": "pagination",
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_items": total_items,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }


class PreviewAppStrategy(BaseStrategy):
    category = "app"

    def process(self, result_reference: "ResultReference", **kwargs) -> Dict[str, Any]:
        try:
            full_result = result_reference.get_full_result()
            metadata = result_reference.get_metadata()
            if full_result is None:
                return {
                    "error": "数据不存在",
                    "reference_id": result_reference.reference_id,
                }

            max_size = kwargs.get("max_size", 1000)
            max_items = kwargs.get("max_items", 10)

            preview_data = self._generate_preview(full_result, max_size, max_items)
            return {
                "preview": preview_data,
                "metadata": metadata,
                "reference_id": result_reference.reference_id,
                "strategy": "preview",
                "type": type(full_result).__name__,
                "truncated": self._is_truncated(full_result, preview_data, max_size),
            }
        except Exception as e:
            logger.error(f"预览APP策略处理failed: {e}")
            return {
                "error": f"预览处理failed: {str(e)}",
                "reference_id": result_reference.reference_id,
            }

    def _generate_preview(self, data: Any, max_size: int, max_items: int) -> Any:
        """Generate preview data"""
        if isinstance(data, str):
            if len(data) <= max_size:
                return data
            return data[:max_size] + "..."

        elif isinstance(data, list):
            if len(data) <= max_items:
                return data
            return data[:max_items] + ["..."]

        elif isinstance(data, dict):
            items = list(data.items())
            if len(items) <= max_items:
                return data
            preview_dict = dict(items[:max_items])
            preview_dict["..."] = f"还有 {len(items) - max_items} 项"
            return preview_dict

        else:
            result_str = str(data)
            if len(result_str) <= max_size:
                return data
            return self._truncate_preview(data, max_size)

    def _is_truncated(self, original: Any, preview: Any, max_size: int) -> bool:
        """Determine if truncated"""
        if isinstance(original, str):
            return len(original) > max_size
        elif isinstance(original, (list, dict)):
            return len(str(original)) > max_size
        return False

    def _truncate_preview(self, data: Any, max_size: int) -> str:
        """Truncate Preview"""
        result_str = str(data)
        if len(result_str) <= max_size:
            return result_str
        return result_str[:max_size] + "..."
