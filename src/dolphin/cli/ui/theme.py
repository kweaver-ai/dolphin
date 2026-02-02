"""
Theme and Styling Configuration for Dolphin CLI

This module defines the visual theme, colors, and styling used throughout
the CLI interface.
"""

from dataclasses import dataclass
from enum import Enum


class Theme:
    """Modern color theme inspired by Codex and Claude Code"""

    # ANSI escape codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Primary colors (muted, modern palette)
    PRIMARY = "\033[38;5;75m"       # Soft blue
    SECONDARY = "\033[38;5;183m"    # Soft purple
    ACCENT = "\033[38;5;216m"       # Peach/coral
    SUCCESS = "\033[38;5;114m"      # Soft green
    WARNING = "\033[38;5;221m"      # Soft yellow
    ERROR = "\033[38;5;210m"        # Soft red

    # Semantic colors
    TOOL_NAME = "\033[38;5;75m"     # Bright blue for tool names
    PARAM_KEY = "\033[38;5;183m"    # Purple for parameter keys
    PARAM_VALUE = "\033[38;5;223m"  # Warm white for values
    STRING_VALUE = "\033[38;5;114m" # Green for strings
    NUMBER_VALUE = "\033[38;5;216m" # Coral for numbers
    BOOLEAN_VALUE = "\033[38;5;221m"# Yellow for booleans
    NULL_VALUE = "\033[38;5;245m"   # Gray for null

    # UI elements
    BORDER = "\033[38;5;240m"       # Dark gray for borders
    BORDER_ACCENT = "\033[38;5;75m" # Blue accent for active borders
    LABEL = "\033[38;5;250m"        # Light gray for labels
    MUTED = "\033[38;5;245m"        # Muted text

    # Box drawing characters
    BOX_TOP_LEFT = "╭"
    BOX_TOP_RIGHT = "╮"
    BOX_BOTTOM_LEFT = "╰"
    BOX_BOTTOM_RIGHT = "╯"
    BOX_HORIZONTAL = "─"
    BOX_VERTICAL = "│"
    BOX_ARROW_RIGHT = "▶"
    BOX_ARROW_LEFT = "◀"
    BOX_DOT = "●"
    BOX_CIRCLE = "○"
    BOX_CHECK = "✓"
    BOX_CROSS = "✗"
    BOX_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Heavy box drawing characters for banner border
    HEAVY_TOP_LEFT = "┏"
    HEAVY_TOP_RIGHT = "┓"
    HEAVY_BOTTOM_LEFT = "┗"
    HEAVY_BOTTOM_RIGHT = "┛"
    HEAVY_HORIZONTAL = "━"
    HEAVY_VERTICAL = "┃"

    # ASCII Art Banner - Large pixel letters with shadow effect
    # Double-layer hollow design: outer frame (█) + inner hollow (░)
    # Each letter is 9 chars wide x 6 rows tall
    # Modern minimalist style with single color
    BANNER_LETTERS = {
        'D': [
            "████████ ",
            "██░░░░██ ",
            "██░░  ░█ ",
            "██░░  ░█ ",
            "██░░░░██ ",
            "████████ ",
        ],
        'O': [
            " ██████  ",
            "██░░░░██ ",
            "█░░  ░░█ ",
            "█░░  ░░█ ",
            "██░░░░██ ",
            " ██████  ",
        ],
        'L': [
            "██░░     ",
            "██░░     ",
            "██░░     ",
            "██░░     ",
            "██░░░░░░ ",
            "████████ ",
        ],
        'P': [
            "████████ ",
            "██░░░░██ ",
            "██░░░░██ ",
            "████████ ",
            "██░░     ",
            "██░░     ",
        ],
        'H': [
            "██░░ ░██ ",
            "██░░ ░██ ",
            "████████ ",
            "██░░░░██ ",
            "██░░ ░██ ",
            "██░░ ░██ ",
        ],
        'I': [
            "████████ ",
            " ░░██░░  ",
            "   ██    ",
            "   ██    ",
            " ░░██░░  ",
            "████████ ",
        ],
        'N': [
            "██░░ ░██ ",
            "███░ ░██ ",
            "██░█░░██ ",
            "██░░█░██ ",
            "██░ ░███ ",
            "██░░ ░██ ",
        ],
    }

    # Letter order - single color design (no gradient)
    BANNER_WORD = "DOLPHIN"
    # Unified color for hollow design (cyan/teal)
    BANNER_COLOR = "\033[38;5;80m"
    # Inner hollow color (darker, creates depth)
    BANNER_HOLLOW_COLOR = "\033[38;5;238m"


class StatusType(Enum):
    """Status types for visual indicators"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class BoxStyle:
    """Box drawing style configuration"""
    width: int = 80
    padding: int = 1
    show_border: bool = True
    border_color: str = Theme.BORDER
    accent_color: str = Theme.BORDER_ACCENT
