# -*- coding: utf-8 -*-
"""Executor 模块 - 执行器"""

from dolphin.core.executor.executor import Executor
from dolphin.core.executor.debug_controller import DebugController

# DolphinExecutor has sdk dependencies, use lazy import
def __getattr__(name):
    if name == "DolphinExecutor":
        from dolphin.core.executor.dolphin_executor import DolphinExecutor
        return DolphinExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Executor",
    "DolphinExecutor",
    "DebugController",
]
