# -*- coding: utf-8 -*-
"""
Dolphin CLI - 命令行工具（应用层）

职责：
- CLI 入口
- 命令实现（run、chat、debug）
- 用户界面（控制台 UI、布局、流式渲染）
- 运行器
- 中断处理

依赖规则：
- dolphin.cli → 依赖 dolphin.sdk, dolphin.lib, dolphin.core
"""

from dolphin.cli.main import main

__all__ = [
    "main",
]
