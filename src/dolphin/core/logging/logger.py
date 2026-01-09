import logging
import os
import json
import contextvars
import re
from typing import Optional, List
from contextlib import contextmanager

"""_dolphin_logger is the global logger for Dolphin SDK.

Developers can customize the logger configuration using the setup_logger() method.
Internal modules of Dolphin SDK can obtain the global logger of Dolphin SDK using the get_logger() method.
By default, the global logger of Dolphin SDK is created using the setup_default_logger() method.
"""
_dolphin_logger = None

MaxLenLog = 4096

# Context variable storage, used to support independent log files during asyncio coroutine parallelization
# Fix: Changed from threading.local() to contextvars.ContextVar to support asynchronous coroutine isolation
_extra_log_file_var = contextvars.ContextVar("extra_log_file", default=None)

# Default logger name for Dolphin SDK
SDK_LOGGER_NAME = "dolphin_language"

# Pre-compiled ANSI escape sequences for removing console color codes
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ANSI color codes
class Colors:
    # Basic Colors
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground color
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Light color
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background color
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


def colorize(text, color):
    """Add color to text"""
    return f"{color}{text}{Colors.RESET}"


def _strip_ansi(s: str) -> str:
    """Remove ANSI color control codes for writing plain text logs"""
    return _ANSI_RE.sub("", s)


@contextmanager
def extra_log_context(file_path: Optional[str]):
    """Set additional log output context (based on contextvars, supports multi-coroutine isolation)

        Usage example:
            with extra_log_context('path/to/detail.log'):
                ...  # Calls to _write_to_extra_log/console within this context will also write to detail.log

        Args:
            file_path: Path to the additional log file, None means disable additional logging
    """
    # Ensure the parent directory exists (if a path is provided)
    if file_path:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
        except Exception:
            # Directory creation failure does not affect the main process
            pass

    token = _extra_log_file_var.set(file_path)
    try:
        yield
    finally:
        # Restore previous context value
        try:
            _extra_log_file_var.reset(token)
        except Exception:
            # If the context has expired, silently ignore it.
            pass


def write_to_log_file(text: str, *, ensure_newline: bool = True):
    """Write a line to an additional log file (if additional log context exists).

    - Automatically remove ANSI color codes and write plain text
    - Open in append mode to avoid persistently holding file handles
    - Thread-safe and coroutine-safe (write granularity is single write)

    Args:
        text: The text to write.
        ensure_newline: Whether to ensure the text ends with a newline.
    """
    file_path = _extra_log_file_var.get()
    if not file_path:
        return
    try:
        s = str(text)
        if ensure_newline and not s.endswith("\n"):
            s += "\n"
        s = _strip_ansi(s)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(s)
    except Exception:
        # Any log writing errors should not affect the main process
        pass

# Alias for internal backward compatibility
_write_to_extra_log = write_to_log_file


def setup_logger(
    level: int = logging.INFO,
    format: str = "%(asctime)s - %(levelname)s - %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    handlers: Optional[List[logging.Handler]] = None,
    propagate: bool = False,
    force: bool = False,
) -> None:
    """Set up the logger.

        :param level: Log level, default is logging.INFO
        :param format: Log format, default is logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        :param datefmt: Date format, default is "%Y-%m-%d %H:%M:%S"
        :param handlers: List of log handlers, default is None
        :param propagate: Whether to propagate logs, default is False
        :param fore: Whether to clear existing handlers
    """
    _dolphin_logger = logging.getLogger(SDK_LOGGER_NAME)

    # Avoid duplicate configuration
    if not force and _dolphin_logger.handlers:
        return

    # Set log level
    _dolphin_logger.setLevel(level)

    # Set whether to pass to the parent logger
    _dolphin_logger.propagate = propagate

    formatter = logging.Formatter(format, datefmt)

    if handlers:
        for handler in handlers:
            handler.setFormatter(formatter)
            _dolphin_logger.addHandler(handler)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        _dolphin_logger.addHandler(console_handler)


