# -*- coding: utf-8 -*-
"""Deprecated: use dolphin.sdk.tool.global_toolkits instead."""
import warnings

warnings.warn(
    "dolphin.sdk.skill.global_skills is deprecated. "
    "Use dolphin.sdk.tool.global_toolkits instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.sdk import GlobalSkills  # noqa: E402

__all__ = ["GlobalSkills"]
