"""
Stream Renderer - CLI Layer for Live Markdown Rendering

This module provides the CLI-layer rendering logic for LLM streaming output.
It is completely separate from the SDK core, allowing the SDK to remain
agnostic to terminal rendering concerns.

Usage:
    renderer = LiveStreamRenderer()
    renderer.start()
    async for item in llm_chat_stream(..., on_stream_chunk=renderer.on_chunk):
        ...
    renderer.stop()
"""

from typing import Optional, Callable


def _is_fixed_layout_active() -> bool:
    """Check if we're using the fixed bottom layout (scroll region is active).
    
    When fixed layout is active, Rich Live is incompatible and should be disabled.
    """
    try:
        from dolphin.cli.ui.console import _active_status_bar
        # If there's an active status bar with a fixed_row, we're in fixed layout mode
        if _active_status_bar and hasattr(_active_status_bar, 'fixed_row'):
            return _active_status_bar.fixed_row is not None
    except ImportError:
        pass
    return False


class LiveStreamRenderer:
    """
    Live Markdown renderer for LLM streaming output.
    
    This class manages Rich's Live component to provide real-time
    Markdown rendering of LLM responses. If Rich is not available,
    or if fixed layout mode is active, it falls back to simple console output.
    
    IMPORTANT: Rich Live is DISABLED when fixed bottom layout is active,
    because Rich Live and ANSI scroll regions are fundamentally incompatible.
    Rich Live takes over terminal control and breaks our scroll region setup.
    """
    
    def __init__(self, verbose: bool = True):
        self._live = None
        self._Markdown = None
        self._verbose = verbose
        self._started = False
        self._rich_available = False
        self._use_simple_mode = False  # True when Rich Live is disabled
        self._paused_status_bar = None  # Track paused status bar for resume
        self._has_output = False  # Track if we've actually output something
        
    def start(self) -> "LiveStreamRenderer":
        """
        Start the Live renderer context.
        
        Returns self for method chaining:
            renderer = LiveStreamRenderer().start()
        """
        if not self._verbose:
            return self
        
        # Pause the status bar to avoid conflicts with streaming output
        try:
            from dolphin.cli.ui.console import _pause_active_status_bar
            self._paused_status_bar = _pause_active_status_bar()
        except ImportError:
            self._paused_status_bar = None
        
        # ALWAYS use simple mode in CLI
        # Rich Live is INCOMPATIBLE with scroll regions and terminal layouts
        # because it takes over terminal control and breaks cursor positioning
        import sys
        if sys.stdout.isatty():
            self._use_simple_mode = True
            self._started = True
            return self
        
        # Non-TTY fallback: try Rich Live (for notebooks, etc.)
        try:
            from rich.live import Live
            from rich.markdown import Markdown
            
            self._Markdown = Markdown
            self._live = Live(
                Markdown(""),
                auto_refresh=True,
                refresh_per_second=10,
                vertical_overflow="visible",
            )
            self._live.start()
            self._rich_available = True
            self._started = True
        except ImportError:
            self._rich_available = False
            self._started = True
            
        return self
    
    def on_chunk(self, chunk_text: str, full_text: str, is_final: bool = False) -> None:
        """
        Callback for each streaming chunk.
        
        Args:
            chunk_text: The new text in this chunk (delta)
            full_text: The complete accumulated text so far
            is_final: Whether this is the final chunk
        """
        if not self._verbose:
            return
        
        if self._use_simple_mode:
            # Line-buffered output with manual ANSI highlighting
            # This provides basic Markdown formatting without Rich Live
            if not hasattr(self, '_line_buffer'):
                self._line_buffer = ""
            
            self._line_buffer += chunk_text
            
            # Process complete lines
            while '\n' in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split('\n', 1)
                self._print_highlighted_line(line)
                self._has_output = True  # Track that we've output something
                
        elif self._rich_available and self._live and self._Markdown:
            # Rich Live mode: update with full Markdown
            self._live.update(self._Markdown(full_text))
        else:
            # Fallback: print incremental text
            print(chunk_text, end="", flush=True)
    
    def _print_highlighted_line(self, line: str) -> None:
        """Print a line with simple ANSI Markdown highlighting."""
        # ANSI codes
        BOLD = "\033[1m"
        RESET = "\033[0m"
        CYAN = "\033[36m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        MAGENTA = "\033[35m"
        BLUE = "\033[34m"
        WHITE = "\033[37m"
        DIM = "\033[2m"
        BG_GRAY = "\033[48;5;236m"  # Dark gray background for code
        
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        
        # Track code block state
        if not hasattr(self, '_in_code_block'):
            self._in_code_block = False
            self._code_lang = ""
        
        # Code block start/end markers
        if stripped.startswith('```'):
            if not self._in_code_block:
                # Starting a code block
                self._in_code_block = True
                self._code_lang = stripped[3:].strip()
                lang_display = f" {self._code_lang}" if self._code_lang else ""
                print(f"{indent}{DIM}╭───{lang_display}{'─' * max(0, 40 - len(lang_display))}╮{RESET}")
            else:
                # Ending a code block
                self._in_code_block = False
                self._code_lang = ""
                print(f"{indent}{DIM}╰{'─' * 44}╯{RESET}")
            return
        
        # Inside code block - render code with special formatting
        if self._in_code_block:
            print(f"{indent}{DIM}│{RESET} {GREEN}{stripped}{RESET}")
            return
        
        # Headers (H1-H6) - check longer prefixes first, remove # prefix for cleaner output
        if stripped.startswith('###### '):
            title = stripped[7:]  # Remove '###### '
            print(f"{indent}{DIM}{title}{RESET}")
        elif stripped.startswith('##### '):
            title = stripped[6:]  # Remove '##### '
            print(f"{indent}{WHITE}{title}{RESET}")
        elif stripped.startswith('#### '):
            title = stripped[5:]  # Remove '#### '
            print(f"{indent}{BLUE}{BOLD}{title}{RESET}")
        elif stripped.startswith('### '):
            title = stripped[4:]  # Remove '### '
            print(f"{indent}{MAGENTA}{BOLD}{title}{RESET}")
        elif stripped.startswith('## '):
            title = stripped[3:]  # Remove '## '
            print(f"{indent}{CYAN}{BOLD}{title}{RESET}")
        elif stripped.startswith('# '):
            title = stripped[2:]  # Remove '# '
            print(f"{indent}{YELLOW}{BOLD}{title}{RESET}")
        # Markdown tables - detect lines with | delimiters
        elif stripped.startswith('|') and stripped.endswith('|'):
            # Check if it's a separator row (|---|---|)
            inner = stripped[1:-1]
            if all(c in '-|: ' for c in inner):
                # Table separator row - render as horizontal line
                cells = inner.split('|')
                rendered_cells = [DIM + '─' * max(3, len(cell.strip())) + RESET for cell in cells]
                print(f"{indent}{DIM}├{'┼'.join(rendered_cells)}┤{RESET}")
            else:
                # Table data row - render with nice borders
                cells = inner.split('|')
                rendered_cells = [self._highlight_inline(cell.strip()) for cell in cells]
                print(f"{indent}{DIM}│{RESET} {f' {DIM}│{RESET} '.join(rendered_cells)} {DIM}│{RESET}")
        # Lists
        elif stripped.startswith('- ') or stripped.startswith('* '):
            bullet = stripped[0]
            content = stripped[2:]
            # Handle inline formatting in content
            content = self._highlight_inline(content)
            print(f"{indent}{GREEN}•{RESET} {content}")
        # Numbered lists
        elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in '.:)':
            num = stripped[0]
            content = stripped[2:].lstrip()
            content = self._highlight_inline(content)
            print(f"{indent}{GREEN}{num}.{RESET} {content}")
        # Regular text with inline formatting
        else:
            print(f"{indent}{self._highlight_inline(stripped)}")
    
    def _highlight_inline(self, text: str) -> str:
        """Highlight inline Markdown: **bold**, `code`, etc."""
        import re
        BOLD = "\033[1m"
        RESET = "\033[0m"
        CYAN = "\033[36m"
        DIM = "\033[2m"
        
        # Replace **text** with bold
        text = re.sub(r'\*\*(.+?)\*\*', f'{BOLD}\\1{RESET}', text)
        # Replace `code` with cyan
        text = re.sub(r'`([^`]+)`', f'{CYAN}\\1{RESET}', text)
        return text
    
    def _highlight_inline_bold(self, text: str) -> str:
        """Highlight **bold** text with ANSI codes. (Legacy, use _highlight_inline instead)"""
        return self._highlight_inline(text)
    
    def stop(self) -> None:
        """Stop the Live renderer and clean up."""
        # Flush any remaining buffer in simple mode
        if self._use_simple_mode and self._started:
            if hasattr(self, '_line_buffer') and self._line_buffer:
                # Print remaining content (may not end with newline)
                self._print_highlighted_line(self._line_buffer)
                self._line_buffer = ""
            # Only add newline if we actually output something
            elif hasattr(self, '_has_output') and self._has_output:
                print()  # End the streaming output with a newline

        if self._live and self._started and not self._use_simple_mode:
            try:
                self._live.stop()
            except Exception:
                pass
        self._started = False
        self._use_simple_mode = False
        self._has_output = False  # Reset for next use
        
        # Resume the status bar that was paused during streaming
        if hasattr(self, '_paused_status_bar') and self._paused_status_bar:
            try:
                from dolphin.cli.ui.console import _resume_status_bar
                _resume_status_bar(self._paused_status_bar)
            except ImportError:
                pass
            self._paused_status_bar = None
        
    def __enter__(self) -> "LiveStreamRenderer":
        """Context manager support."""
        return self.start()
        
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager cleanup."""
        self.stop()


# Convenience function for getting a renderer callback
def create_stream_renderer(verbose: bool = True) -> tuple:
    """
    Create a stream renderer and return (renderer, callback).
    
    Usage:
        renderer, on_chunk = create_stream_renderer()
        renderer.start()
        async for item in llm_chat_stream(..., on_stream_chunk=on_chunk):
            ...
        renderer.stop()
    
    Returns:
        Tuple of (LiveStreamRenderer instance, on_chunk callback)
    """
    renderer = LiveStreamRenderer(verbose=verbose)
    return renderer, renderer.on_chunk
