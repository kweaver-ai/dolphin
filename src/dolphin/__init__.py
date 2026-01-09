# -*- coding: utf-8 -*-
"""
Dolphin Language - An intelligent agent framework

模块结构：
- dolphin.core: 核心运行时引擎（内核态）
- dolphin.lib: 标准库和工具集（用户态）
- dolphin.sdk: 开发者 SDK（开发框架）
- dolphin.cli: 命令行工具（应用层）

依赖关系：
  cli → sdk → lib → core
"""

__version__ = "0.1.0"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.core import (
        Context,
        BaseAgent,
        AgentState,
        Skillset,
        Skillkit,
        SkillFunction,
        RuntimeInstance,
        RuntimeGraph,
    )
    from dolphin.sdk import (
        DolphinAgent,
        Env,
        GlobalSkills,
    )

_module_lookup = {
    # Core
    "Context": "dolphin.core",
    "BaseAgent": "dolphin.core",
    "AgentState": "dolphin.core",
    "Skillset": "dolphin.core",
    "Skillkit": "dolphin.core",
    "SkillFunction": "dolphin.core",
    "RuntimeInstance": "dolphin.core",
    "RuntimeGraph": "dolphin.core",
    # SDK
    "DolphinAgent": "dolphin.sdk",
    "Env": "dolphin.sdk",
    "GlobalSkills": "dolphin.sdk",
}

def __getattr__(name):
    if name in _module_lookup:
        import importlib
        module = importlib.import_module(_module_lookup[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "__version__",
    *list(_module_lookup.keys()),
]
