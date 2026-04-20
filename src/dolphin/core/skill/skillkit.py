# -*- coding: utf-8 -*-
"""Deprecated: use dolphin.core.tool.toolkit instead."""
import warnings

warnings.warn(
    "dolphin.core.skill.skillkit is deprecated. Use dolphin.core.tool.toolkit instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.core import Skillkit  # noqa: E402

__all__ = ["Skillkit"]
