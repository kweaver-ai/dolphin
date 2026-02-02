"""
Layout Manager - Terminal layout management with fixed bottom status area.

This module provides the LayoutManager class which manages terminal layouts
with a fixed bottom status area and scrollable content region.

Architecture:
    ┌──────────────────────────────────────────────────────┐
    │   [Scrollable Content Region]                         │  ← Lines 1 to (height - 3)
    │   ✓ Tool output, logs, responses, user input          │
    │   > User input appears here in scroll region          │
    │   ...                                                 │
    └──────────────────────────────────────────────────────┘
    ────────────────────────────────────────────────────────  ← Fixed separator at height-2
    ⠋ Status Bar (animated spinner + timer)                  ← Fixed at height-1

Features:
- ANSI scroll region for content (lines 1 to N-3)
- Fixed separator line between content and status
- Fixed status bar at bottom with spinner animation
- Input prompt appears INSIDE the scroll region (not fixed)
"""

import signal
import os
import sys
from typing import Optional

from dolphin.cli.ui.components import StatusBar
from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.state import set_active_status_bar, _stdout_lock, safe_print, safe_write


def _draw_separator_unsafe(layout_manager: 'LayoutManager', row: Optional[int] = None) -> None:
    """Draw separator line without acquiring lock (module-level helper).
    
    This is a module-level function to allow calling from both LayoutManager
    and its instance methods without lock acquisition issues.
    
    Args:
        layout_manager: LayoutManager instance
        row: Specific row to draw at, or None for default position
    
    Note:
        Caller must hold _stdout_lock before calling this function.
    """
    if not layout_manager.enabled:
        return

    height, width = layout_manager._get_terminal_size()
    sep_line = row if row is not None else (height - layout_manager._current_bottom_reserve + 1)

    # Draw separator with atomic ANSI sequence
    output = (
        f"\0337"                                          # Save cursor (DEC)
        f"\033[{sep_line};1H"                             # Move to separator line
        f"\033[K{Theme.BORDER}{'─' * (width)}{Theme.RESET}" # Clear & Draw
        f"\0338"                                          # Restore cursor (DEC)
    )
    safe_write(output)
    safe_write("", flush=True)


def _should_enable_layout() -> bool:
    """Multi-check to ensure layout is only enabled in correct environments.

    Returns:
        True if the terminal supports advanced layout features
    """
    # Not a TTY
    if not sys.stdout.isatty():
        return False

    # No TERM environment variable
    if not os.environ.get('TERM'):
        return False

    # Running in Jupyter
    if 'ipykernel' in sys.modules:
        return False

    # Running in pytest
    if 'pytest' in sys.modules:
        return False

    # Dumb terminal
    if os.environ.get('TERM') == 'dumb':
        return False

    return True


