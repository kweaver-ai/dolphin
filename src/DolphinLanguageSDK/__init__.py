"""
DolphinLanguageSDK - Compatibility Layer

This package is deprecated. Please migrate to the new module structure:
- dolphin.core
- dolphin.sdk
- dolphin.cli

Notes:
- Keep this module intentionally thin to reduce maintenance cost.
- Exposed names are best-effort for backward compatibility.
"""

from __future__ import annotations

import warnings
from typing import Any

warnings.warn(
    "DolphinLanguageSDK is deprecated. Please migrate to dolphin.core/dolphin.sdk.",
    DeprecationWarning,
    stacklevel=2,
)


def __getattr__(name: str) -> Any:
    """
    Lazily resolve legacy exports.

    This avoids importing a large graph at module import time while keeping
    backward compatibility for common entry points.
    """
    if name == "Context":
        from dolphin.core import Context as _Context

        return _Context
    if name == "Env":
        from dolphin.sdk import Env as _Env

        return _Env
    if name == "DolphinAgent":
        from dolphin.sdk import DolphinAgent as _DolphinAgent

        return _DolphinAgent
    if name == "flags":
        from dolphin.core import flags as _flags

        return _flags

    raise AttributeError(
        f"module 'DolphinLanguageSDK' has no attribute '{name}'. "
        "This compatibility layer only exposes a small subset of legacy APIs. "
        "Please migrate to dolphin.core/dolphin.sdk."
    )


__all__ = ["Context", "Env", "DolphinAgent", "flags"]

