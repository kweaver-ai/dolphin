"""
Console UI Module - Modern Terminal Display for Dolphin SDK

This module provides a modern, visually appealing terminal UI for displaying
tool calls, skill invocations, and agent interactions. Inspired by Codex CLI
and Claude Code's elegant terminal interfaces.

Features:
- Card-style bordered boxes with Unicode box-drawing characters
- Syntax highlighting for JSON parameters
- Status indicators (running/completed/error)
- Compact yet readable JSON formatting
- Spinner animations for long-running operations
- Harmonious color palette
"""

import ast
import json
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, List


# Import migrated components
from dolphin.cli.ui.theme import Theme, StatusType, BoxStyle
from dolphin.cli.ui.state import (
    _stdout_lock,
    set_active_status_bar,
    set_active_plan_card,
    pause_status_bar_context,
    safe_print,
    safe_write,
)
from dolphin.cli.ui.components import Spinner, StatusBar, LivePlanCard, FixedInputLayout




class ConsoleUI:
    """Modern console UI renderer for Dolphin SDK"""
    
    def __init__(self, style: Optional[BoxStyle] = None, verbose: bool = True):
        self.style = style or BoxStyle()
        self.verbose = verbose
        self._current_spinner: Optional[Spinner] = None
        self._active_skill_spinner: Optional[Spinner] = None  # For skill call animations
        self._paused_status_bar_for_skill: Optional['StatusBar'] = None # Track paused status bar for skill calls
        self._status_bar: Optional[StatusBar] = None  # For status bar animation
    
    def show_status_bar(
        self,
        message: str = "Ready",
        hint: str = "esc to cancel"
    ) -> StatusBar:
        """Show an animated status bar above the input prompt.
        
        Args:
            message: Status message to display
            hint: Hint text (shown in parentheses)
            
        Returns:
            The StatusBar instance (can be used to update message or stop)
        """
        # Stop any existing status bar first
        if self._status_bar:
            self._status_bar.stop()
        
        self._status_bar = StatusBar(message=message, hint=hint)
        self._status_bar.start()
        return self._status_bar
    
    def hide_status_bar(self):
        """Hide the current status bar."""
        if self._status_bar:
            self._status_bar.stop()
            self._status_bar = None
        
    def _get_terminal_width(self) -> int:
        """Get terminal width, with fallback"""
        try:
            import shutil
            return shutil.get_terminal_size().columns
        except Exception:
            return 80
    
    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis"""
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."
    
    def _highlight_json(self, data: Any, indent: int = 0, max_depth: int = 3) -> str:
        """Syntax highlight JSON data with colors"""
        if indent > max_depth:
            return f"{Theme.MUTED}...{Theme.RESET}"
            
        spaces = "  " * indent
        
        if data is None:
            return f"{Theme.NULL_VALUE}null{Theme.RESET}"
        elif isinstance(data, bool):
            return f"{Theme.BOOLEAN_VALUE}{str(data).lower()}{Theme.RESET}"
        elif isinstance(data, (int, float)):
            return f"{Theme.NUMBER_VALUE}{data}{Theme.RESET}"
        elif isinstance(data, str):
            # Truncate long strings (60 chars max to prevent terminal line wrapping)
            display_str = self._truncate(data, 60)
            # Escape special characters
            escaped = display_str.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'{Theme.STRING_VALUE}"{escaped}"{Theme.RESET}'
        elif isinstance(data, list):
            if not data:
                return "[]"
            if len(data) == 1 and not isinstance(data[0], (dict, list)):
                return f"[{self._highlight_json(data[0], indent)}]"
            items = [self._highlight_json(item, indent + 1, max_depth) for item in data[:5]]
            if len(data) > 5:
                items.append(f"{Theme.MUTED}...+{len(data) - 5} more{Theme.RESET}")
            inner = f",\n{spaces}  ".join(items)
            return f"[\n{spaces}  {inner}\n{spaces}]"
        elif isinstance(data, dict):
            if not data:
                return "{}"
            items = []
            for i, (k, v) in enumerate(list(data.items())[:10]):
                key_str = f'{Theme.PARAM_KEY}"{k}"{Theme.RESET}'
                val_str = self._highlight_json(v, indent + 1, max_depth)
                items.append(f"{key_str}: {val_str}")
                if i >= 9 and len(data) > 10:
                    items.append(f"{Theme.MUTED}...+{len(data) - 10} more{Theme.RESET}")
                    break
            inner = f",\n{spaces}  ".join(items)
            return f"{{\n{spaces}  {inner}\n{spaces}}}"
        else:
            return f"{Theme.PARAM_VALUE}{str(data)}{Theme.RESET}"
    
    def _format_compact_json(self, data: Any, max_width: int = 80) -> str:
        """Format JSON compactly if possible, otherwise pretty print"""
        try:
            compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(compact) <= max_width:
                return self._highlight_json(data, 0, 1)
            return self._highlight_json(data, 0, 3)
        except Exception:
            return str(data)
    
    def _draw_box_top(self, title: str = "", icon: str = "", status: StatusType = StatusType.RUNNING) -> str:
        """Draw the top border of a box with optional title"""
        width = min(self.style.width, self._get_terminal_width() - 4)
        
        # Status indicator
        status_indicators = {
            StatusType.PENDING: (Theme.MUTED, Theme.BOX_CIRCLE),
            StatusType.RUNNING: (Theme.PRIMARY, Theme.BOX_SPINNER_FRAMES[0]),
            StatusType.SUCCESS: (Theme.SUCCESS, Theme.BOX_CHECK),
            StatusType.ERROR: (Theme.ERROR, Theme.BOX_CROSS),
            StatusType.SKIPPED: (Theme.WARNING, "○"),
        }
        status_color, status_char = status_indicators.get(status, (Theme.MUTED, "○"))
        
        # Build title section
        if title:
            # Tool name in ITALIC
            title_section = f" {status_color}{status_char}{Theme.RESET} {Theme.BOLD}{Theme.ITALIC}{icon}{Theme.TOOL_NAME}{title}{Theme.RESET} "
            title_len = len(f" {status_char} {icon}{title} ")
        else:
            title_section = ""
            title_len = 0
        
        # Calculate remaining width for border
        remaining = width - title_len - 2  # 2 for corners
        left_border = Theme.BOX_HORIZONTAL * 1
        right_border = Theme.BOX_HORIZONTAL * max(0, remaining - 1)
        
        return (
            f"{Theme.BORDER_ACCENT}{Theme.BOX_TOP_LEFT}{left_border}{Theme.RESET}"
            f"{title_section}"
            f"{Theme.BORDER}{right_border}{Theme.BOX_TOP_RIGHT}{Theme.RESET}"
        )
    
    def _draw_box_bottom(self, status_text: str = "") -> str:
        """Draw the bottom border of a box with optional status"""
        width = min(self.style.width, self._get_terminal_width() - 4)
        
        if status_text:
            status_section = f" {Theme.MUTED}{status_text}{Theme.RESET} "
            status_len = len(f" {status_text} ")
        else:
            status_section = ""
            status_len = 0
        
        remaining = width - status_len - 2
        left_border = Theme.BOX_HORIZONTAL * max(0, remaining // 2)
        right_border = Theme.BOX_HORIZONTAL * max(0, remaining - len(left_border))
        
        return (
            f"{Theme.BORDER}{Theme.BOX_BOTTOM_LEFT}{left_border}{Theme.RESET}"
            f"{status_section}"
            f"{Theme.BORDER}{right_border}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}"
        )
    
    def _draw_box_line(self, content: str, prefix: str = "") -> str:
        """Draw a line of content inside a box"""
        if prefix:
            return f"{Theme.BORDER}{Theme.BOX_VERTICAL}{Theme.RESET} {prefix}{content}"
        return f"{Theme.BORDER}{Theme.BOX_VERTICAL}{Theme.RESET} {content}"
    
    # ─────────────────────────────────────────────────────────────
    # Collapsible Output Configuration
    # ─────────────────────────────────────────────────────────────
    # Default threshold: collapse if output exceeds this many lines
    COLLAPSE_THRESHOLD_LINES = 12
    # Number of lines to show at the beginning when collapsed
    COLLAPSE_HEAD_LINES = 6
    # Number of lines to show at the end when collapsed
    COLLAPSE_TAIL_LINES = 4
    
    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Remove ANSI escape codes from text."""
        import re
        return re.sub(r'\x1b\[[0-9;]*m', '', text)

    def _format_hidden_lines_hint(self, count: int, prefix: str = "") -> str:
        """Format the 'hidden lines' indicator consistently.

        Args:
            count: Number of hidden lines
            prefix: Optional prefix (e.g., "┆ " or "│ ")

        Returns:
            Formatted string like "... (6 more lines)"
        """
        return f"{Theme.MUTED}{prefix}... ({count} more lines){Theme.RESET}"

    def _format_collapsed_content(
        self,
        content: str,
        threshold: int = None,
        head_lines: int = None,
        tail_lines: int = None,
        collapse_indicator: str = "┆"
    ) -> tuple[str, bool, int]:
        """
        Format content with automatic collapsing for long outputs.

        If content exceeds threshold lines, shows only head and tail lines
        with a collapse indicator in between.

        Args:
            content: The content string to format
            threshold: Lines threshold to trigger collapse (default: COLLAPSE_THRESHOLD_LINES)
            head_lines: Number of lines to show at start (default: COLLAPSE_HEAD_LINES)
            tail_lines: Number of lines to show at end (default: COLLAPSE_TAIL_LINES)
            collapse_indicator: Character to prefix collapsed preview lines

        Returns:
            Tuple of (formatted_content, is_collapsed, total_lines)
        """
        threshold = threshold or self.COLLAPSE_THRESHOLD_LINES
        head_lines = head_lines or self.COLLAPSE_HEAD_LINES
        tail_lines = tail_lines or self.COLLAPSE_TAIL_LINES

        lines = content.split('\n')

        # Filter out consecutive empty lines (lines with only ANSI codes count as empty)
        filtered_lines = []
        prev_was_blank = False
        for line in lines:
            is_blank = not self._strip_ansi(line).strip()
            if is_blank:
                if not prev_was_blank:
                    filtered_lines.append(line)
                prev_was_blank = True
            else:
                filtered_lines.append(line)
                prev_was_blank = False
        lines = filtered_lines
        total_lines = len(lines)

        # If within threshold, return filtered content
        if total_lines <= threshold:
            return '\n'.join(lines), False, total_lines

        # Filter out Session meta-info lines for head display
        # These lines are not meaningful to users
        meta_patterns = ('Session restored:', '[Session ', 'Session ')
        
        def is_meta_line(line: str) -> bool:
            """Check if a line is meta-info that should be skipped."""
            stripped = line.strip()
            if not stripped:  # Empty lines are not meta
                return False
            return any(p in stripped for p in meta_patterns)
        
        # Find first meaningful line (skip meta-info at the beginning)
        meaningful_start = 0
        for i, line in enumerate(lines):
            if not is_meta_line(line):
                meaningful_start = i
                break
        
        # Collapse: show head + indicator + tail
        collapsed_lines = []
        
        # Head lines: prefer meaningful content over meta-info
        head_source = lines[meaningful_start:meaningful_start + head_lines]
        if len(head_source) < head_lines:
            # Not enough meaningful lines, fall back to original
            head_source = lines[:head_lines]
        
        for line in head_source:
            # Truncate very long lines
            if len(line) > 78:
                line = line[:75] + "..."
            collapsed_lines.append(f"{Theme.MUTED}{collapse_indicator}{Theme.RESET} {line}")
        
        # Collapse indicator showing hidden lines count
        hidden_count = total_lines - head_lines - tail_lines
        collapsed_lines.append(
            self._format_hidden_lines_hint(hidden_count, prefix=f"{collapse_indicator} ")
        )
        
        # Tail lines with collapse indicator
        for line in lines[-tail_lines:]:
            if len(line) > 78:
                line = line[:75] + "..."
            collapsed_lines.append(f"{Theme.MUTED}{collapse_indicator}{Theme.RESET} {line}")
        
        return '\n'.join(collapsed_lines), True, total_lines

    def _draw_separator(self, style: str = "light") -> str:
        """Draw a horizontal separator"""
        width = min(self.style.width, self._get_terminal_width() - 4)
        if style == "light":
            return f"{Theme.MUTED}{'·' * (width - 2)}{Theme.RESET}"
        elif style == "dashed":
            return f"{Theme.BORDER}{'╌' * (width - 2)}{Theme.RESET}"
        else:
            return f"{Theme.BORDER}{Theme.BOX_HORIZONTAL * (width - 2)}{Theme.RESET}"

    def _format_params_clean(self, params: Dict[str, Any], max_val_len: int = 500) -> str:
        """
        Format parameters as a clean, aligned key-value list (YAML-style).
        
        This provides a much more readable output than raw JSON, especially
        for agents with long text inputs (reflections, plans, etc).
        
        Special handling for code-like parameters (cmd, code, script) which
        are displayed as properly formatted code blocks.
        """
        if not params:
            return f"{Theme.MUTED}(no parameters){Theme.RESET}"
        
        # Keys that should be treated as code blocks
        CODE_KEYS = {'cmd', 'code', 'script', 'python_code', 'shell_code', 'command'}
        
        lines = []
        # Calculate alignment
        keys = list(params.keys())
        max_key_len = max(len(str(k)) for k in keys) if keys else 0
        max_key_len = min(max_key_len, 25)  # Cap alignment padding to avoid huge gaps
        
        # Check if we should truncate the number of items
        items = list(params.items())
        total_items = len(items)
        truncated_items = False
        
        # If parameters are huge, limit the number of items displayed
        if total_items > 15:
             items = items[:15]
             truncated_items = True
             
        for k, v in items:
            key_str = str(k)
            key_lower = key_str.lower()
            
            # Alignment padding
            if len(key_str) > max_key_len:
                 padding = " "
                 display_key = self._truncate(key_str, max_key_len)
            else:
                 padding = " " * (max_key_len - len(key_str))
                 display_key = key_str

            # Check if this is a code-like parameter
            if key_lower in CODE_KEYS and isinstance(v, str) and '\n' in v:
                # Format as code block
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding}")
                code_lines = v.split('\n')
                # Limit to 10 lines max for display
                for i, code_line in enumerate(code_lines[:10]):
                    # Truncate very long lines
                    if len(code_line) > 80:
                        code_line = code_line[:77] + "..."
                    lines.append(f"    {Theme.MUTED}│{Theme.RESET} {Theme.STRING_VALUE}{code_line}{Theme.RESET}")
                if len(code_lines) > 10:
                    lines.append(f"    {self._format_hidden_lines_hint(len(code_lines) - 10, prefix='│ ')}")
            elif isinstance(v, str):
                # Regular string - escape newlines for single-line display
                val_str = v.replace("\n", "\\n")
                if len(val_str) > max_val_len:
                    val_str = val_str[:max_val_len-3] + "..."
                val_display = f"{Theme.STRING_VALUE}{val_str}{Theme.RESET}"
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding} {val_display}")
            elif isinstance(v, (int, float)):
                val_display = f"{Theme.NUMBER_VALUE}{v}{Theme.RESET}"
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding} {val_display}")
            elif isinstance(v, bool):
                val_display = f"{Theme.BOOLEAN_VALUE}{str(v).lower()}{Theme.RESET}"
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding} {val_display}")
            elif v is None:
                val_display = f"{Theme.NULL_VALUE}null{Theme.RESET}"
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding} {val_display}")
            # Special case for tasks list in PlanSkillkit
            elif key_lower == "tasks" and isinstance(v, list) and v and isinstance(v[0], dict):
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding}")
                for i, task in enumerate(v[:10]):
                    task_id = task.get("id", f"task_{i+1}")
                    task_name = task.get("name", "Unnamed Task")
                    lines.append(f"    {Theme.MUTED}•{Theme.RESET} [{Theme.SUCCESS}{task_id}{Theme.RESET}] {Theme.PARAM_VALUE}{task_name}{Theme.RESET}")
                if len(v) > 10:
                    lines.append(f"    {self._format_hidden_lines_hint(len(v) - 10, prefix=' ')}")
            else:
                # Complex types: use existing json highlighter
                val_display = self._highlight_json(v, indent=0, max_depth=1)
                lines.append(f"  {Theme.PARAM_KEY}{display_key}{Theme.RESET}:{padding} {val_display}")
            
        if truncated_items:
            lines.append(f"{Theme.MUTED}  ...+{total_items - 15} more parameters{Theme.RESET}")
            
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # Public API - Skill/Tool Call Display
    # ─────────────────────────────────────────────────────────────
    def skill_call_start(
        self, 
        skill_name: str, 
        params: Dict[str, Any],
        max_param_length: int = 300,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display the start of a skill/tool call with modern styling.
        
        Inspired by Codex CLI's bordered tool call display and 
        Claude Code's clean parameter formatting.
        
        Now includes an animated spinner while the skill is running.
        
        Args:
            skill_name: Name of the skill being called
            params: Parameters passed to the skill
            max_param_length: Maximum length for parameter display
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Stop any existing spinner first
        if self._active_skill_spinner:
            self._active_skill_spinner.stop()
            self._active_skill_spinner = None
        
        # Format the parameters using the clean style
        if params:
            formatted_params = self._format_params_clean(params, max_val_len=max_param_length)
        else:
            formatted_params = f"{Theme.MUTED}(no parameters){Theme.RESET}"
        
        # Build the output
        output_lines = [
            self._draw_box_top(skill_name, "⚡ ", StatusType.RUNNING),
            # Input label: Bold, no colon
            self._draw_box_line(f"{Theme.BOLD}{Theme.LABEL}Input{Theme.RESET}"),
        ]
        
        # Add formatted parameters with proper indentation
        for line in formatted_params.split("\n"):
            output_lines.append(self._draw_box_line(f"  {line}"))
        
        # Print all lines
        for line in output_lines:
            safe_print(line)
        
        # Start the spinner animation for skill execution
        # Also animate the icon in the Box Header (top-left)
        # Header is at index 1 of output_lines
        # Cursor is currently below the last line
        # Distance to Header = len(output_lines) - 1
        header_up_dist = len(output_lines) - 1
        
        self._active_skill_spinner = Spinner(
            f"Running {skill_name}...", 
            position_updates=[{'up': header_up_dist, 'col': 4}]
        )
        # Note: Fixed-position StatusBar uses cursor save/restore, so it won't conflict
        # with the skill spinner. No need to pause StatusBar here.
        self._active_skill_spinner.start()
    
    def _try_parse_json(self, text: str) -> Optional[Any]:
        """Try to parse a string as JSON or Python literal, return None if it fails."""
        if not text or not isinstance(text, str):
            return None
        text = text.strip()
        # Quick check: must start with { or [
        if not (text.startswith('{') or text.startswith('[')):
            return None
            
        # 1. Try JSON first (standard)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
            
        # 2. Try ast.literal_eval (for Python stringified objects with single quotes)
        try:
            val = ast.literal_eval(text)
            if isinstance(val, (dict, list)):
                return val
        except (ValueError, SyntaxError):
            pass
            
        return None
    
    def _format_response(self, response: Any, max_length: int = 300) -> str:
        """
        Format a response for display, with intelligent type detection.
        
        - If response is dict/list, format as highlighted JSON
        - If response is a string that looks like JSON, parse and format it
        - Otherwise, format as plain text with proper truncation
        """
        # Already a dict or list - use JSON formatting
        if isinstance(response, (dict, list)):
            return self._format_compact_json(response)
        
        # String - try to parse as JSON first
        if isinstance(response, str):
            # Try to parse as JSON
            parsed = self._try_parse_json(response)
            if parsed is not None:
                return self._format_compact_json(parsed)
            
            # Check if it's multiline text (like markdown output)
            if '\n' in response:
                return self._format_multiline_text(response, max_length)
            
            # Simple string - truncate and colorize
            display = self._truncate(response, max_length)
            return f"{Theme.PARAM_VALUE}{display}{Theme.RESET}"
        
        # Other types - convert to string
        return f"{Theme.PARAM_VALUE}{str(response)[:max_length]}{Theme.RESET}"
    
    def _highlight_inline_markdown(self, text: str) -> str:
        """Highlight inline Markdown formats: **bold**, `code`, etc.

        Args:
            text: Text with inline markdown

        Returns:
            Text with ANSI color codes for formatting
        """
        import re
        BOLD = "\033[1m"
        UNBOLD = "\033[22m"  # Reset bold/faint without resetting color
        CYAN = "\033[36m"
        RESET = "\033[0m"

        # Replace **text** with bold (use unbold instead of full reset to preserve outer colors)
        text = re.sub(r'\*\*(.+?)\*\*', f'{BOLD}\\1{UNBOLD}', text)
        # Replace `code` with cyan
        text = re.sub(r'`([^`]+)`', f'{CYAN}\\1{RESET}', text)
        return text

    def _format_multiline_text(self, text: str, max_length: int = 300) -> str:
        """
        Format multiline text for display in a box.
        Handles:
        - Markdown-like content (including inline formats like **bold**, `code`)
        - Python execution output (Session info, errors, tracebacks)
        - General structured text
        """
        lines = text.split('\n')

        # Filter out consecutive empty lines
        filtered_lines = []
        prev_was_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank:
                if not prev_was_blank:
                    filtered_lines.append(line)
                prev_was_blank = True
            else:
                filtered_lines.append(line)
                prev_was_blank = False
        lines = filtered_lines

        # Filter out meta-info lines that are not useful for display
        meta_patterns = (
            '<class ',           # e.g., <class 'pandas.core.frame.DataFrame'>
            'Session restored:', # Session restore info
            '[Session ',         # Session execution info
        )
        lines = [line for line in lines if not any(p in line for p in meta_patterns)]

        result_lines = []
        in_traceback = False

        # NOTE: No max_lines limit here - let _format_collapsed_content handle folding
        for i, line in enumerate(lines):
            # Truncate long lines
            display_line = line[:77] + "..." if len(line) > 80 else line
            
            # Handle Traceback state
            if line.startswith('Traceback') or line.startswith('错误:'):
                in_traceback = True
                result_lines.append(f"{Theme.ERROR}{Theme.BOLD}{display_line}{Theme.RESET}")
                continue
            
            if in_traceback:
                # Check for exit conditions (new section headers)
                if line.startswith('Output:') or line.startswith('输出:') or \
                   line.startswith('Return value:') or line.startswith('返回值:') or \
                   line.startswith('Session ') or line.startswith('[Session'):
                    in_traceback = False
                else:
                    # In traceback processing
                    if line.startswith('  File ') or line.strip().startswith('File '):
                        result_lines.append(f"{Theme.WARNING}{display_line}{Theme.RESET}")
                    elif 'Error:' in line or 'Exception:' in line or line.endswith('Error'):
                        # This usually marks the end of a traceback block
                        result_lines.append(f"{Theme.ERROR}{Theme.BOLD}{display_line}{Theme.RESET}")
                        in_traceback = False
                    else:
                        result_lines.append(f"{Theme.MUTED}{display_line}{Theme.RESET}")
                    continue

            # Standard processing (non-traceback)
            if line.startswith('Error ') or 'Error:' in line or 'error:' in line.lower():
                result_lines.append(f"{Theme.ERROR}{display_line}{Theme.RESET}")
            elif line.startswith('输出:') or line.startswith('Output:'):
                result_lines.append(f"{Theme.SUCCESS}{display_line}{Theme.RESET}")
            elif line.startswith('Return value:') or line.startswith('返回值:'):
                result_lines.append(f"{Theme.PRIMARY}{Theme.BOLD}{display_line}{Theme.RESET}")
            elif line.startswith('[Session') or line.startswith('Session '):
                result_lines.append(f"{Theme.MUTED}{display_line}{Theme.RESET}")
            
            # Markdown patterns
            elif line.startswith('# '):
                # Apply inline markdown to header content
                header_text = self._highlight_inline_markdown(display_line[2:])
                result_lines.append(f"{Theme.PRIMARY}{Theme.BOLD}{header_text}{Theme.RESET}")
            elif line.startswith('## '):
                header_text = self._highlight_inline_markdown(display_line[3:])
                result_lines.append(f"{Theme.SECONDARY}{Theme.BOLD}{header_text}{Theme.RESET}")
            elif line.startswith('### '):
                header_text = self._highlight_inline_markdown(display_line[4:])
                result_lines.append(f"{Theme.ACCENT}{header_text}{Theme.RESET}")
            elif line.startswith('- ') or line.startswith('* '):
                list_text = self._highlight_inline_markdown(display_line[2:])
                result_lines.append(f"{Theme.SUCCESS}•{Theme.RESET} {list_text}")
            elif line.startswith('  - ') or line.startswith('  * '):
                list_text = self._highlight_inline_markdown(display_line[4:])
                result_lines.append(f"  {Theme.SUCCESS}◦{Theme.RESET} {list_text}")
            elif line.strip().startswith('|'):
                result_lines.append(f"{Theme.MUTED}{display_line}{Theme.RESET}")
            else:
                # Apply inline markdown to regular text
                formatted_text = self._highlight_inline_markdown(display_line)
                # Don't wrap in PARAM_VALUE to avoid interfering with inline markdown colors
                result_lines.append(formatted_text)

        # NOTE: No max_length truncation here - let _format_collapsed_content handle folding
        return '\n'.join(result_lines)

    def skill_call_end(
        self,
        skill_name: str,
        response: Any,
        max_response_length: int = 300,
        success: bool = True,
        duration_ms: Optional[float] = None,
        verbose: Optional[bool] = None,
        collapsed: bool = True
    ) -> None:
        """
        Display the completion of a skill/tool call.
        
        Stops the running spinner animation before showing results.
        Supports automatic collapsing of long outputs.
        
        Args:
            skill_name: Name of the skill that completed
            response: Response from the skill
            max_response_length: Maximum length for response display
            success: Whether the call was successful
            duration_ms: Execution duration in milliseconds
            verbose: Override verbose setting
            collapsed: Whether to collapse long outputs (default: True)
        """
        # Stop spinner first (before any output) and update header icon
        if self._active_skill_spinner:
            self._active_skill_spinner.stop(success=success)
            self._active_skill_spinner = None
        
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Format the response using intelligent type detection
        formatted_response = self._format_response(response, max_response_length)
        
        # Skip rendering if response is empty (avoid empty boxes)
        stripped_response = self._strip_ansi(formatted_response).strip()
        if not stripped_response:
            return
        
        # Apply collapsing if enabled
        is_collapsed = False
        total_lines = 0
        if collapsed:
            formatted_response, is_collapsed, total_lines = self._format_collapsed_content(
                formatted_response
            )
        else:
            total_lines = len(formatted_response.split('\n'))
        
        # Build status text
        status_parts = []
        if duration_ms is not None:
            if duration_ms >= 1000:
                status_parts.append(f"{duration_ms/1000:.2f}s")
            else:
                status_parts.append(f"{duration_ms:.0f}ms")
        status_text = " ".join(status_parts) if status_parts else ""
        
        # Build output label
        status_icon = Theme.BOX_CHECK if success else Theme.BOX_CROSS
        status_color = Theme.SUCCESS if success else Theme.ERROR

        output_label = (
            f"{Theme.BOLD}{Theme.LABEL}Output{Theme.RESET} "
            f"{status_color}{status_icon}{Theme.RESET}"
        )
        
        # Build output
        output_lines = [
            self._draw_separator("light"),
            self._draw_box_line(output_label),
        ]
        
        for line in formatted_response.split("\n"):
            output_lines.append(self._draw_box_line(f"  {line}"))
        
        output_lines.append(self._draw_box_bottom(status_text))
        # No blank line after - let following content manage spacing
        
        for line in output_lines:
            safe_print(line)
    
    def skill_call_compact(
        self,
        skill_name: str,
        params: Dict[str, Any],
        response: Any,
        success: bool = True,
        duration_ms: Optional[float] = None,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a complete skill call in compact format (single box).
        
        Args:
            skill_name: Name of the skill
            params: Input parameters
            response: Output response
            success: Whether successful
            duration_ms: Execution duration
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        status = StatusType.SUCCESS if success else StatusType.ERROR
        status_icon = Theme.BOX_CHECK if success else Theme.BOX_CROSS
        status_color = Theme.SUCCESS if success else Theme.ERROR
        
        # Format params compactly
        param_str = json.dumps(params, ensure_ascii=False, separators=(",", ":")) if params else "()"
        if len(param_str) > 60:
            param_str = param_str[:57] + "..."
        
        # Format response compactly
        if isinstance(response, str):
            resp_str = self._truncate(response, 60)
        else:
            resp_str = json.dumps(response, ensure_ascii=False, separators=(",", ":"))[:60]
        
        # Duration string
        duration_str = ""
        if duration_ms is not None:
            if duration_ms >= 1000:
                duration_str = f" {Theme.MUTED}({duration_ms/1000:.2f}s){Theme.RESET}"
            else:
                duration_str = f" {Theme.MUTED}({duration_ms:.0f}ms){Theme.RESET}"
        
        # Single line format for very short calls
        safe_print(
            f"\n{status_color}{status_icon}{Theme.RESET} "
            f"{Theme.BOLD}⚡ {Theme.TOOL_NAME}{skill_name}{Theme.RESET}"
            f"{Theme.MUTED}({Theme.RESET}{Theme.PARAM_VALUE}{param_str}{Theme.RESET}{Theme.MUTED}){Theme.RESET}"
            f" {Theme.MUTED}→{Theme.RESET} "
            f"{Theme.STRING_VALUE}{resp_str}{Theme.RESET}"
            f"{duration_str}\n"
        )

    # ─────────────────────────────────────────────────────────────
    # Block Start/End Display
    # ─────────────────────────────────────────────────────────────
    
    def block_start(
        self,
        block_type: str,
        output_var: str,
        content_preview: Optional[str] = None,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display the start of a code block execution.
        
        Args:
            block_type: Type of block (explore, prompt, judge, etc.)
            output_var: Variable to store output
            content_preview: Preview of block content
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Block type icons and colors
        block_icons = {
            "explore": ("[?]", Theme.SECONDARY),
            "prompt": ("[>]", Theme.SUCCESS),
            "judge": ("[J]", Theme.WARNING),
            "assign": ("[=]", Theme.PRIMARY),
            "tool": ("[*]", Theme.ACCENT),
        }
        
        icon, color = block_icons.get(block_type.lower(), ("[X]", Theme.LABEL))
        
        # Build output line
        header = f"{color}{Theme.BOLD}{icon} {block_type.upper()}{Theme.RESET}"
        var_display = f"{Theme.PRIMARY}{output_var}{Theme.RESET}"
        arrow = f"{Theme.MUTED}→{Theme.RESET}"
        
        line = f"{header} {var_display} {arrow}"
        
        if content_preview:
            preview = self._truncate(content_preview.strip(), 50)
            line += f" {Theme.MUTED}{preview}{Theme.RESET}"
        
        # Pause status bar to avoid output conflicts
        with pause_status_bar_context():
            safe_print(line)
    
    def thinking_indicator(
        self,
        message: str = "Thinking",
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a thinking/processing indicator.
        
        Args:
            message: Message to display
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        safe_print(f"{Theme.MUTED}{Theme.BOX_SPINNER_FRAMES[0]} {message}...{Theme.RESET}", end="\r")

    def agent_skill_enter(
        self,
        skill_name: str,
        message: Optional[str] = None,
        verbose: Optional[bool] = None,
    ) -> None:
        """
        Print a visual delimiter indicating a sub-agent (agent-as-skill) has started.
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
            
        label = message or f"🚀 AGENT ACTIVATE: {skill_name}"
        self._draw_banner(label, style="success")

    def agent_skill_exit(
        self,
        skill_name: str,
        message: Optional[str] = None,
        verbose: Optional[bool] = None,
    ) -> None:
        """
        Print a visual delimiter indicating a sub-agent (agent-as-skill) has exited.

        This is intentionally UI-only: core execution should not embed terminal formatting logic.
        """
        if verbose is False or (verbose is None and not self.verbose):
            return

        label = message or f"🏁 AGENT COMPLETE: {skill_name}"
        self._draw_banner(label, style="secondary")

    def _draw_banner(self, text: str, style: str = "primary") -> None:
        """Draw a bold banner for major events"""
        width = min(self.style.width, self._get_terminal_width() - 4)
        
        if style == "success":
            color = Theme.SUCCESS
        elif style == "secondary":
            color = Theme.SECONDARY
        elif style == "error":
            color = Theme.ERROR
        else:
            color = Theme.PRIMARY
            
        # Top border
        safe_print(f"\n{color}{Theme.BOX_TOP_LEFT}{Theme.BOX_HORIZONTAL * width}{Theme.BOX_TOP_RIGHT}{Theme.RESET}")
        
        # Content string
        # Ensure text is not too long
        if len(text) > width - 4:
            text = text[:width - 7] + "..."
            
        padding_left = (width - len(text)) // 2
        padding_right = width - len(text) - padding_left
        
        safe_print(f"{color}{Theme.BOX_VERTICAL}{Theme.RESET}{' ' * padding_left}{Theme.BOLD}{text}{Theme.RESET}{' ' * padding_right}{color}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Bottom border
        safe_print(f"{color}{Theme.BOX_BOTTOM_LEFT}{Theme.BOX_HORIZONTAL * width}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}\n")

    # ─────────────────────────────────────────────────────────────
    # Session/Conversation Display
    # ─────────────────────────────────────────────────────────────
    
    def session_start(
        self,
        session_type: str,
        target: str,
        verbose: Optional[bool] = None
    ) -> None:
        """Display session start with Blackbox-style gradient banner with shadows.
        
        Features:
        - Large pixel art "DOLPHIN"
        - Gradient colors (yellow -> green -> pink)
        - Shadow effect using ▓ characters
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Build combined banner lines with gradient colors and shadow
        letters = Theme.BANNER_LETTERS
        word = Theme.BANNER_WORD
        main_color = Theme.BANNER_COLOR
        hollow_color = Theme.BANNER_HOLLOW_COLOR
        num_rows = 6  # Each letter has 6 rows
        
        banner_lines = []
        for row in range(num_rows):
            line_parts = []
            for char in word:
                letter_art = letters.get(char, ['         '] * 6)
                
                # Process each character: █ gets main color, ░ gets hollow color
                styled_segment = ""
                for c in letter_art[row]:
                    if c == '█':
                        styled_segment += f"{main_color}{c}{Theme.RESET}"
                    elif c == '░':
                        styled_segment += f"{hollow_color}{c}{Theme.RESET}"
                    else:
                        styled_segment += c
                line_parts.append(styled_segment)
            banner_lines.append(''.join(line_parts))
        
        # Calculate width - each letter is ~9 chars wide, 7 letters
        content_width = len(word) * 9
        padding = 2
        border_width = content_width + padding * 2
        
        # Use rounded box characters for clean border
        border_color = Theme.BORDER_ACCENT
        top_border = f"{border_color}{Theme.BOLD}{Theme.BOX_TOP_LEFT}{Theme.BOX_HORIZONTAL * border_width}{Theme.BOX_TOP_RIGHT}{Theme.RESET}"
        bottom_border = f"{border_color}{Theme.BOLD}{Theme.BOX_BOTTOM_LEFT}{Theme.BOX_HORIZONTAL * border_width}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}"
        
        # Clear line before each print to remove any residual text from Rich status spinner
        # This ensures the LOGO displays cleanly without trailing artifacts
        import sys
        
        safe_print()
        safe_write("\033[K")  # Clear to end of line
        safe_print(top_border)
        
        # Empty padding row
        empty_row = ' ' * content_width
        safe_write("\033[K")
        safe_print(f"{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}{' ' * padding}{empty_row}{' ' * padding}{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Print banner lines
        for line in banner_lines:
            # Line already has colors, just add padding and borders
            safe_write("\033[K")
            safe_print(f"{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}{' ' * padding}{line}{' ' * padding}{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Empty padding row
        safe_write("\033[K")
        safe_print(f"{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}{' ' * padding}{empty_row}{' ' * padding}{border_color}{Theme.BOLD}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        safe_write("\033[K")
        safe_print(bottom_border)
        
        # Session info
        safe_print(f"{Theme.MUTED}   Type 'exit', 'quit', or 'q' to end{Theme.RESET}")
        safe_print()
    
    def session_end(self, verbose: Optional[bool] = None) -> None:
        """Display session end"""
        if verbose is False or (verbose is None and not self.verbose):
            return

        width = min(40, self._get_terminal_width() - 4)
        border = f"{Theme.BORDER}{'═' * width}{Theme.RESET}"

        safe_print(f"\n{border}")
        safe_print(f"{Theme.WARNING}{Theme.BOLD}👋 Session ended{Theme.RESET}")
        safe_print(f"{border}\n")

    def display_session_info(
        self,
        skillkit_info: dict = None,
        show_commands: bool = True,
        verbose: Optional[bool] = None
    ) -> None:
        """Display available skillkits and command hints after session start.

        Args:
            skillkit_info: Dict mapping skillkit name to tool count
            show_commands: Whether to show available slash commands
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return

        if skillkit_info:
            safe_print(f"{Theme.SECONDARY}📦 Available Skillkits:{Theme.RESET}")
            for name, count in sorted(skillkit_info.items()):
                safe_print(f"{Theme.MUTED}   • {name} ({count} tools){Theme.RESET}")

        if show_commands:
            safe_print(f"{Theme.MUTED}💡 Commands: /help • exit/quit/q to end{Theme.RESET}")

        safe_print()
    
    def user_input_display(
        self,
        user_input: str,
        verbose: Optional[bool] = None
    ) -> None:
        """Display formatted user input in a clean, minimal style"""
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        if user_input.strip():
            content = user_input.strip()
        else:
            content = f"{Theme.MUTED}(empty input){Theme.RESET}"
        
        # Clean, minimal style like Claude Code - single newline before for separation
        safe_print(f"{Theme.SECONDARY}{Theme.BOLD}>{Theme.RESET} {content}")
    
    def agent_label(
        self,
        agent_name: str,
        verbose: Optional[bool] = None
    ) -> None:
        """Display agent response label"""
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        safe_print(f"\n{Theme.SUCCESS}{Theme.BOLD}🤖 {agent_name}{Theme.RESET}")

    # ─────────────────────────────────────────────────────────────
    # Plan/Task Progress Display
    # ─────────────────────────────────────────────────────────────
    
    def task_progress(
        self,
        current: int,
        total: int,
        current_task: str,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display task progress with a visual progress bar.
        
        Args:
            current: Current task number (1-indexed)
            total: Total number of tasks
            current_task: Description of current task
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Calculate progress
        percentage = (current / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        
        # Color based on progress
        if percentage >= 100:
            color = Theme.SUCCESS
        elif percentage >= 50:
            color = Theme.PRIMARY
        else:
            color = Theme.ACCENT
        
        # Build progress line
        progress_line = (
            f"{color}[{bar}]{Theme.RESET} "
            f"{Theme.BOLD}{current}/{total}{Theme.RESET} "
            f"{Theme.MUTED}({percentage:.0f}%){Theme.RESET}"
        )
        
        safe_print(f"\n{progress_line}")
        if current_task:
            safe_print(f"  {Theme.LABEL}▸{Theme.RESET} {current_task}")
    
    # ─────────────────────────────────────────────────────────────
    # Codex-Style Components (New)
    # ─────────────────────────────────────────────────────────────
    
    def task_list_tree(
        self,
        tasks: List[Dict[str, Any]],
        title: str = "Updated Plan",
        style: str = "codex",
        verbose: Optional[bool] = None
    ) -> None:
        """
        Render a Codex-style tree task list with checkboxes.
        
        Args:
            tasks: List of tasks with 'content'/'name', 'status', optional 'children'
            title: Title for the task list
            style: 'codex' for checkbox style, 'emoji' for emoji style
            verbose: Override verbose setting
            
        Example output (codex style):
            • Updated Plan
              └─ □ 扫描仓库结构与说明文档
              └─ ☑ 梳理核心模块与依赖关系
              └─ □ 总结构建运行与开发流程
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Status icons based on style
        if style == "codex":
            status_icons = {
                "pending": ("□", Theme.MUTED),
                "in_progress": ("◐", Theme.PRIMARY),
                "running": ("◐", Theme.PRIMARY),
                "completed": ("☑", Theme.SUCCESS),
                "done": ("☑", Theme.SUCCESS),
                "success": ("☑", Theme.SUCCESS),
                "paused": ("▫", Theme.WARNING),
                "cancelled": ("☒", Theme.ERROR),
                "error": ("☒", Theme.ERROR),
                "skipped": ("○", Theme.MUTED),
            }
        else:  # emoji style
            status_icons = {
                "pending": ("⏳", Theme.MUTED),
                "in_progress": ("🔄", Theme.PRIMARY),
                "running": ("🔄", Theme.PRIMARY),
                "completed": ("✅", Theme.SUCCESS),
                "done": ("✅", Theme.SUCCESS),
                "success": ("✅", Theme.SUCCESS),
                "paused": ("⏸️", Theme.WARNING),
                "cancelled": ("❌", Theme.ERROR),
                "error": ("❌", Theme.ERROR),
                "skipped": ("○", Theme.MUTED),
            }
        
        # Calculate progress
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") in ("completed", "done", "success"))
        percentage = (completed / total * 100) if total > 0 else 0
        
        # Header with bullet point
        progress_str = f"{Theme.MUTED}({completed}/{total} · {percentage:.0f}%){Theme.RESET}"
        safe_print(f"\n{Theme.PRIMARY}•{Theme.RESET} {Theme.BOLD}{title}{Theme.RESET} {progress_str}")
        
        # Render tasks
        for i, task in enumerate(tasks):
            content = task.get("content", task.get("name", task.get("description", f"Task {i+1}")))
            status = task.get("status", "pending").lower()
            icon, color = status_icons.get(status, ("○", Theme.MUTED))
            
            # Tree connector (└─ for all items)
            prefix = f"  {Theme.MUTED}└─{Theme.RESET}"
            
            # Highlight running/in_progress tasks
            if status in ("running", "in_progress"):
                task_line = f"{prefix} {color}{icon}{Theme.RESET} {Theme.BOLD}{content}{Theme.RESET}"
            else:
                task_line = f"{prefix} {color}{icon}{Theme.RESET} {content}"
            
            safe_print(task_line)
            
            # Render children if present
            children = task.get("children", [])
            for child in children:
                child_content = child.get("content", child.get("name", ""))
                child_status = child.get("status", "pending").lower()
                child_icon, child_color = status_icons.get(child_status, ("○", Theme.MUTED))
                child_line = f"       {Theme.MUTED}·{Theme.RESET} {child_color}{child_icon}{Theme.RESET} {child_content}"
                safe_print(child_line)
        
        safe_print()  # Trailing newline
    
    def collapsible_text(
        self,
        text: str,
        max_lines: int = 5,
        verbose: Optional[bool] = None
    ) -> str:
        """
        Display long text with automatic folding.
        
        Args:
            text: The text to display
            max_lines: Maximum lines to show before folding
            verbose: Override verbose setting
            
        Returns:
            Formatted text with fold indicator if applicable
            
        Example:
            Line 1
            Line 2
            ... +72 lines
        """
        if verbose is False or (verbose is None and not self.verbose):
            return ""
        
        lines = text.split('\n')
        if len(lines) <= max_lines:
            return text
        
        visible_lines = lines[:max_lines]
        hidden_count = len(lines) - max_lines

        result = '\n'.join(visible_lines)
        result += f"\n{self._format_hidden_lines_hint(hidden_count)}"

        return result
    
    def print_collapsible(
        self,
        text: str,
        max_lines: int = 5,
        verbose: Optional[bool] = None
    ) -> None:
        """Print text with automatic folding."""
        formatted = self.collapsible_text(text, max_lines, verbose)
        if formatted:
            safe_print(formatted)
    
    def timed_status(
        self,
        message: str,
        elapsed_seconds: int = 0,
        show_interrupt_hint: bool = True,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a status line with elapsed time (like Codex CLI).
        
        Args:
            message: The status message
            elapsed_seconds: Elapsed time in seconds
            show_interrupt_hint: Whether to show 'esc to interrupt'
            verbose: Override verbose setting
            
        Example output:
            • Planning repository inspection (27s • esc to interrupt)
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        time_str = f"{elapsed_seconds}s"
        hint_str = " • esc to interrupt" if show_interrupt_hint else ""
        
        safe_print(f"\n{Theme.PRIMARY}•{Theme.RESET} {message} {Theme.MUTED}({time_str}{hint_str}){Theme.RESET}")
    
    def action_item(
        self,
        action: str,
        description: str,
        details: Optional[List[str]] = None,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display an action item with optional details (Codex-style).
        
        Args:
            action: The action name (e.g., "Explored", "Ran", "Updated Plan")
            description: Brief description
            details: Optional list of detail lines
            verbose: Override verbose setting
            
        Example:
            • Explored
              └─ List ls -la
                 Search AGENTS.md in ..
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Action header
        safe_print(f"\n{Theme.PRIMARY}•{Theme.RESET} {Theme.BOLD}{action}{Theme.RESET}")
        
        # Description with tree connector
        if description:
            safe_print(f"  {Theme.MUTED}└─{Theme.RESET} {description}")
        
        # Details as sub-items
        if details:
            for i, detail in enumerate(details[:10]):  # Limit to 10 items
                safe_print(f"     {Theme.MUTED}{detail}{Theme.RESET}")
            if len(details) > 10:
                safe_print(f"     {Theme.MUTED}… +{len(details) - 10} more{Theme.RESET}")

    # ─────────────────────────────────────────────────────────────
    # Plan Renderer (Codex-style)
    # ─────────────────────────────────────────────────────────────
    
    def _get_visual_width(self, text: str) -> int:
        """Calculate the visual width of a string in terminal (handling double-width CJK)."""
        # Remove ANSI escape codes before calculating width
        clean_text = ""
        skip = False
        for i, char in enumerate(text):
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

    # ─────────────────────────────────────────────────────────────
    # Plan Renderer (Codex-style)
    # ─────────────────────────────────────────────────────────────
    
    def plan_update(
        self,
        tasks: List[Dict[str, Any]],
        current_action: Optional[str] = None,
        current_task_id: Optional[int] = None,
        current_task_content: Optional[str] = None,
        conclusions: Optional[str] = None,
        elapsed_seconds: Optional[int] = None,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Render a complete plan update in a plan-focused visual style.
        
        This renderer is intended for plan orchestration tools (e.g., plan_skillkit)
        and can be used by callers who want a dedicated plan visualization.
        
        Args:
            tasks: List of tasks with 'content', 'status'
            current_action: Current action type ('create', 'start', 'done', 'pause', 'skip')
            current_task_id: ID of the task being operated on
            current_task_content: Content of the current task
            conclusions: Conclusions for completed tasks
            elapsed_seconds: Optional elapsed time for status display
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        if not tasks:
            return
            
        # No need to pause StatusBar in fixed-position mode - it uses cursor save/restore
        self._render_plan_update_internal(
            tasks, current_action, current_task_id, 
            current_task_content, conclusions, elapsed_seconds
        )
            
    def _render_plan_update_internal(
        self,
        tasks: List[Dict[str, Any]],
        current_action: Optional[str] = None,
        current_task_id: Optional[int] = None,
        current_task_content: Optional[str] = None,
        conclusions: Optional[str] = None,
        elapsed_seconds: Optional[int] = None
    ) -> None:
        PLAN_PRIMARY = "\033[38;5;44m"     # Modern Teal/Cyan
        PLAN_ACCENT = "\033[38;5;80m"      # Lighter Teal
        PLAN_MUTED = "\033[38;5;242m"      # Dimmed gray
        
        # Status icons (plan-specific style)
        # Use simple spinner frames for "in_progress" to give a dynamic feel
        spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        current_frame = spinner_frames[int(time.time() * 10) % len(spinner_frames)]
        
        status_icons = {
            "pending": ("○", Theme.MUTED),
            "in_progress": (current_frame, PLAN_PRIMARY),
            "running": (current_frame, PLAN_PRIMARY),
            "completed": ("●", Theme.SUCCESS),
            "done": ("●", Theme.SUCCESS),
            "success": ("●", Theme.SUCCESS),
            "paused": ("◎", Theme.WARNING),
            "cancelled": ("⊘", Theme.ERROR),
            "error": ("⊘", Theme.ERROR),
            "skipped": ("○", Theme.MUTED),
        }
        
        # Calculate stats
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") in ("completed", "done", "success"))
        
        # Build the plan card
        term_width = self._get_terminal_width()
        width = min(self.style.width, term_width - 4)
        if width < 40: width = 40 # Minimum usable width
        
        # Header
        title = "Plan Update"
        progress = f"{completed}/{total}"
        header_text = f"  📋 {title}"
        
        # Calculate padding using visual width
        v_header_w = self._get_visual_width(header_text)
        v_progress_w = self._get_visual_width(progress)
        header_padding = width - v_header_w - v_progress_w - 4
        
        # No leading blank - previous content should manage spacing
        safe_print(f"{PLAN_PRIMARY}{Theme.BOX_TOP_LEFT}{Theme.BOX_HORIZONTAL * (width)}{Theme.BOX_TOP_RIGHT}{Theme.RESET}")
        safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{Theme.BOLD}{header_text}{Theme.RESET}{' ' * max(0, header_padding)}{PLAN_ACCENT}{progress}{Theme.RESET}  {PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")
        safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.BOX_HORIZONTAL * (width)}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Task list
        for i, task in enumerate(tasks):
            content = task.get("content", task.get("name", f"Task {i+1}"))
            status = task.get("status", "pending").lower()
            
            # Truncate long content based on visual width
            max_v_content = width - 10
            v_content = self._get_visual_width(content)
            if v_content > max_v_content:
                # Simple truncation that's safe for multi-byte
                content = content[:int(max_v_content/1.5)] + "..."
                v_content = self._get_visual_width(content)

            icon, color = status_icons.get(status, ("○", Theme.MUTED))
            
            # Use dynamic icon if it's the current task being worked on
            is_current = (current_task_id is not None and i + 1 == current_task_id)
            if is_current and status in ("pending", "running", "in_progress"):
                icon, color = current_frame, PLAN_PRIMARY
            
            if is_current:
                task_line = f"  {color}{icon}{Theme.RESET} {Theme.BOLD}{content}{Theme.RESET}"
                indicator = f" {PLAN_PRIMARY}←{Theme.RESET}"
            else:
                task_line = f"  {color}{icon}{Theme.RESET} {content}"
                indicator = ""
            
            # Calculate final line visual width
            v_line_w = self._get_visual_width(task_line)
            v_indicator_w = self._get_visual_width(indicator)
            padding = width - v_line_w - v_indicator_w - 1
            
            safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{task_line}{indicator}{' ' * max(0, padding)}{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Footer with action info
        if current_action and current_task_id:
            action_icons = {
                "create": "📝",
                "start": "▶",
                "done": "✓",
                "pause": "⏸",
                "skip": "⏭",
            }
            action_icon = action_icons.get(current_action, "•")
            
            # Separator
            safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.BOX_HORIZONTAL * (width)}{Theme.BOX_VERTICAL}{Theme.RESET}")
            
            # Action line
            if current_task_content:
                action_text = f"  {action_icon} Task {current_task_id}: {current_task_content}"
            else:
                action_text = f"  {action_icon} Task {current_task_id}"
            
            v_action_w = self._get_visual_width(action_text)
            if v_action_w > width - 4:
                action_text = action_text[:int((width-6)/1.5)] + "..."
                v_action_w = self._get_visual_width(action_text)
            
            padding = width - v_action_w - 1
            safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{PLAN_ACCENT}{action_text}{Theme.RESET}{' ' * max(0, padding)}{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")
            
            # Conclusions if present
            if conclusions:
                conclusion_text = f"    {conclusions}"
                v_conclusion_w = self._get_visual_width(conclusion_text)
                if v_conclusion_w > width - 4:
                    conclusion_text = conclusion_text[:int((width-6)/1.5)] + "..."
                    v_conclusion_w = self._get_visual_width(conclusion_text)
                
                padding = width - v_conclusion_w - 1
                safe_print(f"{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}{PLAN_MUTED}{conclusion_text}{Theme.RESET}{' ' * max(0, padding)}{PLAN_PRIMARY}{Theme.BOX_VERTICAL}{Theme.RESET}")
        
        # Bottom border with optional timer
        if elapsed_seconds is not None:
            timer_text = f" {elapsed_seconds}s "
            v_timer_w = self._get_visual_width(timer_text)
            left_len = (width - v_timer_w) // 2
            right_len = width - v_timer_w - left_len
            safe_print(f"{PLAN_PRIMARY}{Theme.BOX_BOTTOM_LEFT}{Theme.BOX_HORIZONTAL * left_len}{Theme.RESET}{Theme.MUTED}{timer_text}{Theme.RESET}{PLAN_PRIMARY}{Theme.BOX_HORIZONTAL * right_len}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}")
        else:
            safe_print(f"{PLAN_PRIMARY}{Theme.BOX_BOTTOM_LEFT}{Theme.BOX_HORIZONTAL * (width)}{Theme.BOX_BOTTOM_RIGHT}{Theme.RESET}")
        
        # No trailing newline - let following content add spacing as needed

    # ─────────────────────────────────────────────────────────────
    # Task List Display (Original)
    # ─────────────────────────────────────────────────────────────
    
    def task_list(
        self,
        tasks: List[Dict[str, Any]],
        title: str = "📋 Task Plan",
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a formatted task list with status icons.
        
        Args:
            tasks: List of tasks with 'name', 'status' ('pending', 'running', 'done', 'error')
            title: Title for the task list
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        # Status icons and colors
        status_display = {
            "pending": (Theme.MUTED, "⏳"),
            "running": (Theme.PRIMARY, "⚡"),
            "done": (Theme.SUCCESS, "✓"),
            "completed": (Theme.SUCCESS, "✓"),
            "success": (Theme.SUCCESS, "✓"),
            "error": (Theme.ERROR, "✗"),
            "failed": (Theme.ERROR, "✗"),
            "skipped": (Theme.WARNING, "○"),
        }
        
        # Count stats
        done_count = sum(1 for t in tasks if t.get("status") in ("done", "completed", "success"))
        total_count = len(tasks)
        
        # Header with progress
        percentage = (done_count / total_count * 100) if total_count > 0 else 0
        header = f"{Theme.BOLD}{title}{Theme.RESET} {Theme.MUTED}({done_count}/{total_count} · {percentage:.0f}%){Theme.RESET}"
        
        safe_print(f"\n{header}")
        
        # Task items
        for i, task in enumerate(tasks, 1):
            name = task.get("name", task.get("description", f"Task {i}"))
            status = task.get("status", "pending").lower()
            color, icon = status_display.get(status, (Theme.MUTED, "○"))
            
            # Highlight current running task
            if status == "running":
                task_line = f"  {color}{icon} {Theme.BOLD}{i}. {name}{Theme.RESET}"
            else:
                task_line = f"  {color}{icon}{Theme.RESET} {i}. {name}"
            
            safe_print(task_line)
    
    def plan_summary(
        self,
        plan_name: str,
        tasks: List[str],
        next_step: Optional[str] = None,
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a plan summary in a clean card format.
        
        Args:
            plan_name: Name/title of the plan
            tasks: List of task descriptions
            next_step: Next step to execute
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        safe_print(f"\n{self._draw_box_top(plan_name, '📋 ', StatusType.SUCCESS)}")
        
        # Tasks section
        safe_print(self._draw_box_line(f"{Theme.LABEL}Tasks ({len(tasks)}):{Theme.RESET}"))
        for i, task in enumerate(tasks[:7], 1):  # Show max 7 tasks
            task_preview = self._truncate(task, 50)
            safe_print(self._draw_box_line(f"  {Theme.MUTED}{i}.{Theme.RESET} {task_preview}"))
        
        if len(tasks) > 7:
            safe_print(self._draw_box_line(f"  {Theme.MUTED}...+{len(tasks) - 7} more{Theme.RESET}"))
        
        # Next step section
        if next_step:
            safe_print(self._draw_separator("light"))
            safe_print(self._draw_box_line(f"{Theme.LABEL}Next:{Theme.RESET} {Theme.PRIMARY}{next_step}{Theme.RESET}"))
        
        safe_print(self._draw_box_bottom())
    
    def result_card(
        self,
        title: str,
        content: Any,
        status: str = "success",
        verbose: Optional[bool] = None
    ) -> None:
        """
        Display a result in a card format.
        
        Args:
            title: Title of the result
            content: Result content (str, dict, or list)
            status: Status ('success', 'error', 'info')
            verbose: Override verbose setting
        """
        if verbose is False or (verbose is None and not self.verbose):
            return
        
        status_map = {
            "success": (StatusType.SUCCESS, "✓"),
            "error": (StatusType.ERROR, "✗"),
            "info": (StatusType.RUNNING, "ℹ"),
        }
        status_type, icon = status_map.get(status, (StatusType.SUCCESS, "✓"))
        
        safe_print(f"\n{self._draw_box_top(title, f'{icon} ', status_type)}")
        
        # Format content
        if isinstance(content, dict):
            formatted = self._format_compact_json(content)
        elif isinstance(content, list):
            formatted = self._format_compact_json(content)
        else:
            formatted = str(content)
        
        for line in formatted.split("\n")[:15]:  # Limit to 15 lines
            safe_print(self._draw_box_line(f"  {line}"))
        
        if formatted.count("\n") > 15:
            safe_print(self._draw_box_line(f"  {Theme.MUTED}...{Theme.RESET}"))
        
        safe_print(self._draw_box_bottom())


# ─────────────────────────────────────────────────────────────
# Global Instance and Convenience Functions
# ─────────────────────────────────────────────────────────────

# Global console UI instance
_console_ui: Optional[ConsoleUI] = None


def get_console_ui(verbose: bool = True) -> ConsoleUI:
    """Get or create global ConsoleUI instance"""
    global _console_ui
    if _console_ui is None:
        _console_ui = ConsoleUI(verbose=verbose)
    return _console_ui


def set_console_ui(ui: ConsoleUI) -> None:
    """Set global ConsoleUI instance"""
    global _console_ui
    _console_ui = ui


# Convenience functions that delegate to global instance
def ui_skill_call(
    skill_name: str,
    params: Dict[str, Any],
    max_length: int = 300,
    verbose: Optional[bool] = None
) -> None:
    """Display skill call start (convenience function)"""
    get_console_ui().skill_call_start(skill_name, params, max_length, verbose)


def ui_skill_response(
    skill_name: str,
    response: Any,
    max_length: int = 300,
    success: bool = True,
    duration_ms: Optional[float] = None,
    verbose: Optional[bool] = None
) -> None:
    """Display skill call response (convenience function)"""
    get_console_ui().skill_call_end(skill_name, response, max_length, success, duration_ms, verbose)


def ui_block_start(
    block_type: str,
    output_var: str,
    content: Optional[str] = None,
    verbose: Optional[bool] = None
) -> None:
    """Display block start (convenience function)"""
    get_console_ui().block_start(block_type, output_var, content, verbose)


# Session and conversation display functions (moved from log.py)
def console_session_start(session_type: str, target: str) -> None:
    """Display session start message"""
    get_console_ui().session_start(session_type, target, verbose=True)


def console_session_end() -> None:
    """Display session end message"""
    get_console_ui().session_end(verbose=True)


# Alias for backwards compatibility
console_conversation_end = console_session_end


def console_display_session_info(skillkit_info: dict = None, show_commands: bool = True) -> None:
    """Display available skillkits and command hints after session start.

    Args:
        skillkit_info: Dict mapping skillkit name to tool count, e.g. {"python_skillkit": 3}
        show_commands: Whether to show available slash commands
    """
    get_console_ui().display_session_info(skillkit_info, show_commands, verbose=True)


def console_user_input(user_input: str) -> None:
    """Display user input in enhanced format"""
    get_console_ui().user_input_display(user_input, verbose=True)


def console_conversation_separator() -> None:
    """Display conversation separator line"""
    separator = f"{Theme.MUTED}{Theme.BOX_HORIZONTAL * 40}{Theme.RESET}"
    safe_print(f"\n{separator}")


if __name__ == "__main__":
    # Demo the UI
    ui = ConsoleUI()
    
    safe_print("\n" + "=" * 60)
    safe_print("  Dolphin Console UI Demo")
    safe_print("=" * 60)
    
    # ─────────────────────────────────────────────────────────────
    # NEW: Codex-Style Components Demo
    # ─────────────────────────────────────────────────────────────
    
    safe_print("\n" + "-" * 60)
    safe_print("  [NEW] Codex-Style Components")
    safe_print("-" * 60)
    
    # Demo Codex-style task list tree
    ui.task_list_tree(
        [
            {"content": "扫描仓库结构与说明文档", "status": "completed"},
            {"content": "梳理核心模块与依赖关系", "status": "completed"},
            {"content": "总结构建运行与开发流程", "status": "in_progress"},
            {"content": "给出可继续深入的阅读路径", "status": "pending"},
        ],
        title="Updated Plan",
        style="codex"
    )
    
    # Demo action item (like Codex's "Explored", "Ran" sections)
    ui.action_item(
        action="Explored",
        description="List ls -la",
        details=[
            "Search AGENTS.md in ..",
            "List ls -la"
        ]
    )
    
    ui.action_item(
        action="Ran",
        description='git rev-parse --is-inside-work-tree && git log -n 5',
        details=[
            "true",
            "… +3 lines",
            "c91c032d 已合并 PR 140381: examples清理",
            "229ae14c 已合并 PR 139859: 核心代码注释翻译英文"
        ]
    )
    
    # Demo timed status (like Codex's bottom status bar)
    ui.timed_status("Planning repository inspection", elapsed_seconds=27)
    
    # Demo collapsible text
    long_text = "\n".join([f"Line {i}: Some content here..." for i in range(1, 80)])
    safe_print("\n[Collapsible Text Demo]")
    ui.print_collapsible(long_text, max_lines=5)
    
    safe_print("\n" + "-" * 60)
    safe_print("  [END] Codex-Style Components")
    safe_print("-" * 60)
    
    # ─────────────────────────────────────────────────────────────
    # Original Demo
    # ─────────────────────────────────────────────────────────────
    
    safe_print("\n" + "-" * 60)
    safe_print("  Original Components")
    safe_print("-" * 60)
    
    # Demo skill call
    ui.skill_call_start(
        "_plan_tasks",
        {
            "exec_mode": "seq",
            "max_concurrency": 3,
            "tasks": [
                {"id": "task_1", "name": "Load Excel file", "prompt": "Load the Excel file"},
                {"id": "task_2", "name": "Analyze structure", "prompt": "Analyze the file structure"},
                {"id": "task_3", "name": "Generate insights", "prompt": "Generate key insights"},
            ],
        }
    )
    
    import time
    time.sleep(0.5)
    
    ui.skill_call_end(
        "_plan_tasks",
        {
            "status": "success",
            "tasks": [
                {"id": "task_1", "name": "Load Excel file"},
                {"id": "task_2", "name": "Analyze structure"},
                {"id": "task_3", "name": "Generate insights"},
            ],
            "next_step": "Execute task_1",
        },
        duration_ms=156.3
    )
    
    # Demo block start
    ui.block_start("explore", "analysis_result", "Analyzing the data structure...")
    
    # Demo compact call
    ui.skill_call_compact(
        "_python",
        {"code": "df.describe()"},
        "DataFrame statistics computed",
        success=True,
        duration_ms=42.5
    )
    
    # Demo session
    ui.session_start("interactive", "tabular_analyst")
    ui.user_input_display("Analyze this Excel file")
    ui.agent_label("tabular_analyst")
    ui.session_end()
