"""SkillKit Hook Module
Provides hook functions and utility methods for processing skill results.

Main Features:
- Before returning to LLM: get_for_llm -> generates understandable data based on strategy
- Before returning to APP: get_for_app -> generates displayable data based on strategy
- Result caching: unified management of result lifecycle
"""

from typing import Dict, Any, Optional

from dolphin.lib.skill_results.result_processor import ResultProcessor
from dolphin.lib.skill_results.result_reference import ResultReference
from dolphin.lib.skill_results.strategy_registry import StrategyRegistry
from dolphin.lib.skill_results.cache_backend import (
    CacheBackend,
    MemoryCacheBackend,
)
from dolphin.core.skill.skill_function import SkillFunction, DynamicAPISkillFunction

from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


class SkillkitHook:
    """Skillkit Result Processing Hooks.

    - Provides a unified interface for result retrieval and processing
    - Supports data transformation with different strategies
    - Manages result caching and lifecycle
    """

    def __init__(
        self,
        cache_backend: Optional[CacheBackend] = None,
        strategy_registry: Optional[StrategyRegistry] = None,
    ) -> None:
        self._processor = ResultProcessor(
            cache_backend=cache_backend or MemoryCacheBackend(),
            strategy_registry=strategy_registry or StrategyRegistry(),
        )

    # === Hook: After tool execution ===
    def on_tool_after_execute(
        self, tool_name: str, result: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> ResultReference:
        """Alias: equivalent to process_result."""
        return self.process_result(
            tool_name=tool_name, result=result, metadata=metadata
        )

    # === Hook: After tool execution ===
    def process_result(
        self,
        tool_name: str,
        result: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResultReference:
        """Called after the tool execution is completed, saves the result and returns a reference.
        The returned reference ID can be recorded in the context for subsequent frontend/LLM to retrieve data as needed.
        """
        return self._processor.process_result(
            tool_name=tool_name, result=result, metadata=metadata
        )

    # === Hook: Before returning LLM ===
    def on_before_send_to_llm(
        self,
        reference_id: str,
        strategy_name: str = None,
        skill: SkillFunction = None,
        **kwargs,
    ) -> Optional[str]:
        """Alias: equivalent to get_for_llm. Uses the default strategy by default.

        Special handling for dynamic tool responses:
        - If the result contains _dynamic_tools marker, returns a user-friendly message
        - Otherwise, processes the result using the normal strategy
        """

        # Check if this is a dynamic tool response
        ref = self._get_result_reference(reference_id)

        if ref:
            full_result = ref.get_full_result()

            if isinstance(full_result, dict):
                # Check for _dynamic_tools at multiple levels
                dynamic_tools = None
                message = ""
                
                # Level 1: Check if _dynamic_tools is directly in full_result
                if "_dynamic_tools" in full_result:
                    dynamic_tools = full_result.get("_dynamic_tools", [])
                    message = full_result.get("message", "") or full_result.get("answer", "")
                    if isinstance(message, dict):
                        message = message.get("message", "") or message.get("answer", "")
                
                # Level 2: Check if _dynamic_tools is in full_result["answer"]
                elif "answer" in full_result:
                    answer = full_result["answer"]
                    if isinstance(answer, dict) and "_dynamic_tools" in answer:
                        dynamic_tools = answer.get("_dynamic_tools", [])
                        message = answer.get("message", "")
                
                # If we found dynamic tools, process them
                if dynamic_tools is not None:
                    tool_names = []
                    if isinstance(dynamic_tools, list):
                        for tool in dynamic_tools:
                            if isinstance(tool, dict) and "name" in tool:
                                tool_names.append(tool["name"])

                    # Build the response message
                    if not message and tool_names:
                        message = f"Successfully loaded {len(tool_names)} tools: {', '.join(tool_names)}"
                    elif not message:
                        message = "Successfully loaded dynamic tools"
                    
                    logger.debug(
                        f"[Dynamic Tool] Returning for LLM - message: {message}, tools: {tool_names}"
                    )
                    return message

        # Normal processing
        if strategy_name is None and skill is not None:
            strategy_name = skill.get_first_valid_llm_strategy()

        strategy_name = strategy_name if strategy_name else "default"

        return self.get_for_llm(
            reference_id=reference_id, strategy_name=strategy_name, **kwargs
        )

    def on_before_reply_app(
        self,
        reference_id: str,
        strategy_name: str = "default",
        skill: SkillFunction = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Alias: equivalent to get_for_app. Uses the default strategy by default.
        
        Special handling for dynamic tool responses:
        - If the result contains _dynamic_tools marker, returns structured data with message
        - Otherwise, processes the result using the normal strategy
        """
        # Check if this is a dynamic API tool response
        ref = self._get_result_reference(reference_id)

        if ref and skill and isinstance(skill, DynamicAPISkillFunction):
            full_result = ref.get_full_result()
            return {"answer": full_result}
        
        # Normal processing
        try:
            strategy_name = skill.get_first_valid_app_strategy()
            if not strategy_name:
                return {"error": "未找到有效的APP策略"}

            return self.get_for_app(reference_id, strategy_name=strategy_name, **kwargs)
        except Exception as e:
            logger.error(f"APP回复前处理failed: {e}")
            return {"error": f"数据处理failed: {str(e)}"}

    def on_before_send_to_context(
        self,
        reference_id: str,
        skill: SkillFunction,
        skillkit_name: str,
        resource_skill_path: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Hook called before sending result to context (SCRATCHPAD message).

        This hook applies context retention strategies to optimize how much
        content is stored in the context window.

        Args:
            reference_id: The result reference ID
            skill: The executed skill function
            skillkit_name: Name of the skillkit
            resource_skill_path: Optional path to resource skill

        Returns:
            tuple[str, dict]: (processed_content, metadata)
        """
        from dolphin.core.skill.context_retention import (
            SkillContextRetention,
            get_context_retention_strategy,
            ContextRetentionMode,
        )

        ref = self._get_result_reference(reference_id)
        if not ref:
            return "", {}

        full_result = ref.get_full_result()
        if not isinstance(full_result, str):
            full_result = str(full_result)

        # Get decorator config or default
        config = getattr(skill.func, '_context_retention', None)
        if not config:
            config = SkillContextRetention()  # Default FULL mode

        # Apply strategy
        strategy = get_context_retention_strategy(config.mode)
        processed_result = strategy.process(full_result, config, reference_id)

        # Build metadata
        metadata = {
            "original_length": len(full_result),
            "processed_length": len(processed_result),
            "retention_mode": config.mode.value,
            "pinned": config.mode == ContextRetentionMode.PIN,
        }

        # Use update() to merge with existing metadata
        existing_metadata = ref.get_metadata()
        if existing_metadata:
            metadata.update(existing_metadata)

        return processed_result, metadata

    def get_for_llm(
        self, reference_id: str, strategy_name: str = "default", **kwargs
    ) -> str:
        """Get data suitable for LLM
        - Generate data in a format understandable by LLM according to the strategy
        - Support strategies such as 'llm:summary', 'llm:truncate', etc.
        """
        try:
            ref = self._get_result_reference(reference_id)
            if ref is None:
                return "结果引用不存在"

            return ref.get_for_category("llm", strategy_name, **kwargs)
        except Exception as e:
            logger.error(f"GetLLM数据failed: {e}")
            return f"数据Getfailed: {str(e)}"

    def get_for_app(
        self, reference_id: str, strategy_name: str = "default", **kwargs
    ) -> Dict[str, Any]:
        """Get data suitable for APP
        - Generate a displayable data format according to the strategy
        - Support strategies such as 'app:pagination', 'app:preview', etc.
        """
        try:
            ref = self._get_result_reference(reference_id)
            if ref is None:
                return {"error": "结果引用不存在"}

            return ref.get_for_category("app", strategy_name=strategy_name, **kwargs)
        except Exception as e:
            logger.error(f"GetAPP数据failed: {e}")
            return {"error": f"数据Getfailed: {str(e)}"}

    def get_for_category(
        self, reference_id: str, category: str, strategy_name: str = "default", **kwargs
    ) -> Any:
        """Get data based on category
        - Supports strategy processing for any category
        - Provides unified error handling
        """
        try:
            ref = self._get_result_reference(reference_id)
            if ref is None:
                if category == "llm":
                    return "结果引用不存在"
                else:
                    return {"error": "结果引用不存在"}

            return ref.get_for_category(category, strategy_name=strategy_name, **kwargs)
        except Exception as e:
            logger.error(f"Get{category}数据failed: {e}")
            if category == "llm":
                return f"数据Getfailed: {str(e)}"
            else:
                return {"error": f"数据Getfailed: {str(e)}"}

    def get_raw_result(self, reference_id: str) -> Any:
        """Get original result data (not processed by strategy)"""
        try:
            ref = self._get_result_reference(reference_id)
            if ref is None:
                return None
            return ref.get_full_result()
        except Exception as e:
            logger.error(f"Get原始结果failed: {e}")
            return None

    def get_result_metadata(self, reference_id: str) -> Optional[Dict[str, Any]]:
        """Get result metadata"""
        try:
            ref = self._get_result_reference(reference_id)
            if ref is None:
                return None
            return ref.get_metadata()
        except Exception as e:
            logger.error(f"Get结果元数据failed: {e}")
            return None

    def _get_result_reference(self, reference_id: str) -> Optional[ResultReference]:
        """Get result reference"""
        try:
            """Get ResultReference by reference ID."""
            return self._processor.get_result_reference(reference_id)
        except Exception as e:
            logger.error(f"Get结果引用failed: {e}")
            return None

    def delete_result(self, reference_id: str) -> bool:
        """Delete the cached result of the specified reference."""
        return self._processor.delete_result(reference_id)

    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Clean up expired cache and return the number of items cleaned."""
        return self._processor.cleanup_expired(max_age_hours=max_age_hours)

    def get_stats(self) -> Dict[str, Any]:
        """Get the statistics information of the cache and policy system."""
        return self._processor.get_stats()
