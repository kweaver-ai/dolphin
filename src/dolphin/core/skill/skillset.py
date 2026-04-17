# -*- coding: utf-8 -*-
"""Deprecated: use dolphin.core.tool.toolset instead."""
import warnings

warnings.warn(
    "dolphin.core.skill.skillset is deprecated. Use dolphin.core.tool.toolset instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.core.tool.toolset import ToolSet as Skillset  # noqa: E402

__all__ = ["Skillset"]
