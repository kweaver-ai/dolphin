"""Utilities for safe Rich status rendering.

Rich's live rendering (including Console.status) may block in non-interactive
environments. This module provides an opt-in wrapper that degrades to a no-op
status object when Rich rendering isn't safe.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Protocol

from rich.console import Console


class StatusLike(Protocol):
    """Minimal interface used by callers of Console.status()."""

    def update(self, *_args: Any, **_kwargs: Any) -> None: ...


class _NoopStatus:
    def update(self, *_args: Any, **_kwargs: Any) -> None:
        return


@contextmanager
def safe_rich_status(
    message: str,
    *,
    console: Optional[Console] = None,
    enable_env_var: str = "DOLPHIN_ENABLE_RICH_STATUS",
) -> Iterator[StatusLike]:
    """Yield a Rich status spinner only when explicitly enabled and safe.

    Rules:
    - Opt-in via env var (default: DOLPHIN_ENABLE_RICH_STATUS=1)
    - Require a real TTY (stderr or stdout)
    - Require Console.is_terminal
    - Never raise; fall back to a no-op status object
    """
    if os.environ.get(enable_env_var) != "1":
        yield _NoopStatus()
        return

    stderr_isatty = getattr(sys.stderr, "isatty", lambda: False)()
    stdout_isatty = getattr(sys.stdout, "isatty", lambda: False)()
    if not (stderr_isatty or stdout_isatty):
        yield _NoopStatus()
        return

    try:
        active_console = console or Console()
        if not getattr(active_console, "is_terminal", False):
            yield _NoopStatus()
            return
        with active_console.status(message) as status:
            yield status
    except Exception:
        yield _NoopStatus()

