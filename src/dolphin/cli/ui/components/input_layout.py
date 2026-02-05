"""
Fixed Input Layout Component for Dolphin CLI

Provides a terminal layout with fixed bottom input area and scrollable top content.
"""

import sys
import threading
from typing import Optional

from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.components.status_bar import StatusBar
from dolphin.cli.ui.state import safe_write, safe_print


class FixedInputLayout:
    """
    Terminal layout with fixed bottom input area and scrollable top content.

    Uses ANSI scroll regions to create:

    - Top area: scrollable content output
    - Bottom area: fixed status bar + input prompt

    Usage:
        layout = FixedInputLayout(status_message="Ready")
        layout.start()

        # Print content normally - it scrolls in the top area
        layout.print("Some output...")

        # Get user input from fixed bottom
        user_input = layout.get_input()

        layout.stop()
    """

    # Reserve lines at bottom for: status bar (1) + info line (1) + input prompt (1) + buffer (1)
    BOTTOM_RESERVE = 5

    def __init__(
        self,
        status_message: str = "Ready",
        status_hint: str = "esc to cancel",
        info_line: str = ""
    ):
        self.status_message = status_message
        self.status_hint = status_hint
        self.info_line = info_line
        self._status_bar: Optional[StatusBar] = None
        self._terminal_height = 24
        self._terminal_width = 80
        self._active = False
        self._lock = threading.Lock()

    def _get_terminal_size(self) -> tuple:
        """Get terminal dimensions."""
        try:
            import shutil
            size = shutil.get_terminal_size()
            return size.lines, size.columns
        except Exception:
            return 24, 80

    def _setup_scroll_region(self):
        """Setup ANSI scroll region (top portion of screen)."""
        self._terminal_height, self._terminal_width = self._get_terminal_size()
        scroll_bottom = self._terminal_height - self.BOTTOM_RESERVE

        # Set scroll region: ESC[<top>;<bottom>r
        # This makes only lines 1 to scroll_bottom scrollable
        safe_write(f"\033[1;{scroll_bottom}r")

        # Move cursor to top of scroll region
        safe_write("\033[1;1H")
        safe_write("", flush=True)

    def _draw_fixed_bottom(self):
        """Draw the fixed bottom area (status bar, info, input prompt)."""
        height, width = self._terminal_height, self._terminal_width
        bottom_start = height - self.BOTTOM_RESERVE + 1

        # Save cursor position
        safe_write("\0337")

        # Move to bottom area (outside scroll region)
        safe_write(f"\033[{bottom_start};1H")

        # Clear the bottom lines
        for i in range(self.BOTTOM_RESERVE):
            safe_write(f"\033[{bottom_start + i};1H\033[K")

        # Draw separator line
        safe_write(f"\033[{bottom_start};1H")
        separator = f"{Theme.BORDER}{'─' * (width - 1)}{Theme.RESET}"
        safe_write(separator)

        # Draw info line (if any)
        if self.info_line:
            safe_write(f"\033[{bottom_start + 1};1H")
            safe_write(f"{Theme.MUTED}{self.info_line}{Theme.RESET}")

        # Status bar will be drawn by StatusBar class at bottom_start + 2

        # Input prompt position: bottom_start + 3
        safe_write(f"\033[{bottom_start + 3};1H")
        safe_write(f"{Theme.PRIMARY}>{Theme.RESET} ")

        # Restore cursor to scroll region
        safe_write("\0338")
        safe_write("", flush=True)

    def start(self):
        """Initialize the fixed layout."""
        self._active = True
        self._setup_scroll_region()

        # Clear screen in scroll region
        safe_write("\033[2J\033[1;1H")
        safe_write("", flush=True)

        # Draw fixed bottom
        self._draw_fixed_bottom()

        # Start status bar animation (positioned in fixed bottom area)
        self._status_bar = StatusBar(
            message=self.status_message,
            hint=self.status_hint
        )
        # Don't auto-start - we'll render it manually in the fixed position

    def print(self, text: str):
        """Print text to the scrollable area."""
        if not self._active:
            print(text)
            return

        with self._lock:
            # Save cursor, move to scroll region, print, restore
            safe_write("\0337")
            # Text will print in scroll region and scroll naturally
            print(text)
            safe_write("\0338")
            safe_write("", flush=True)

    def update_status(self, message: str):
        """Update the status bar message."""
        with self._lock:
            self.status_message = message
            if self._status_bar:
                self._status_bar.update_message(message)

    def update_info(self, info: str):
        """Update the info line."""
        with self._lock:
            self.info_line = info
            self._draw_fixed_bottom()

    def stop(self):
        """Restore normal terminal mode."""
        self._active = False

        if self._status_bar:
            self._status_bar.stop(clear=False)
            self._status_bar = None

        # Reset scroll region to full screen
        safe_write("\033[r")
        # Move cursor to bottom
        safe_write(f"\033[{self._terminal_height};1H")
        safe_write("", flush=True)
