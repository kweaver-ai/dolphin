"""
StatusBar Component for Dolphin CLI

Provides an animated status bar with spinner, message, and elapsed time.
"""

import os
import sys
import threading
import time
from typing import Optional

from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.state import _stdout_lock, safe_write, safe_print


class StatusBar:
    """
    Animated status bar with spinner, message, and elapsed time.

    Displays a line like:
    ⠋ I'm Feeling Lucky (esc to cancel, 3m 55s)

    Features:
    - Left: animated spinner
    - Center: status message
    - Right: elapsed time counter
    """

    # Spinner frames
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Status bar colors
    STATUS_COLOR = "\033[38;5;214m"  # Orange/gold
    TIME_COLOR = "\033[38;5;245m"    # Gray
    HINT_COLOR = "\033[38;5;242m"    # Dark gray

    # Debug logging
    _DEBUG_LOG_FILE = "/tmp/statusbar_debug.log"
    _DEBUG_ENABLED = os.getenv("DOLPHIN_DEBUG_UI", "").lower() in ("1", "true", "yes")

    @classmethod
    def _debug_log(cls, msg: str) -> None:
        """Write debug message to log file."""
        if cls._DEBUG_ENABLED:
            try:
                with open(cls._DEBUG_LOG_FILE, "a") as f:
                    import datetime
                    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    f.write(f"[{ts}] {msg}\n")
            except Exception:
                pass

    def __init__(self, message: str = "Processing", hint: str = "esc to cancel", fixed_row: Optional[int] = None):
        """Initialize the status bar.

        Args:
            message: Status message to display
            hint: Hint text (shown in parentheses)
            fixed_row: If set, render at this fixed row (1-indexed from top).
                      If None, render at current cursor position.
        """
        self.message = message
        self.hint = hint
        self.fixed_row = fixed_row  # Fixed screen row (1-indexed), or None for inline
        self.running = False
        self.paused = False  # When True, animation continues but no output
        self.thread: Optional[threading.Thread] = None
        self.frame_index = 0
        self.start_time = 0.0
        self._lock = threading.Lock()

        # Log initialization
        self._debug_log(f"StatusBar.__init__: message={message!r}, hint={hint!r}, fixed_row={fixed_row}")

    def _format_elapsed(self, seconds: int) -> str:
        """Format seconds as Xm Ys or Xs."""
        if seconds >= 60:
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}m {secs}s"
        return f"{seconds}s"

    def _build_line(self) -> str:
        """Build the status bar line."""
        frame = self.SPINNER_FRAMES[self.frame_index % len(self.SPINNER_FRAMES)]
        elapsed = int(time.time() - self.start_time)
        elapsed_str = self._format_elapsed(elapsed)

        # Format: ⠋ Message (hint, time)
        line = (
            f"{self.STATUS_COLOR}{frame}{Theme.RESET} "
            f"{self.STATUS_COLOR}{self.message}{Theme.RESET} "
            f"{self.HINT_COLOR}({self.hint}, {self.TIME_COLOR}{elapsed_str}{self.HINT_COLOR}){Theme.RESET}"
        )
        return line

    def _animate(self):
        """Background thread animation loop.

        Uses both the instance lock (self._lock) and global stdout lock (_stdout_lock)
        to coordinate with other threads.
        """
        self._debug_log(f"_animate: THREAD STARTED, fixed_row={self.fixed_row}")
        loop_count = 0
        while self.running:
            loop_count += 1
            with self._lock:
                # Only write output if not paused
                if not self.paused:
                    line = self._build_line()

                    # Ensure line doesn't exceed terminal width to prevent wrapping
                    try:
                        import shutil
                        width = shutil.get_terminal_size().columns
                        # Simplified truncation for extremely long strings
                        if len(line) > width * 3:
                             pass
                    except:
                        pass

                    # Use global stdout lock to prevent conflicts with other output
                    with _stdout_lock:
                        if self.fixed_row is not None:
                            # Fixed position mode: save, move, clear+draw, restore
                            # Combine into SINGLE write to minimize threading conflict
                            output = (
                                f"\0337"                     # Save cursor
                                f"\033[{self.fixed_row};1H"  # Move to fixed row
                                f"\033[K"                    # Clear line
                                f"{line}"                    # Draw content
                                f"\0338"                     # Restore cursor
                            )
                            safe_write(output)
                            if loop_count <= 3:  # Log first few loops
                                self._debug_log(f"_animate: loop={loop_count}, mode=FIXED, row={self.fixed_row}, output_repr={output!r}")
                        else:
                            # Inline mode
                            safe_write(f"\r\033[K{line}")
                            if loop_count <= 3:  # Log first few loops
                                self._debug_log(f"_animate: loop={loop_count}, mode=INLINE, line_len={len(line)}")

                        safe_write("", flush=True)

            self.frame_index += 1
            time.sleep(0.1)

        self._debug_log(f"_animate: THREAD STOPPED after {loop_count} loops")

    def start(self):
        """Start the status bar animation."""
        self._debug_log(f"start: called, fixed_row={self.fixed_row}")
        self.start_time = time.time()
        self.frame_index = 0
        self.running = True
        self.paused = False
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()
        self._debug_log(f"start: thread started")

    def pause(self):
        """Pause the status bar output (thread-safe).

        The animation thread continues running but doesn't write to stdout.
        Call resume() to continue output.
        """
        with self._lock:
            if not self.paused:
                self.paused = True
                # Clear the status bar line (use global lock for stdout)
                with _stdout_lock:
                    if self.fixed_row is not None:
                        # Fixed position mode: clear the fixed row
                        output = (
                            f"\0337"                     # Save cursor
                            f"\033[{self.fixed_row};1H"  # Move to fixed row
                            f"\033[K"                    # Clear line
                            f"\0338"                     # Restore cursor
                        )
                        safe_write(output)
                    else:
                        # Inline mode: clear current line and move to next line
                        # This ensures subsequent output doesn't mix with status bar
                        safe_write("\r\033[K\n")
                    safe_write("", flush=True)

    def resume(self):
        """Resume the status bar output (thread-safe).

        Immediately redraws the status bar to ensure it's visible right away.
        """
        with self._lock:
            self.paused = False
            # Immediately redraw to ensure visibility (use global lock for stdout)
            line = self._build_line()
            with _stdout_lock:
                if self.fixed_row is not None:
                    output = (
                        f"\0337"                     # Save cursor
                        f"\033[{self.fixed_row};1H"  # Move to fixed row
                        f"\033[K"                    # Clear line
                        f"{line}"                    # Draw content
                        f"\0338"                     # Restore cursor
                    )
                    safe_write(output)
                else:
                    # Inline mode: redraw on current line
                    safe_write(f"\r\033[K{line}")
                safe_write("", flush=True)

    def update_message(self, message: str):
        """Update the status message (thread-safe)."""
        with self._lock:
            self.message = message

    def stop(self, clear: bool = True):
        """Stop the status bar animation."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)

        if clear:
            with _stdout_lock:
                # Handle fixed row mode (absolute positioning)
                if self.fixed_row is not None:
                    safe_write(f"\033[{self.fixed_row};0H\033[K")
                else:
                    # Inline mode: clear current line
                    safe_write("\r\033[K")
                safe_write("", flush=True)