def get_logger(sub_name: str = "") -> logging.Logger:
    """Get the logger with the specified name.

        :param name: The name of the logger
        :return: The logger object
    """
    logger_name = f"{SDK_LOGGER_NAME}.{sub_name}" if sub_name else SDK_LOGGER_NAME
    return logging.getLogger(logger_name)


# Set the default logger
def setup_default_logger(log_suffix: Optional[str] = None):
    global _dolphin_logger

    # If a logger already exists and no suffix is specified, return directly.
    if _dolphin_logger is not None and log_suffix is None:
        return _dolphin_logger

    # If a suffix is specified, reconfiguration is required.
    if log_suffix is not None and _dolphin_logger is not None:
        # Clear existing processors
        _dolphin_logger.handlers.clear()

    _dolphin_logger = logging.getLogger(SDK_LOGGER_NAME)
    _dolphin_logger.setLevel(logging.INFO)
    _dolphin_logger.propagate = False

    # Avoid duplicate processor addition
    if not _dolphin_logger.handlers:
        # Allow customizing log directory and file suffix via environment variables
        # DOLPHIN_LOG_DIR: log directory (default "log")
        # DOLPHIN_LOG_SUFFIX: File name suffix (default no suffix)
        env_log_dir = os.getenv("DOLPHIN_LOG_DIR", "log")
        env_suffix = os.getenv("DOLPHIN_LOG_SUFFIX")
        # If log_suffix is not explicitly passed in, respect the environment variable
        if log_suffix is None and env_suffix:
            log_suffix = env_suffix

        # Ensure the directory exists
        try:
            os.makedirs(env_log_dir, exist_ok=True)
        except Exception:
            # Failed to create directory, revert to default directory
            env_log_dir = "log"
            os.makedirs(env_log_dir, exist_ok=True)

        # Build log filename
        if log_suffix:
            log_file = os.path.join(env_log_dir, f"dolphin_{log_suffix}.log")
        else:
            log_file = os.path.join(env_log_dir, "dolphin.log")

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        _dolphin_logger.addHandler(file_handler)


# Initialize the default logger
setup_default_logger()


def _format_json_compact(data, max_width=80):
    """Format JSON data, keeping it compact within a reasonable width"""
    if isinstance(data, dict):
        json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(json_str) <= max_width:
            return json_str
        else:
            # If too long, try formatting
            formatted = json.dumps(data, ensure_ascii=False, indent=2)
            lines = formatted.split("\n")
            if len(lines) <= 5:  # If the number of lines is not large, return the formatted version
                return formatted
            else:  # Otherwise, return the truncated compact version
                if len(json_str) > max_width:
                    return json_str[: max_width - 3] + "..."
                return json_str
    return str(data)


def _stdout(value: str, info: bool = False, **kwargs):
    if info or ("verbose" in kwargs and kwargs["verbose"]):
        # Console Output
        print(value, **{k: v for k, v in kwargs.items() if k in ["end", "flush"]})
        # Synchronously write additional logs (if context is set)
        end = kwargs.get("end", "\n")
        if end:
            _write_to_extra_log(
                value + ("" if end is None else end), ensure_newline=False
            )
        else:
            _write_to_extra_log(value, ensure_newline=False)


