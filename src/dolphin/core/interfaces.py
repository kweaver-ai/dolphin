# -*- coding: utf-8 -*-
"""
Protocol 接口定义 - 用于解耦跨层依赖
"""

from typing import Protocol, List, Any, Optional, Dict


class IMemoryManager(Protocol):
    """内存管理器接口 - 实现在 dolphin.lib.memory"""
    
    def retrieve_relevant_memory(
        self, 
        context: Any, 
        user_id: str, 
        query: str,
        top_k: int = 5,
    ) -> List[Any]:
        """检索相关记忆"""
        ...
    
    def store_memory(
        self,
        user_id: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """存储记忆"""
        ...


class ISkillkit(Protocol):
    """Skillkit 接口 - 用于类型提示"""
    
    def exec(self, skill_name: str, *args, **kwargs) -> Any:
        """执行 skill"""
        ...
    
    def get_skill_list(self) -> List[str]:
        """获取 skill 列表"""
        ...


class ITrajectory(Protocol):
    """轨迹接口 - 用于类型提示"""
    
    def record(self, event_type: str, data: dict) -> None:
        """记录事件"""
        ...
    
    def get_records(self) -> List[dict]:
        """获取所有记录"""
        ...


class ITraceListener(Protocol):
    """Trace listener interface for observability tracking
    
    This interface enables dolphin SDK to report LLM and tool execution events
    to external tracing systems (e.g., OpenTelemetry) without tight coupling.
    Implementations can use OpenTelemetry or other tracing backends without
    coupling the dolphin SDK to specific observability implementations.
    """
    
    def on_llm_start(
        self,
        model: str,
        messages: List[dict],
        block_type: str,
        **kwargs,
    ) -> None:
        """Called before LLM invocation
        
        Args:
            model: Model name (e.g., "gpt-4")
            messages: Input messages list
            block_type: Block type ("chat", "judge", "explore")
            **kwargs: Additional context (temperature, top_p, etc.)
        """
        ...
    
    def on_llm_end(
        self,
        model: str,
        response: Optional[dict],
        latency_ms: int,
        usage: Optional[dict],
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Called after LLM invocation completes
        
        Args:
            model: Model name
            response: LLM response dict (None if error occurred)
            latency_ms: Execution time in milliseconds
            usage: Token usage dict (input_tokens, output_tokens)
            error: Exception if call failed, None otherwise
            **kwargs: Additional context
        """
        ...
    
    def on_tool_start(
        self,
        tool_name: str,
        tool_type: str,
        args: dict,
        **kwargs,
    ) -> None:
        """Called before tool execution
        
        Args:
            tool_name: Name of the tool/skill
            tool_type: Tool type ("function", "extension", etc.)
            args: Tool input parameters
            **kwargs: Additional context
        """
        ...
    
    def on_tool_end(
        self,
        tool_name: str,
        result: Optional[Any],
        latency_ms: int,
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Called after tool execution completes
        
        Args:
            tool_name: Name of the tool/skill
            result: Tool execution result (None if error occurred)
            latency_ms: Execution time in milliseconds
            error: Exception if execution failed, None otherwise
            **kwargs: Additional context
        """
        ...
