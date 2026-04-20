# -*- coding: utf-8 -*-
"""Deprecated: dolphin.core.skill has been renamed to dolphin.core.tool.

This package is a backward-compatibility shim.
"""
import warnings

warnings.warn(
    "The 'dolphin.core.skill' package is deprecated and will be removed in a "
    "future release. Use 'dolphin.core.tool' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.core import Skillkit, Skillset  # noqa: E402
from dolphin.core.tool.tool_function import ToolFunction as SkillFunction  # noqa: E402
from dolphin.core.tool.tool_matcher import ToolMatcher as SkillMatcher  # noqa: E402

__all__ = ["Skillkit", "Skillset", "SkillFunction", "SkillMatcher"]