def console_skill_call(skill_name, params, max_length=200, verbose=None, skill=None):
    """Display skill/tool call with modern styling.
    
    This function uses the new console_ui module for enhanced visual display
    inspired by Codex CLI and Claude Code's terminal interfaces.
    
    Supports custom UI rendering via Skillkit.has_custom_ui() protocol.
    
    Args:
        skill_name: Name of the skill being called
        params: Parameters passed to the skill
        max_length: Maximum length for parameter display
        verbose: Whether to display (None uses default, False suppresses)
        skill: Optional SkillFunction object (for custom UI lookup)
    """
    if verbose is False:
        return

    # Check if skill has custom UI rendering
    if skill and hasattr(skill, 'owner_skillkit') and skill.owner_skillkit:
        skillkit = skill.owner_skillkit
        if hasattr(skillkit, 'has_custom_ui') and skillkit.has_custom_ui(skill_name):
            # Use custom rendering (start phase)
            if hasattr(skillkit, 'render_skill_start'):
                skillkit.render_skill_start(skill_name, params, verbose=verbose if verbose is not None else True)
            return  # Skip default rendering

    try:
        from dolphin.cli.ui.console import get_console_ui
        ui = get_console_ui()
        ui.skill_call_start(skill_name, params, max_length, verbose=True)
    except ImportError:
        # Fallback to legacy display if console_ui not available
        header = f"{Colors.BOLD}{Colors.BRIGHT_CYAN}🔧 CALL SKILL{Colors.RESET} {Colors.BOLD}{Colors.BRIGHT_YELLOW}<{skill_name}>{Colors.RESET}"
        separator = f"{Colors.DIM}{Colors.BRIGHT_BLACK}{'─' * 60}{Colors.RESET}"
        formatted_params = _format_json_compact(params, max_width=100)
        if len(formatted_params) > max_length:
            formatted_params = formatted_params[:max_length] + "..."
        input_line = f"{Colors.BRIGHT_GREEN}>>> {Colors.RESET}{Colors.CYAN}{formatted_params}{Colors.RESET}"
        print(separator)
        print(header)
        print(input_line)


def console_skill_response(skill_name, response, max_length=200, verbose=None, skill=None, params=None, duration_ms=0):
    """Display skill/tool response with modern styling.
    
    This function uses the new console_ui module for enhanced visual display
    inspired by Codex CLI and Claude Code's terminal interfaces.
    
    Supports custom UI rendering via Skillkit.has_custom_ui() protocol.
    
    Args:
        skill_name: Name of the skill that completed
        response: Response from the skill
        max_length: Maximum length for response display
        verbose: Whether to display (None uses default, False suppresses)
        skill: Optional SkillFunction object (for custom UI lookup)
        params: Optional parameters that were passed to the skill
        duration_ms: Execution duration in milliseconds
    """
    from dolphin.lib.skillkits.cognitive_skillkit import CognitiveSkillkit

    if CognitiveSkillkit.is_cognitive_skill(skill_name):
        return

    if verbose is False:
        return

    # Check if skill has custom UI rendering
    if skill and hasattr(skill, 'owner_skillkit') and skill.owner_skillkit:
        skillkit = skill.owner_skillkit
        if hasattr(skillkit, 'has_custom_ui') and skillkit.has_custom_ui(skill_name):
            # Use custom rendering (end phase)
            if hasattr(skillkit, 'render_skill_end'):
                skillkit.render_skill_end(
                    skill_name,
                    params or {},
                    response,
                    success=True,
                    duration_ms=duration_ms,
                    verbose=verbose if verbose is not None else True
                )
            return  # Skip default rendering

    try:
        from dolphin.cli.ui.console import get_console_ui
        ui = get_console_ui()
        ui.skill_call_end(skill_name, response, max_length, success=True, verbose=True)
    except ImportError:
        # Fallback to legacy display if console_ui not available
        if isinstance(response, dict):
            display_response = _format_json_compact(response, max_width=100)
        elif not isinstance(response, str):
            display_response = str(response)
        else:
            display_response = response

        if len(display_response) > max_length:
            display_response = display_response[:max_length] + "..."

        output_line = f"{Colors.BRIGHT_BLUE}<<< {Colors.RESET}{Colors.BRIGHT_WHITE}{display_response}{Colors.RESET}"
        separator = f"{Colors.DIM}{Colors.BRIGHT_BLACK}{'─' * 60}{Colors.RESET}"
        print(f"\n{output_line}")
        print(f"{separator}\n")


def console_agent_skill_exit(skill_name: str, message: str = None, verbose=None):
    """Display a delimiter indicating an agent-as-skill has exited.

    This keeps terminal formatting concerns in the UI layer.
    """
    if verbose is False:
        return

    try:
        from dolphin.cli.ui.console import get_console_ui

        ui = get_console_ui()
        ui.agent_skill_exit(skill_name, message=message, verbose=True)
    except ImportError:
        # Fallback: plain separator
        label = message or f" AGENT EXITED: {skill_name}"
        print("\n" + ("─" * 10) + label + ("─" * 10) + "\n")


