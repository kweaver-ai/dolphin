# -*- coding: utf-8 -*-
"""Deprecated: use dolphin.core.tool.tool_matcher instead."""
import warnings

warnings.warn(
    "dolphin.core.skill.skill_matcher is deprecated. Use dolphin.core.tool.tool_matcher instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.core.tool.tool_matcher import ToolMatcher as SkillMatcher  # noqa: E402

__all__ = ["SkillMatcher"]
