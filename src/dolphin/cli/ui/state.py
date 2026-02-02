"""
Global State Management for UI Components

This module manages global state for UI components including:
- Thread synchronization lock for stdout
- Active component tracking (StatusBar, LivePlanCard)
- Component pause/resume coordination
"""

import threading
from contextlib import contextmanager
from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.cli.ui.components.status_bar import StatusBar
    from dolphin.cli.ui.components.plan_card import LivePlanCard


# ─────────────────────────────────────────────────────────────
# Global stdout coordination lock
# Prevents race conditions between spinner threads and main output
# ─────────────────────────────────────────────────────────────
_stdout_lock = threading.RLock()


def safe_write(text: str, flush: bool = True) -> None:
    """Thread-safe stdout write.
    
    Use this instead of sys.stdout.write() when outputting text
    that might conflict with spinner animations.
    
    Args:
        text: Text to write to stdout
        flush: Whether to flush after writing
    """
    import sys
    with _stdout_lock:
        sys.stdout.write(text)
        if flush:
            sys.stdout.flush()


def safe_print(*args, **kwargs) -> None:
    """Thread-safe print function.
    
    Use this instead of print() when outputting text
    that might conflict with spinner animations.
    """
    with _stdout_lock:
        print(*args, **kwargs)


# ─────────────────────────────────────────────────────────────
# Global StatusBar Coordination
# Prevents concurrent animations from conflicting with each other
# ─────────────────────────────────────────────────────────────
_active_status_bar: Optional['StatusBar'] = None
_active_plan_card: Optional['LivePlanCard'] = None


def _pause_active_components() -> List[Any]:
    """Pause all active live UI components (StatusBar, LivePlanCard).

    Returns:
        List of paused components to resume later.
    """
    paused = []

    # Pause Status Bar
    global _active_status_bar
    if _active_status_bar and _active_status_bar.running and not _active_status_bar.paused:
        _active_status_bar.pause()
        paused.append(_active_status_bar)
        # Debug log - import locally to avoid circular dependency
        from dolphin.cli.ui.components.status_bar import StatusBar
        StatusBar._debug_log("Paused active StatusBar")

    # Pause Plan Card
    global _active_plan_card
    if _active_plan_card and _active_plan_card.running and not _active_plan_card.paused:
        _active_plan_card.pause()
        paused.append(_active_plan_card)
        # Debug log
        from dolphin.cli.ui.components.status_bar import StatusBar
        StatusBar._debug_log("Paused active LivePlanCard")

    return paused


def _resume_components(components: List[Any]) -> None:
    """Resume previously paused components.

    Args:
        components: List of components to resume.
    """
    for comp in components:
        if hasattr(comp, 'resume'):
            comp.resume()
            # Debug log - import locally to avoid circular dependency
            from dolphin.cli.ui.components.status_bar import StatusBar
            StatusBar._debug_log(f"Resumed {type(comp).__name__}")


def _pause_active_status_bar() -> Optional['StatusBar']:
    """Pause the active status bar if one exists.

    Uses pause() instead of stop() so the timer continues running.

    Returns:
        The paused StatusBar instance (to resume later), or None
    """
    global _active_status_bar
    # Debug log - import locally to avoid circular dependency
    from dolphin.cli.ui.components.status_bar import StatusBar
    StatusBar._debug_log(f"_pause_active_status_bar: called, _active_status_bar={_active_status_bar is not None}, running={_active_status_bar.running if _active_status_bar else 'N/A'}")
    if _active_status_bar and _active_status_bar.running:
        _active_status_bar.pause()
        StatusBar._debug_log(f"_pause_active_status_bar: paused StatusBar")
        return _active_status_bar
    return None


def _resume_status_bar(status_bar: Optional['StatusBar']) -> None:
    """Resume a previously paused status bar.

    Args:
        status_bar: The StatusBar instance to resume
    """
    # Debug log - import locally to avoid circular dependency
    from dolphin.cli.ui.components.status_bar import StatusBar
    StatusBar._debug_log(f"_resume_status_bar: called, status_bar={status_bar is not None}, running={status_bar.running if status_bar else 'N/A'}")
    if status_bar and status_bar.running:
        status_bar.resume()
        StatusBar._debug_log(f"_resume_status_bar: resumed StatusBar")


def set_active_status_bar(status_bar: Optional['StatusBar']) -> None:
    """Register the active status bar for coordination.

    Args:
        status_bar: The StatusBar instance to track
    """
    global _active_status_bar
    _active_status_bar = status_bar


def set_active_plan_card(plan_card: Optional['LivePlanCard']) -> None:
    """Register the active plan card for coordination.

    Args:
        plan_card: The LivePlanCard instance to track
    """
    global _active_plan_card
    _active_plan_card = plan_card


@contextmanager
def pause_status_bar_context():
    """Context manager to pause and resume live UI components.

    Use this to wrap any code that outputs content to the terminal
    to prevent Live UI animations from conflicting with the output.
    """
    paused = _pause_active_components()
    try:
        yield
    finally:
        _resume_components(paused)


# Export the lock for use by components
__all__ = [
    '_stdout_lock',
    '_active_status_bar',
    '_active_plan_card',
    'set_active_status_bar',
    'set_active_plan_card',
    'pause_status_bar_context',
    '_pause_active_status_bar',
    '_resume_status_bar',
    '_pause_active_components',
    '_resume_components',
    'safe_print',
    'safe_write',
]