def console_agent_skill_enter(skill_name: str, message: str = None, verbose=None):
    """Display a delimiter indicating an agent-as-skill has started.
    
    This keeps terminal formatting concerns in the UI layer.
    """
    if verbose is False:
        return

    try:
        from dolphin.cli.ui.console import get_console_ui
        ui = get_console_ui()
        ui.agent_skill_enter(skill_name, message=message, verbose=True)
    except ImportError:
        label = message or f"🚀 AGENT ACTIVATE: {skill_name}"
        print(f"\n===== {label} =====\n")


def console_block_start(
    block_name: str, output_var: str, content: Optional[str] = None, verbose=None
):
    """Display code block start with modern styling.
    
    This function uses the new console_ui module for enhanced visual display
    inspired by Codex CLI and Claude Code's terminal interfaces.
    
    Args:
        block_name: Type of block (explore, prompt, judge, assign, tool)
        output_var: Variable name to store the output
        content: Optional content preview
        verbose: Whether to display (None uses default, False suppresses)
    """
    if verbose is False:
        return

    try:
        from dolphin.cli.ui.console import get_console_ui
        ui = get_console_ui()
        ui.block_start(block_name, output_var, content, verbose=True)
    except ImportError:
        # Fallback to legacy display if console_ui not available
        block_icons = {
            "explore": "🔍",
            "prompt": "💬",
            "judge": "⚖️",
            "assign": "📝",
            "tool": "🔧",
        }

        block_colors = {
            "explore": Colors.BRIGHT_MAGENTA,
            "prompt": Colors.BRIGHT_GREEN,
            "judge": Colors.BRIGHT_YELLOW,
            "assign": Colors.BRIGHT_BLUE,
            "tool": Colors.BRIGHT_CYAN,
        }

        icon = block_icons.get(block_name, "📦")
        color = block_colors.get(block_name, Colors.BRIGHT_WHITE)

        header = f"{color}{Colors.BOLD}{icon} {block_name.upper()}{Colors.RESET}"
        var_name = f"{Colors.BRIGHT_CYAN}{output_var}{Colors.RESET}"
        arrow = f"{Colors.DIM}→{Colors.RESET}"

        if content:
            content = str(content)
            if content.strip():
                content_preview = (
                    content.strip()[:50] + "..."
                    if len(content.strip()) > 50
                    else content.strip()
                )
                content_part = f" {Colors.DIM}{content_preview}{Colors.RESET}"
            else:
                content_part = ""
        else:
            content_part = ""

        output_line = f"{header} {var_name} {arrow}{content_part}"
        print(output_line)


def set_log_level(level: int = logging.INFO, force: bool = False):
    """Dynamically set the log level of the global logger

        Args:
            level: Log level, such as logging.DEBUG, logging.INFO, logging.WARNING, etc.
            force: Whether to forcibly set, even if the logger already has handlers
    """
    global _dolphin_logger

    if _dolphin_logger is None:
        # If the logger has not been initialized yet, initialize it first.
        setup_default_logger()
    _dolphin_logger.setLevel(level)

    # If forcibly set, clear existing handlers and reset them.
    if force:
        _dolphin_logger.handlers.clear()
        setup_default_logger()
        _dolphin_logger.setLevel(level)


def console(info, verbose=None, **kwargs):
    """Console output function, supports verbose parameter control

        Args:
            info: Information to be output
            verbose: Whether to display detailed information (if None, determine based on the logic in _stdout)
            **kwargs: Other parameters, such as end, flush, etc.
    """
    if verbose is not None:
        # If the verbose parameter is explicitly specified, use that value.
        if "end" in kwargs:
            _stdout(str(info), info=verbose, flush=True, end=kwargs["end"])
        else:
            _stdout(str(info), info=verbose, flush=True)
    else:
        # Keep the original logic and get verbose from kwargs
        if "end" in kwargs:
            _stdout(str(info), info=True, flush=True, end=kwargs["end"])
        else:
            _stdout(str(info), info=True, flush=True)


