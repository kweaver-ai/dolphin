"""
Plan Card Component - Live-updating Plan Card with animated spinner.

This component provides a visually appealing terminal UI for displaying
plan task progress with animated spinners and real-time updates.
"""

import sys
import threading
import time
import unicodedata
from typing import Any, Dict, Optional, List

from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.state import _stdout_lock, set_active_plan_card, safe_write


class LivePlanCard:
    """
    Live-updating Plan Card with animated spinner.

    Uses ANSI cursor control to refresh the entire card area
    while maintaining the spinner animation.

    Note: This class coordinates with StatusBar to prevent concurrent
    animation conflicts. When LivePlanCard starts, it pauses any active
    StatusBar and resumes it when stopped.
    """

    # Color theme (Teal/Cyan)
    PLAN_PRIMARY = "\033[38;5;44m"
    PLAN_ACCENT = "\033[38;5;80m"
    PLAN_MUTED = "\033[38;5;242m"

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, fixed_row_start: Optional[int] = None):
        self.running = False
        self.paused = False
        self.fixed_row_start = fixed_row_start
        self.thread: Optional[threading.Thread] = None
        self.frame_index = 0
        self.tasks: List[Dict[str, Any]] = []
        self.current_task_id: Optional[int] = None
        self.current_action: Optional[str] = None
        self.current_task_content: Optional[str] = None
        self.start_time: float = 0
        self._lines_printed = 0
        self._lock = threading.RLock()

    def _get_visual_width(self, text: str) -> int:
        """Calculate visual width handling CJK and ANSI codes."""
        clean_text = ""
        skip = False
        for char in text:
            if char == "\033":
                skip = True
            if not skip:
                clean_text += char
            if skip and char == "m":
                skip = False

        width = 0
        for char in clean_text:
            if unicodedata.east_asian_width(char) in ("W", "F", "A"):
                width += 2
            else:
                width += 1
        return width

    def _get_terminal_width(self) -> int:
        try:
            import shutil
            return shutil.get_terminal_size().columns
        except Exception:
            return 80

    def _build_card_lines(self) -> List[str]:
        """Build all lines of the plan card for rendering."""
        lines = []

        width = min(80, self._get_terminal_width() - 8)
        if width < 40:
            width = 40

        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.get("status") in ("completed", "done", "success"))

        # Header
        title = "Plan Update"
        progress = f"{completed}/{total}"
        header_text = f"  📋 {title}"
        v_header_w = self._get_visual_width(header_text)
        v_progress_w = self._get_visual_width(progress)
        header_padding = width - v_header_w - v_progress_w - 4

        lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_TOP_LEFT}{Theme.BOX_HORIZONTAL * width}{Theme.BOX_TOP_RIGHT}{Theme.RESET}")
        lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{Theme.BOLD}{header_text}{Theme.RESET}{' ' * max(0, header_padding)}{self.PLAN_ACCENT}{progress}{Theme.RESET}  {self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")
        lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.BOX_HORIZONTAL * width}{Theme.BOX_VERTICAL}{Theme.RESET}")

        # Task list with animated spinner
        current_frame = self.SPINNER_FRAMES[self.frame_index % len(self.SPINNER_FRAMES)]

        for i, task in enumerate(self.tasks):
            content = task.get("content", task.get("name", f"Task {i+1}"))
            status = task.get("status", "pending").lower()

            # Truncate content
            max_v_content = width - 10
            v_content = self._get_visual_width(content)
            if v_content > max_v_content:
                content = content[:int(max_v_content / 1.5)] + "..."

            # Determine icon and color
            is_current = (self.current_task_id is not None and i + 1 == self.current_task_id)

            if is_current and status in ("pending", "running", "in_progress"):
                icon, color = current_frame, self.PLAN_PRIMARY
            elif status in ("completed", "done", "success"):
                icon, color = "●", Theme.SUCCESS
            elif status in ("running", "in_progress"):
                icon, color = current_frame, self.PLAN_PRIMARY
            else:
                icon, color = "○", Theme.MUTED

            if is_current:
                task_line = f"  {color}{icon}{Theme.RESET} {Theme.BOLD}{content}{Theme.RESET}"
                indicator = f" {self.PLAN_PRIMARY}←{Theme.RESET}"
            else:
                task_line = f"  {color}{icon}{Theme.RESET} {content}"
                indicator = ""

            v_line_w = self._get_visual_width(task_line)
            v_indicator_w = self._get_visual_width(indicator)
            padding = width - v_line_w - v_indicator_w - 1

            lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{task_line}{indicator}{' ' * max(0, padding)}{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")

        # Footer with action and elapsed time
        if self.current_action and self.current_task_id:
            action_icons = {"create": "📝", "start": "▶", "done": "✓", "pause": "⏸", "skip": "⏭"}
            action_icon = action_icons.get(self.current_action, "•")

            lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.BOX_HORIZONTAL * width}{Theme.BOX_VERTICAL}{Theme.RESET}")

            if self.current_task_content:
                action_text = f"  {action_icon} Task {self.current_task_id}: {self.current_task_content}"
            else:
                action_text = f"  {action_icon} Task {self.current_task_id}"

            v_action_w = self._get_visual_width(action_text)
            if v_action_w > width - 4:
                action_text = action_text[:int((width - 6) / 1.5)] + "..."
                v_action_w = self._get_visual_width(action_text)

            padding = width - v_action_w - 1
            lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{self.PLAN_ACCENT}{action_text}{Theme.RESET}{' ' * max(0, padding)}{self.PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")

        # Bottom border with timer and dynamic status
        elapsed = int(time.time() - self.start_time)

        # Determine status based on task completion
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.get("status") in ("completed", "done", "success"))

        if completed == total and total > 0:
            status_text = "completed"
            status_color = Theme.SUCCESS
        else:
            status_text = "running"
            status_color = Theme.MUTED

        timer_text = f" {elapsed}s • {status_text} "
        # Build timer text with color
        colored_timer = f"{Theme.MUTED}{elapsed}s • {status_color}{status_text}{Theme.MUTED} {Theme.RESET}"
        v_timer_w = self._get_visual_width(timer_text)  # Use plain text for width calculation
        left_len = (width - v_timer_w) // 2
        right_len = width - v_timer_w - left_len
        lines.append(f"{self.PLAN_PRIMARY}{Theme.BOX_BOTTOM_LEFT}{Theme.BOX_HORIZONTAL * left_len}{Theme.RESET}{colored_timer}{self.PLAN_PRIMARY}{Theme.BOX_HORIZONTAL * right_len}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}")

        return lines

    def _animate(self):
        """Background thread animation loop."""
        while self.running:
            with self._lock:
                if not self.paused:
                    lines = self._build_card_lines()

                    with _stdout_lock:
                        if self.fixed_row_start:
                            # ABSOLUTE POSITIONING: Gamma-tier stability
                            output_parts = ["\0337"]  # Save cursor
                            for i, line in enumerate(lines):
                                # Move to exact row, column 1
                                output_parts.append(f"\033[{self.fixed_row_start + i};1H\033[K{line}")
                            output_parts.append("\0338")  # Restore cursor
                            safe_write("".join(output_parts))
                        else:
                            # Fallback to relative (fragile, used if no LayoutManager)
                            if self._lines_printed > 0:
                                safe_write(f"\033[{self._lines_printed}A")
                                max_lines = max(self._lines_printed, len(lines))
                                for _ in range(max_lines):
                                    safe_write("\033[K\n")
                                safe_write(f"\033[{max_lines}A")

                            output = "".join(f"{line}\n" for line in lines)
                            safe_write(output)

                        safe_write("", flush=True)

                    self._lines_printed = len(lines)

            self.frame_index += 1
            time.sleep(0.12)

    def start(
        self,
        tasks: List[Dict[str, Any]],
        current_task_id: Optional[int] = None,
        current_action: Optional[str] = None,
        current_task_content: Optional[str] = None,
        fixed_row_start: Optional[int] = None
    ):
        """Start the live card animation."""
        if self.running:
            self.stop()

        self.tasks = tasks
        self.current_task_id = current_task_id
        self.current_action = current_action
        self.current_task_content = current_task_content
        self.fixed_row_start = fixed_row_start
        self.start_time = time.time()
        self.frame_index = 0
        self._lines_printed = 0
        self.paused = False

        set_active_plan_card(self)

        with _stdout_lock:
            if not self.fixed_row_start:
                safe_write("\n")

            lines = self._build_card_lines()

            if self.fixed_row_start:
                output_parts = ["\0337"]
                for i, line in enumerate(lines):
                    output_parts.append(f"\033[{self.fixed_row_start + i};1H\033[K{line}")
                output_parts.append("\0338")
                safe_write("".join(output_parts))
            else:
                for line in lines:
                    safe_write(f"{line}\n")
            safe_write("", flush=True)

        self._lines_printed = len(lines)
        self.running = True
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def pause(self) -> None:
        """Pause the animation.

        If in fixed mode, we DON'T clear the screen as it's not in the way.
        This provides flicker-free concurrent output.
        """
        with self._lock:
            if not self.paused:
                self.paused = True
                if not self.fixed_row_start:
                    # Only clear if we are inline and potentially in the way
                    with _stdout_lock:
                        if self._lines_printed > 0:
                            safe_write(f"\033[{self._lines_printed}A")
                            for _ in range(self._lines_printed):
                                safe_write("\033[K\n")
                            safe_write(f"\033[{self._lines_printed}A")
                        safe_write("", flush=True)
                        self._lines_printed = 0

    def resume(self) -> None:
        """Resume the animation."""
        with self._lock:
            if self.paused:
                self.paused = False
                if self.fixed_row_start:
                    return # Already there

                # Re-print card if inline
                with _stdout_lock:
                    lines = self._build_card_lines()
                    for line in lines:
                        safe_write(f"{line}\n")
                    safe_write("", flush=True)
                self._lines_printed = len(lines)

    def update(
        self,
        tasks: Optional[List[Dict[str, Any]]] = None,
        current_task_id: Optional[int] = None,
        current_action: Optional[str] = None,
        current_task_content: Optional[str] = None
    ):
        """Update the card data (thread-safe)."""
        with self._lock:
            if tasks is not None:
                self.tasks = tasks
            if current_task_id is not None:
                self.current_task_id = current_task_id
            if current_action is not None:
                self.current_action = current_action
            if current_task_content is not None:
                self.current_task_content = current_task_content

    def stop(self):
        """Stop the animation and clear the card."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)

        set_active_plan_card(None)

        with self._lock:
            with _stdout_lock:
                # Handle fixed row mode (absolute positioning)
                if self.fixed_row_start is not None:
                    # Fixed row mode: move to fixed row and clear
                    for row in range(self.fixed_row_start, self.fixed_row_start + self._lines_printed):
                        safe_write(f"\033[{row};0H\033[K")  # Move to row and clear
                    safe_write("", flush=True)
                elif self._lines_printed > 0:
                    # Relative mode: existing logic
                    safe_write(f"\033[{self._lines_printed}A")
                    for _ in range(self._lines_printed):
                        safe_write("\033[K\n")
                    safe_write(f"\033[{self._lines_printed}A")
                    safe_write("", flush=True)

                self._lines_printed = 0
