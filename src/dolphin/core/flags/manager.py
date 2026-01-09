"""Feature Flags Management Module (Lightweight + Strict + Concurrent Isolation)

Features:
- Constant Access (prohibits string literals; allows dynamically verified strings from configuration layer)
- Strict Validation for Unknown Flags (errors in test/development environments, configurable degradation)
- Scope Overriding Based on ContextVar, Thread/Coroutine Safe
"""

from typing import Dict, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os

# Module-level imports, avoid repeated imports inside function bodies
from .definitions import DEFAULT_VALUES as _DEFAULTS

logger = logging.getLogger(__name__)

# Known flags set
_KNOWN_FLAGS = frozenset(_DEFAULTS.keys())

# Concurrency context isolation: Maintain independent overrides for each thread/coroutine
_OVERRIDES: ContextVar[Dict[str, bool]] = ContextVar("DL_FLAGS_OVERRIDES", default={})


def _get_overrides() -> Dict[str, bool]:
    """Get the overlay mapping of the current context (cannot be directly modified in-place)."""
    return dict(_OVERRIDES.get())  # Return a copy to avoid direct shared references being modified


def _set_overrides(new_map: Dict[str, bool]):
    _OVERRIDES.set(new_map)


def _strict_mode() -> bool:
    # Default strict mode enabled (safer for development/testing); disable in production via DL_FLAGS_STRICT=0
    return os.getenv("DL_FLAGS_STRICT", "1") not in {"0", "false", "False"}


def _ensure_known(name: str) -> bool:
    if name in _KNOWN_FLAGS:
        return True
    msg = f"Unknown feature flag: {name}"
    if _strict_mode():
        raise KeyError(msg)
    logger.warning(msg)
    return False


class _FlagsManager:
    """Flag Manager (Singleton)"""

    def is_enabled(self, name: str) -> bool:
        """Check whether the flag is enabled (string literals are prohibited and must be passed as constant values)."""
        if not _ensure_known(name):
            return False
        overrides = _get_overrides()
        if name in overrides:
            return overrides[name]
        return _DEFAULTS.get(name, False)

    def set(self, name: str, value: bool) -> None:
        """Set the override value for a single flag."""
        if not _ensure_known(name):
            return
        overrides = _get_overrides()
        overrides[name] = bool(value)
        _set_overrides(overrides)

    @contextmanager
    def override(self, mapping: Mapping[str, bool]):
        """Temporarily override flags (explicit mapping only).

                Usage example: with flags.override({flags.EXPLORE_BLOCK_V2: True})
        """
        to_apply: Dict[str, bool] = {}

        # Strict validation + normalization of boolean
        for name, value in mapping.items():
            if _ensure_known(name):
                to_apply[name] = bool(value)

        # Save and set new value (scope isolation)
        saved = _get_overrides()
        try:
            new_map = saved.copy()
            new_map.update(to_apply)
            _set_overrides(new_map)
            yield
        finally:
            _set_overrides(saved)

    def reset(self) -> None:
        """Clear the override values in the current context."""
        _set_overrides({})

    def get_all(self) -> Dict[str, bool]:
        """Return the current values of all known flags (overrides > defaults)."""
        cur = _get_overrides()
        return {
            name: cur.get(name, _DEFAULTS.get(name, False)) for name in _KNOWN_FLAGS
        }


_manager = _FlagsManager()

# Functional facade (for reuse in __init__.py or direct export)
is_enabled = _manager.is_enabled
override = _manager.override
reset = _manager.reset
get_all = _manager.get_all
set_flag = _manager.set
