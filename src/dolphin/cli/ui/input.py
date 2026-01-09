"""
Input utilities with auto-completion and interrupt support.

Provides enhanced input prompts with:
- Tab/arrow-key completion for debug commands
- ESC key interrupt handling for agent execution
- Slash command shortcuts for conversation mode
"""

from typing import List, Optional, Callable, TYPE_CHECKING
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

if TYPE_CHECKING:
    from dolphin.cli.interrupt.handler import InterruptToken


# Debug command definitions for auto-completion
DEBUG_COMMANDS = [
    # Execution control
    ("step", "单步执行下一个 block"),
    ("next", "单步执行下一个 block (同 step)"),
    ("continue", "继续执行到下一个断点"),
    ("run", "运行到结束（忽略所有断点）"),
    ("until", "运行到指定 block: until <n>"),
    ("quit", "退出调试模式"),
    # Breakpoint management
    ("break", "设置断点: break <n>"),
    ("delete", "删除断点: delete <n>"),
    ("list", "显示所有断点"),
    # Variable inspection
    ("vars", "显示所有变量"),
    ("var", "显示特定变量: var <name>"),
    ("progress", "显示执行进度信息"),
    ("trace", "显示执行轨迹 - trace [brief/full] 默认简略"),
    ("trace full", "显示执行轨迹 (完整模式 - 不折叠只读消息)"),
    # Snapshot
    ("snapshot", "显示快照分析"),
    # Help
    ("help", "显示帮助信息"),
]

# Slash command shortcuts (for conversation mode)
# These are quick inspection commands - user types / and gets completions
# /debug enters interactive debug REPL, others execute once and return to conversation
SLASH_COMMANDS = [
    ("/debug", "进入实时调试交互模式 (REPL)"),
    ("/trace", "查看执行轨迹 默认简略"),
    ("/trace full", "查看执行轨迹 (完整模式 - 不折叠只读消息)"),
    ("/snapshot", "查看快照分析"),
    ("/vars", "查看所有变量"),
    ("/var", "查看特定变量: /var <name>"),
    ("/progress", "查看执行进度"),
    ("/help", "查看调试命令帮助"),
]


class DebugCommandCompleter(Completer):
    """Completer for debug commands.
    
    Supports both direct input (e.g., 'vars') and slash-prefixed input (e.g., '/vars').
    When user types '/', completions are shown but the actual command is without slash.
    """
    
    def __init__(self, commands: List[tuple]):
        """
        Args:
            commands: List of (command, description) tuples
        """
        self.commands = commands
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        
        # Handle slash prefix: "/va" -> complete to "vars" (strip the slash)
        has_slash = text.startswith("/")
        search_text = text[1:] if has_slash else text
        
        for cmd, desc in self.commands:
            cmd_lower = cmd.lower()
            
            if cmd_lower.startswith(search_text):
                # Always complete to command without slash (debug mode uses bare commands)
                yield Completion(
                    cmd_lower,
                    start_position=-len(document.text_before_cursor),
                    display_meta=desc,
                )


class ConversationCompleter(Completer):
    """Completer that only activates for slash commands in conversation mode."""
    
    def __init__(self):
        self.slash_commands = SLASH_COMMANDS
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        
        # Only show completions when text starts with "/"
        if not text.startswith("/"):
            return
        
        text_lower = text.lower()
        for cmd, desc in self.slash_commands:
            if cmd.startswith(text_lower):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )


# Shared PromptSession instances
_debug_session = PromptSession(history=InMemoryHistory())
_conversation_session = PromptSession(history=InMemoryHistory())