class LayoutManager:
    """Manages terminal layout with fixed bottom status area.

    Provides a modern CLI experience with:
    - Scrollable content region at top (including user input)
    - Fixed separator line
    - Fixed status bar at bottom

    The layout uses ANSI escape sequences to create scroll regions.
    User input happens INSIDE the scroll region, not in a fixed area.

    Usage:
        layout = LayoutManager(enabled=True)
        layout.start_session("Interactive", "my_agent")

        # During execution
        layout.show_status("Processing your request...")

        # Content prints normally and scrolls
        safe_print("Some output...")

        # End session
        layout.end_session()

    Attributes:
        enabled: Whether layout features are active
        _status_bar: Active StatusBar instance
        _terminal_height: Cached terminal height
        _terminal_width: Cached terminal width
    """

    # Reserve lines at bottom: separator (1) + status bar (1) + buffer (1)
    BOTTOM_RESERVE = 3

    def __init__(self, enabled: bool = True):
        """Initialize layout manager.

        Args:
            enabled: Enable layout features (auto-disabled if terminal unsupported)
        """
        self.enabled = enabled and _should_enable_layout()
        self._status_bar: Optional[StatusBar] = None
        self._terminal_height = 24
        self._terminal_width = 80
        self._scroll_region_active = False
        self._session_active = False
        self._original_sigwinch_handler = None
        
        # New: Tracking dynamic reserve
        self._current_bottom_reserve = self.BOTTOM_RESERVE
        self._plan_panel_height = 0
        
        # Resize handling: defer actual processing to prevent race with animation
        self._resize_pending = False
        self._pending_height = 0
        self._pending_width = 0
        
        # Note: _stdout_lock is imported from state.py for consistency with
        # StatusBar and LivePlanCard components. This prevents race conditions
        # where different locks protect concurrent stdout operations.

    def _get_terminal_size(self) -> tuple:
        """Get terminal dimensions.

        Returns:
            Tuple of (height, width)
        """
        try:
            import shutil
            size = shutil.get_terminal_size()
            return size.lines, size.columns
        except Exception:
            return 24, 80

    def _handle_resize(self, signum, frame):
        """Handle terminal resize event.
        
        Note: This is called from signal handler context, so we defer
        actual processing to the next UI operation to prevent interference
        with LivePlanCard animation thread (avoid cursor save/restore race).
        """
        try:
            if not self.enabled:
                return

            # Get new size
            try:
                height, width = self._get_terminal_size()
            except Exception:
                return

            if height == self._terminal_height and width == self._terminal_width:
                return

            # Defer processing: just set flag and pending dimensions
            self._resize_pending = True
            self._pending_height = height
            self._pending_width = width

        except Exception:
            # Signal handlers should never raise exceptions
            # This prevents potential crashes during resize
            pass

    def _process_pending_resize(self):
        """Process deferred resize operation.
        
        This should be called from UI operations (not signal handler context)
        to safely update terminal state.
        """
        if not self._resize_pending:
            return

        self._resize_pending = False
        height = self._pending_height
        width = self._pending_width

        if height == self._terminal_height and width == self._terminal_width:
            return

        old_height = self._terminal_height
        
        # Update dimensions
        self._terminal_height = height
        self._terminal_width = width

        # Re-setup scroll region with lock protection
        try:
            with _stdout_lock:
                scroll_bottom = height - self._current_bottom_reserve
                if scroll_bottom >= 5:
                    safe_write(f"\033[1;{scroll_bottom}r")
                    self._scroll_region_active = True
                else:
                    safe_write("\033[r")
                    self._scroll_region_active = False

                # Update Status Bar if active
                if self._status_bar:
                    self._status_bar.fixed_row = height - 1

                # Redraw Separator
                if self._scroll_region_active:
                    _draw_separator_unsafe(self)
                
                safe_write("", flush=True)
        except:
            pass

    def _setup_scroll_region(self) -> None:
        """Setup ANSI scroll region (top portion of screen)."""
        if not self.enabled:
            return

        self._terminal_height, self._terminal_width = self._get_terminal_size()
        scroll_bottom = self._terminal_height - self.BOTTOM_RESERVE

        if scroll_bottom < 5:
            # Terminal too small, disable layout
            self.enabled = False
            return

        with _stdout_lock:
            # Push existing content up to prevent overlap with fixed region
            safe_write("\n" * self.BOTTOM_RESERVE)
            
            # Set scroll region: ESC[<top>;<bottom>r
            safe_write(f"\033[1;{scroll_bottom}r")
            # Move cursor to top of scroll region
            safe_write("\033[1;1H")
            safe_write("", flush=True)
        self._scroll_region_active = True

    def _reset_scroll_region(self) -> None:
        """Reset scroll region to full screen.
        
        This method:
        1. Resets the scroll region to cover the entire terminal
        2. Clears the fixed separator and status bar lines (they are now stale)
        3. Positions cursor at a reasonable location for subsequent output
        """
        with _stdout_lock:
            if self._scroll_region_active:
                height = self._terminal_height
                
            # Build a single atomic output sequence
            output_parts = [
                "\033[r",          # Reset scroll region to full screen
                "\033[?25h",       # Show cursor
            ]
            
            # Clear the entire reserved bottom area
            for i in range(self._terminal_height - self._current_bottom_reserve, self._terminal_height + 1):
                if i > 0:
                    output_parts.append(f"\033[{i};1H\033[K")
            
            # Position cursor at the end of the previous scroll region
            cursor_row = self._terminal_height - self._current_bottom_reserve + 1
            if cursor_row > self._terminal_height:
                cursor_row = self._terminal_height
            output_parts.append(f"\033[{cursor_row};1H")
            
            safe_write("".join(output_parts))
            safe_write("", flush=True)
            
        self._scroll_region_active = False
        self._current_bottom_reserve = self.BOTTOM_RESERVE
        self._plan_panel_height = 0

    def _draw_separator(self, row: Optional[int] = None) -> None:
        """Draw separator line at specific or default position."""
        if not self.enabled:
            return

        with _stdout_lock:
            _draw_separator_unsafe(self, row)

    def _draw_separator_internal(self, row: Optional[int] = None) -> None:
        """Internal method - deprecated, use _draw_separator instead."""
        self._draw_separator(row)

    def update_layout_for_plan(self, active: bool, height: int = 10) -> None:
        """Dynamically adjust layout to accommodate a Plan Panel.

        Args:
            active: Whether plan panel is active
            height: Desired height for the plan panel
        """
        # Process any pending resize first (safe context, not signal handler)
        self._process_pending_resize()
        
        if not self.enabled:
            return

        new_plan_height = height if active else 0
        if new_plan_height == self._plan_panel_height:
            return

        old_plan_height = self._plan_panel_height
        self._plan_panel_height = new_plan_height

        # Reserve = Plan Panel + Separator (1) + Current Reserve
        self._current_bottom_reserve = self.BOTTOM_RESERVE + self._plan_panel_height

        # Apply new scroll region
        height_total, _ = self._get_terminal_size()
        scroll_bottom = height_total - self._current_bottom_reserve

        if scroll_bottom < 5:
            # Fallback if screen too small
            self._current_bottom_reserve = self.BOTTOM_RESERVE
            scroll_bottom = height_total - self._current_bottom_reserve

        with _stdout_lock:
            # Build the complete atomic sequence for activating plan panel
            output_parts = []

            # CRITICAL: When activating plan panel (old=0, new>0), push content up first
            if old_plan_height == 0 and new_plan_height > 0:
                # Calculate old scroll region
                old_scroll_bottom = height_total - self.BOTTOM_RESERVE

                # Step 1: Ensure current scroll region is set correctly
                # (defensive: in case it was changed elsewhere)
                output_parts.append(f"\033[1;{old_scroll_bottom}r")

                # Step 2: Move to the bottom of current scroll region
                output_parts.append(f"\033[{old_scroll_bottom};1H")

                # Step 3: Output newlines to push content up
                # Each newline at the bottom of scroll region triggers a scroll
                output_parts.append("\n" * new_plan_height)

            # Step 4: Set the new scroll region (with expanded reserve for plan panel)
            output_parts.append(f"\033[1;{scroll_bottom}r")

            # Step 5: If we just activated the panel, position cursor at bottom of new scroll region
            # This ensures subsequent output appears in the right place
            if old_plan_height == 0 and new_plan_height > 0:
                output_parts.append(f"\033[{scroll_bottom};1H")

            # Execute all commands atomically
            if output_parts:
                safe_write("".join(output_parts))
                safe_write("", flush=True)

            # Draw separator (this handles its own cursor save/restore)
            _draw_separator_unsafe(self)

    def get_plan_panel_range(self) -> Optional[tuple]:
        """Get the vertical row range for the plan panel.
        
        Returns:
            Tuple of (start_row, end_row) or None
        """
        if not self.enabled or self._plan_panel_height == 0:
            return None
            
        height, _ = self._get_terminal_size()
        # Separator is at height - reserver + 1
        # Start is one line below separator
        start = height - self._current_bottom_reserve + 2
        end = height - self.BOTTOM_RESERVE
        return (start, end)

    def start_session(self, mode: str, agent_name: str) -> None:
        """Start a new session with the layout.

        This displays the session banner and initializes the layout.

        Args:
            mode: Session mode (e.g., "Interactive", "Execution")
            agent_name: Name of the agent being run
        """
        self._session_active = True

        if self.enabled:
            # Register resize handler
            if hasattr(signal, 'SIGWINCH'):
                self._original_sigwinch_handler = signal.signal(signal.SIGWINCH, self._handle_resize)

            self._setup_scroll_region()
            # Initial separator
            self._draw_separator()

    def end_session(self) -> None:
        """End the current session and cleanup."""
        self._session_active = False

        # Restore original signal handler
        if hasattr(signal, 'SIGWINCH') and self._original_sigwinch_handler:
            signal.signal(signal.SIGWINCH, self._original_sigwinch_handler)
            self._original_sigwinch_handler = None

        # Stop status bar if running
        self.hide_status()

        # Reset terminal state
        self._reset_scroll_region()
        
        # Note: Removed the final safe_print() here - it caused extra blank lines
        # The _reset_scroll_region already positions cursor properly

    def show_status(
        self,
        message: str = "Processing",
        hint: str = "esc to interrupt"
    ) -> StatusBar:
        """Show animated status bar at fixed bottom position.

        Args:
            message: Status message to display
            hint: Hint text (shown in parentheses)

        Returns:
            The StatusBar instance
        """
        # Process any pending resize first (safe context, not signal handler)
        self._process_pending_resize()
        
        # Stop existing status bar
        if self._status_bar:
            self._status_bar.stop(clear=True)

        # Calculate fixed row for status bar
        fixed_row = None
        if self.enabled and self._scroll_region_active:
            height, _ = self._get_terminal_size()
            fixed_row = height - 1  # Status bar at height-1 (bottom)
        
        StatusBar._debug_log(f"LayoutManager.show_status: enabled={self.enabled}, scroll_active={self._scroll_region_active}, fixed_row={fixed_row}")
        
        self._status_bar = StatusBar(message=message, hint=hint, fixed_row=fixed_row)
        self._status_bar.start()
        
        # Register with global coordinator for LivePlanCard coordination
        set_active_status_bar(self._status_bar)
        
        return self._status_bar

    def hide_status(self, clear: bool = True) -> None:
        """Hide the status bar.

        Args:
            clear: Whether to clear the status bar line
        """
        if self._status_bar:
            # Check if we were using fixed row
            fixed_row = self._status_bar.fixed_row
            
            self._status_bar.stop(clear=False)
            self._status_bar = None
            
            # Unregister from global coordinator
            set_active_status_bar(None)
            
            if clear and fixed_row is not None:
                with _stdout_lock:
                    # Clear the status bar row
                    safe_write("\0337") # Save cursor
                    safe_write(f"\033[{fixed_row};1H\033[K")
                    safe_write("\0338") # Restore cursor
                    safe_write("", flush=True)
            elif clear:
                with _stdout_lock:
                    # Fallback for inline status bar
                    safe_write("\r\033[K")
                    safe_write("", flush=True)

    def update_status(self, message: str) -> None:
        """Update status bar message.

        Args:
            message: New status message
        """
        # Process any pending resize first (safe context, not signal handler)
        self._process_pending_resize()
        
        if self._status_bar:
            self._status_bar.update_message(message)

    def display_interrupt_prompt(self) -> None:
        """Display the interrupt prompt UI.

        Shows a formatted prompt indicating execution was interrupted
        and user can provide new input.
        """
        with _stdout_lock:
            safe_print()
            safe_print(f"{Theme.WARNING}{'━' * 40}{Theme.RESET}")
            safe_print(f"{Theme.WARNING}🛑 Execution interrupted{Theme.RESET}")
            safe_print(f"{Theme.MUTED}Enter new instructions, or press Enter to continue{Theme.RESET}")
            safe_print(f"{Theme.WARNING}{'━' * 40}{Theme.RESET}")

    def display_completion(self, message: str = "Completed") -> None:
        """Display completion message.

        Args:
            message: Completion message to display
        """
        with _stdout_lock:
            safe_print(f"\n{Theme.SUCCESS}✓ {message}{Theme.RESET}")

    def display_error(self, message: str) -> None:
        """Display error message.

        Args:
            message: Error message to display
        """
        with _stdout_lock:
            safe_print(f"\n{Theme.ERROR}✗ {message}{Theme.RESET}")

    def display_info(self, message: str) -> None:
        """Display info message.

        Args:
            message: Info message to display
        """
        with _stdout_lock:
            safe_print(f"{Theme.PRIMARY}ℹ {message}{Theme.RESET}")

    def display_warning(self, message: str) -> None:
        """Display warning message.

        Args:
            message: Warning message to display
        """
        with _stdout_lock:
            safe_print(f"{Theme.WARNING}⚠ {message}{Theme.RESET}")

    async def get_user_input(self, prompt: str = "> ") -> str:
        """Get user input asynchronously.

        This uses prompt_toolkit for async input with proper terminal handling.
        Input happens INSIDE the scroll region, not in a fixed area.

        Args:
            prompt: Input prompt string

        Returns:
            User input string
        """
        from dolphin.cli.ui.input import prompt_conversation

        # Hide status bar during input
        if self._status_bar:
            self._status_bar.stop(clear=True)

        # Ensure cursor is visible for input
        safe_write("\033[?25h")
        safe_write("", flush=True)

        try:
            return await prompt_conversation(prompt)
        finally:
            # If we are returning to a session, the caller will re-show/hide as needed
            pass
