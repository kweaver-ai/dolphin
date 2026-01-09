# -*- coding: utf-8 -*-
"""
内置 Agent 定义

提供 Dolphin CLI 默认使用的内置智能体，类似 OpenAI Codex 和 Claude Code 的默认交互模式。

包含:
- explore: 带有本地环境工具的 explore 对话智能体
"""

import os

# 获取内置 agents 目录路径
BUILTIN_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认的 explore agent 名称
DEFAULT_EXPLORE_AGENT = "explore"

__all__ = [
    "BUILTIN_AGENTS_DIR",
    "DEFAULT_EXPLORE_AGENT",
]
