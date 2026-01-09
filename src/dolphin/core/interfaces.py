# -*- coding: utf-8 -*-
"""
Protocol 接口定义 - 用于解耦跨层依赖
"""

from typing import Protocol, List, Any, Optional


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
