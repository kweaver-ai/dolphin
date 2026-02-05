"""
Spinner Component for Dolphin CLI

Provides animated spinner for indicating long-running operations.
"""

import sys
import threading
import time
from typing import Dict, List, Optional

from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.state import _stdout_lock, safe_write, safe_print


class Spinner:
    """Animated spinner for long-running operations.

    Uses the global _stdout_lock to prevent output conflicts with
    other threads writing to stdout.
    """

    def __init__(self, message: str = "Processing", position_updates: Optional[List[Dict[str, int]]] = None):
        """
        Args:
            message: Text to display alongside the bottom spinner.
            position_updates: Optional list of relative positions to update synchronously.
                              Each dict should have 'up' (lines up) and 'col' (column index).
                              Example: [{'up': 5, 'col': 4}] updates the character 5 lines up at col 4.
        """
        self.message = message
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.frame_index = 0
        self.position_updates = position_updates or []

    def _animate(self):
        frames = Theme.BOX_SPINNER_FRAMES
        while self.running:
            frame = frames[self.frame_index % len(frames)]

            # Use global lock to prevent conflicts with main thread output
            with _stdout_lock:
                # Build the entire output as a single string for atomic write
                output_parts = []

                # 1. Bottom line spinner
                output_parts.append(f"\r{Theme.PRIMARY}{frame}{Theme.RESET} {Theme.LABEL}{self.message}{Theme.RESET}")

                # 2. Update remote positions (e.g., Box Header) if any
                if self.position_updates:
                    # Save cursor position (DEC sequence \0337 is widely supported)
                    output_parts.append("\0337")

                    for pos in self.position_updates:
                        lines_up = pos.get('up', 0)
                        column = pos.get('col', 0)
                        if lines_up > 0:
                            # Move up N lines, then move to specific column
                            # \033[NA (Up), \033[MG (Column M)
                            output_parts.append(f"\033[{lines_up}A\033[{column}G")
                            output_parts.append(f"{Theme.PRIMARY}{frame}{Theme.RESET}")

                    # Restore cursor position (DEC sequence \0338)
                    output_parts.append("\0338")

                # Single atomic write
                safe_write("".join(output_parts))
                safe_write("", flush=True)

            self.frame_index += 1
            time.sleep(0.08)

        # Clear the bottom line when done (also protected by lock)
        with _stdout_lock:
            safe_write("\r" + " " * (len(self.message) + 10) + "\r")
            safe_write("", flush=True)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def stop(self, success: bool = True):
        """Stop the spinner and optionally update remote positions with a completion icon."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)

        # Update remote positions with a static completion icon
        if self.position_updates:
            # Choose icon based on success status
            completion_icon = "●" if success else "✗"
            completion_color = Theme.SUCCESS if success else Theme.ERROR

            safe_write("\0337")  # Save cursor
            for pos in self.position_updates:
                lines_up = pos.get('up', 0)
                column = pos.get('col', 0)
                if lines_up > 0:
                    safe_write(f"\033[{lines_up}A\033[{column}G")
                    safe_write(f"{completion_color}{completion_icon}{Theme.RESET}")
            safe_write("\0338")  # Restore cursor
            safe_write("", flush=True)
