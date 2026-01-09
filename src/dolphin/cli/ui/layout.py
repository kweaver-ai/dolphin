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

from dolphin.cli.ui.console import StatusBar, Theme, set_active_status_bar


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
        print("Some output...")

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
        """Handle terminal resize event."""
        if not self.enabled:
            return

        # Get new size
        try:
            height, width = self._get_terminal_size()
        except:
            return

        if height == self._terminal_height and width == self._terminal_width:
            return

        old_height = self._terminal_height
        
        # Update dimensions
        self._terminal_height = height
        self._terminal_width = width

        # Re-setup scroll region
        try:
            scroll_bottom = height - self.BOTTOM_RESERVE
            if scroll_bottom >= 5:
                sys.stdout.write(f"\033[1;{scroll_bottom}r")
                self._scroll_region_active = True
            else:
                sys.stdout.write("\033[r")
                self._scroll_region_active = False
        except:
            pass

        # Update Status Bar if active
        if self._status_bar:
            self._status_bar.fixed_row = height - 1

        # Redraw Separator
        if self._scroll_region_active:
            self._draw_separator()
        
        sys.stdout.flush()

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

        # Push existing content up to prevent overlap with fixed region
        sys.stdout.write("\n" * self.BOTTOM_RESERVE)
        
        # Set scroll region: ESC[<top>;<bottom>r
        sys.stdout.write(f"\033[1;{scroll_bottom}r")
        # Move cursor to top of scroll region
        sys.stdout.write("\033[1;1H")
        sys.stdout.flush()
        self._scroll_region_active = True

    def _reset_scroll_region(self) -> None:
        """Reset scroll region to full screen.
        
        This method:
        1. Resets the scroll region to cover the entire terminal
        2. Clears the fixed separator and status bar lines (they are now stale)
        3. Positions cursor at a reasonable location for subsequent output
        """
        if self._scroll_region_active:
            height = self._terminal_height
            
            # Build a single atomic output sequence
            output_parts = [
                "\033[r",          # Reset scroll region to full screen
                "\033[?25h",       # Show cursor
            ]
            
            # Clear the fixed separator line (was at height-2)
            sep_line = height - 2
            if sep_line > 0:
                output_parts.append(f"\033[{sep_line};1H\033[K")
            
            # Clear the fixed status bar line (was at height-1)
            status_line = height - 1
            if status_line > 0:
                output_parts.append(f"\033[{status_line};1H\033[K")
            
            # Clear the bottom line too (height)
            output_parts.append(f"\033[{height};1H\033[K")
            
            # Position cursor at what was the scroll region bottom + 1
            # This is where new output should appear after session ends
            scroll_bottom = height - self.BOTTOM_RESERVE
            cursor_row = scroll_bottom + 1
            if cursor_row > height:
                cursor_row = height
            output_parts.append(f"\033[{cursor_row};1H")
            
            sys.stdout.write("".join(output_parts))
            sys.stdout.flush()
            self._scroll_region_active = False

    def _draw_separator(self) -> None:
        """Draw separator line between content and status area."""
        if not self.enabled:
            return

        height, width = self._get_terminal_size()
        sep_line = height - 2  # Separator at height-2

        # Draw separator with atomic ANSI sequence
        output = (
            f"\0337"                                          # Save cursor (DEC)
            f"\033[{sep_line};1H"                             # Move to separator line
            f"\033[K{Theme.BORDER}{'─' * (width)}{Theme.RESET}" # Clear & Draw
            f"\0338"                                          # Restore cursor (DEC)
        )
        sys.stdout.write(output)
        sys.stdout.flush()

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
        
        # Note: Removed the final print() here - it caused extra blank lines
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
                # Clear the status bar row
                sys.stdout.write("\0337") # Save cursor
                sys.stdout.write(f"\033[{fixed_row};1H\033[K")
                sys.stdout.write("\0338") # Restore cursor
                sys.stdout.flush()
            elif clear:
                # Fallback for inline status bar
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()

    def update_status(self, message: str) -> None:
        """Update status bar message.

        Args:
            message: New status message
        """
        if self._status_bar:
            self._status_bar.update_message(message)

    def display_interrupt_prompt(self) -> None:
        """Display the interrupt prompt UI.

        Shows a formatted prompt indicating execution was interrupted
        and user can provide new input.
        """
        print()
        print(f"{Theme.WARNING}{'━' * 40}{Theme.RESET}")
        print(f"{Theme.WARNING}🛑 Execution interrupted{Theme.RESET}")
        print(f"{Theme.MUTED}Enter new instructions, or press Enter to continue{Theme.RESET}")
        print(f"{Theme.WARNING}{'━' * 40}{Theme.RESET}")

    def display_completion(self, message: str = "Completed") -> None:
        """Display completion message.

        Args:
            message: Completion message to display
        """
        print(f"\n{Theme.SUCCESS}✓ {message}{Theme.RESET}")

    def display_error(self, message: str) -> None:
        """Display error message.

        Args:
            message: Error message to display
        """
        print(f"\n{Theme.ERROR}✗ {message}{Theme.RESET}")

    def display_info(self, message: str) -> None:
        """Display info message.

        Args:
            message: Info message to display
        """
        print(f"{Theme.PRIMARY}ℹ {message}{Theme.RESET}")

    def display_warning(self, message: str) -> None:
        """Display warning message.

        Args:
            message: Warning message to display
        """
        print(f"{Theme.WARNING}⚠ {message}{Theme.RESET}")

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
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

        try:
            return await prompt_conversation(prompt)
        finally:
            # If we are returning to a session, the caller will re-show/hide as needed
            pass
