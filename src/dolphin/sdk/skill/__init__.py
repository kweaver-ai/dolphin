# -*- coding: utf-8 -*-
"""Deprecated: dolphin.sdk.skill has been renamed to dolphin.sdk.tool.

This module is a backward-compatibility shim. All names here are re-exported
from :mod:`dolphin.sdk.tool`.  Importing from ``dolphin.sdk.skill`` will emit
a :class:`DeprecationWarning`; please update your imports.
"""
import warnings

warnings.warn(
    "The 'dolphin.sdk.skill' package is deprecated and will be removed in a "
    "future release. Use 'dolphin.sdk.tool' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.sdk import GlobalSkills  # noqa: E402
from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit  # noqa: E402

__all__ = [
    "GlobalSkills",
    "TriditionalToolkit",
]