async def prompt_debug_command(prompt_text: str = "Debug > ", allow_execution_control: bool = True) -> str:
    """
    Prompt for debug command with auto-completion (async version).
    
    Args:
        prompt_text: The prompt string to display
        allow_execution_control: If False, exclude execution control commands from completion
    
    Returns:
        User input string
    """
    commands = DEBUG_COMMANDS
    if not allow_execution_control:
        # Filter out execution control commands for live debug / post-mortem
        execution_cmds = {"step", "next", "continue", "run", "until"}
        commands = [(cmd, desc) for cmd, desc in commands if cmd not in execution_cmds]
    
    completer = DebugCommandCompleter(commands)
    
    try:
        return (await _debug_session.prompt_async(
            prompt_text,
            completer=completer,
            complete_while_typing=True,
        )).strip()
    except (EOFError, KeyboardInterrupt):
        raise


async def prompt_conversation(prompt_text: str = "\n> ") -> str:
    """
    Prompt for user input in conversation mode with slash-command completion (async version).

    Args:
        prompt_text: The prompt string to display

    Returns:
        User input string
    """
    completer = ConversationCompleter()

    try:
        return (await _conversation_session.prompt_async(
            prompt_text,
            completer=completer,
            complete_while_typing=True,
        )).strip()
    except (EOFError, KeyboardInterrupt):
        raise


class EscapeInterrupt(Exception):
    """Exception raised when ESC key is pressed during prompt."""
    pass


def create_interrupt_key_bindings(
    interrupt_token: Optional["InterruptToken"] = None
) -> KeyBindings:
    """Create key bindings that handle ESC for interrupt.

    Args:
        interrupt_token: Optional InterruptToken to trigger on ESC

    Returns:
        KeyBindings with ESC handler
    """
    kb = KeyBindings()

    @kb.add(Keys.Escape)
    def handle_escape(event):
        """Handle ESC key press to trigger interrupt."""
        if interrupt_token:
            interrupt_token.trigger_interrupt()
        # Use app.exit with exception - the proper way to exit prompt_toolkit
        event.app.exit(exception=EscapeInterrupt())

    return kb


# Session for interrupt-aware prompts
_interrupt_session: Optional[PromptSession] = None


def _get_interrupt_session() -> PromptSession:
    """Get or create the interrupt-aware prompt session."""
    global _interrupt_session
    if _interrupt_session is None:
        _interrupt_session = PromptSession(history=InMemoryHistory())
    return _interrupt_session


async def prompt_with_interrupt(
    prompt_text: str = "> ",
    interrupt_token: Optional["InterruptToken"] = None,
    completer: Optional[Completer] = None,
    default_text: str = ""
) -> str:
    """
    Prompt for user input with ESC key interrupt support.

    When ESC is pressed, the interrupt_token is triggered and EscapeInterrupt
    is raised. The caller should catch this and handle the interrupt appropriately.

    Args:
        prompt_text: The prompt string to display
        interrupt_token: InterruptToken to trigger on ESC press
        completer: Optional completer for auto-completion
        default_text: Initial text to pre-fill the input buffer

    Returns:
        User input string

    Raises:
        EscapeInterrupt: When ESC key is pressed
        EOFError: When Ctrl+D is pressed
        KeyboardInterrupt: When Ctrl+C is pressed
    """
    session = _get_interrupt_session()
    key_bindings = create_interrupt_key_bindings(interrupt_token)

    # Use ConversationCompleter if no completer provided
    if completer is None:
        completer = ConversationCompleter()

    try:
        return (await session.prompt_async(
            prompt_text,
            key_bindings=key_bindings,
            completer=completer,
            complete_while_typing=True,
            default=default_text,
        )).strip()
    except EscapeInterrupt:
        raise
    except (EOFError, KeyboardInterrupt):
        raise


async def prompt_interrupt_input(prompt_text: str = "💬 New instructions (Enter to continue): ") -> str:
    """
    Prompt for user input after an interrupt.

    This is a simplified prompt without ESC handling, used after execution
    has been interrupted to get the user's new instructions.

    Args:
        prompt_text: The prompt string to display

    Returns:
        User input string (may be empty if user just pressed Enter)
    """
    session = PromptSession()

    try:
        return (await session.prompt_async(prompt_text)).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
