# -*- coding: utf-8 -*-
"""Deprecated: use dolphin.core.tool.tool_function instead."""
import warnings

warnings.warn(
    "dolphin.core.skill.skill_function is deprecated. Use dolphin.core.tool.tool_function instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.core.tool.tool_function import ToolFunction as SkillFunction  # noqa: E402

__all__ = ["SkillFunction"]
