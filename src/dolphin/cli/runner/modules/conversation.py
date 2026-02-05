"""
Conversation Loop Module

This module handles the interactive conversation loop for Dolphin agents,
including user input prompting, interrupt handling, and execution flow control.

Key Features:
- Interactive conversation loop with fixed layout support
- ESC key interrupt handling for agent execution
- Multi-modal input support (text, images, URLs)
- Real-time debug command processing
- Status bar with spinner animation during processing

Extracted Functions:
- _handle_user_interrupt: Handle user interrupts (ESC or Ctrl-C)
- runConversationLoop: Main conversation loop orchestration
- _promptUserInput: Prompt user for input with interrupt support
"""

import asyncio
import sys
from typing import Any, Dict, Optional, Tuple

from dolphin.core import flags
from dolphin.core.agent.agent_state import AgentState, PauseType
from dolphin.core.common.exceptions import DebuggerQuitException, UserInterrupt
from dolphin.core.logging.logger import console

from dolphin.cli.args.parser import Args
from dolphin.cli.utils.helpers import outputVariablesToJson
from dolphin.cli.interrupt.handler import InterruptToken
from dolphin.cli.ui.layout import LayoutManager
from dolphin.cli.ui.console import console_session_start, console_display_session_info


def _handle_user_interrupt(agent, layout, source: str) -> None:
    """Handle user interrupt (ESC or Ctrl-C) by setting up agent state for resumption.

    This is a shared handler for both UserInterrupt and asyncio.CancelledError,
    as they have identical semantics: user wants to provide new input.

    Args:
        agent: The DolphinAgent instance
        layout: The LayoutManager instance
        source: String identifying the interrupt source for logging ("UserInterrupt" or "CancelledError")
    """
    from dolphin.cli.ui.components import StatusBar

    layout.hide_status()

    # Set agent state for proper resumption with context preservation
    agent._state = AgentState.PAUSED
    agent._pause_type = PauseType.USER_INTERRUPT

    # Clear the interrupt event so future calls don't immediately re-interrupt
    if hasattr(agent, 'clear_interrupt'):
        agent.clear_interrupt()
    elif hasattr(agent, 'get_interrupt_event'):
        event = agent.get_interrupt_event()
        if event:
            event.clear()

    StatusBar._debug_log(f"_handle_user_interrupt: handled {source}, agent state set to PAUSED/USER_INTERRUPT")


async def runConversationLoop(agent, args: Args, initialVariables: Dict[str, Any]) -> bool:
    """Run the main conversation loop with fixed layout and interrupt support.

    Args:
        agent: Agent instance
        args: Parsed CLI arguments
        initialVariables: Initial variables

    Returns:
        True if should enter post-mortem after interactive mode ends
    """
    # Initialize layout manager and interrupt token
    layout = LayoutManager(enabled=args.interactive)
    interrupt_token = InterruptToken()

    # Initialize event dispatcher for Plan UI
    from dolphin.cli.ui.event_dispatcher import CLIEventDispatcher
    event_dispatcher = CLIEventDispatcher(layout=layout, verbose=args.saveHistory)

    currentQuery = args.query

    if currentQuery:
        agent.add_bucket(bucket_name="_query", content=currentQuery)

    if args.interactive:
        mode = "Interactive"
        # Setup scroll region FIRST, then print banner inside the scrollable area
        layout.start_session(mode, args.agent)
        console_session_start(mode, args.agent)

        # Display available skillkits and command hints
        from dolphin.cli.runner.modules.agent_lifecycle import _get_skillkit_info
        skillkit_info = _get_skillkit_info(agent)
        console_display_session_info(skillkit_info, show_commands=True)

        if flags.is_enabled(flags.DEBUG_MODE):
            console("💡 输入 /debug 进入实时调试，/trace /snapshot /vars 快速查看", verbose=args.saveHistory)
    else:
        mode = "Execution"
        # No layout for non-interactive mode, just print banner
        console_session_start(mode, args.agent)

        # Display available skillkits (no command hints in non-interactive mode)
        from dolphin.cli.runner.modules.agent_lifecycle import _get_skillkit_info
        skillkit_info = _get_skillkit_info(agent)
        console_display_session_info(skillkit_info, show_commands=False)

    isFirstExecution = True
    enterPostmortemAfterInteractive = False

    # DEBUG: Import StatusBar for logging
    from dolphin.cli.ui.components import StatusBar
    StatusBar._debug_log(f"runConversationLoop: starting, interactive={args.interactive}, currentQuery={currentQuery!r}")

    try:
        # Bind interrupt token to agent and event loop
        interrupt_token.bind(agent, asyncio.get_running_loop())

        while True:
            StatusBar._debug_log(f"runConversationLoop: loop iteration, isFirstExecution={isFirstExecution}, currentQuery={currentQuery!r}")

            # Prompt for input if not first execution and interactive mode
            if not currentQuery and args.interactive and not isFirstExecution:
                StatusBar._debug_log(f"runConversationLoop: calling _promptUserInput")
                currentQuery, shouldBreak, debugCommand = await _promptUserInput(
                    args, interrupt_token
                )

                # Handle live debug command
                if debugCommand is not None:
                    from dolphin.cli.runner.modules.debugger import _handleLiveDebugCommand
                    await _handleLiveDebugCommand(agent, debugCommand)
                    currentQuery = None
                    continue

                if shouldBreak:
                    if flags.is_enabled(flags.DEBUG_MODE) and args.interactive:
                        enterPostmortemAfterInteractive = True
                    break

            try:
                # Clear interrupt state before execution
                interrupt_token.clear()

                # Show inline status bar (simplified - no fixed positioning)
                if args.interactive:
                    layout.show_status("Processing your request", "esc to interrupt")

                # Start keyboard monitor for ESC interrupt
                monitor_stop = None
                monitor_task = None
                if args.interactive:
                    import threading
                    from dolphin.cli.interrupt.keyboard import _monitor_interrupt
                    monitor_stop = threading.Event()
                    monitor_task = asyncio.create_task(_monitor_interrupt(interrupt_token, monitor_stop))

                try:
                    if isFirstExecution:
                        StatusBar._debug_log(f"runConversationLoop: running first execution")
                        from dolphin.cli.runner.modules.execution import _runFirstExecution
                        await _runFirstExecution(agent, args, initialVariables, event_dispatcher)
                        isFirstExecution = False
                        StatusBar._debug_log(f"runConversationLoop: first execution done")
                    else:
                        from dolphin.cli.runner.modules.execution import _runSubsequentExecution
                        await _runSubsequentExecution(agent, args, currentQuery, event_dispatcher)
                finally:
                    # Stop keyboard monitor
                    if monitor_stop:
                        monitor_stop.set()
                    if monitor_task:
                        try:
                            await monitor_task
                        except:
                            pass

                # Hide status bar after completion
                if args.interactive:
                    layout.hide_status()
                    StatusBar._debug_log(f"runConversationLoop: status bar hidden")

            except DebuggerQuitException:
                layout.hide_status()
                console("✅ 调试会话已结束。")
                break
            except UserInterrupt:
                # UserInterrupt: user pressed ESC, interrupt() was called
                StatusBar._debug_log(f"runConversationLoop: UserInterrupt caught, continuing loop")
                if args.interactive:
                    _handle_user_interrupt(agent, layout, "UserInterrupt")
                    isFirstExecution = False
                else:
                    raise
            except asyncio.CancelledError:
                # CancelledError: Ctrl-C SIGINT or asyncio task cancellation
                StatusBar._debug_log(f"runConversationLoop: CancelledError caught, continuing loop")
                if args.interactive:
                    _handle_user_interrupt(agent, layout, "CancelledError")
                    isFirstExecution = False
                else:
                    raise
            except Exception as e:
                StatusBar._debug_log(f"runConversationLoop: Exception caught: {type(e).__name__}: {e}")
                raise

            currentQuery = None
            StatusBar._debug_log(f"runConversationLoop: after execution, about to check interactive={args.interactive}")


            if not args.interactive:
                StatusBar._debug_log(f"runConversationLoop: not interactive, breaking")
                break

        # Final output for interactive mode
        if args.interactive and args.outputVariables:
            outputVariablesToJson(agent.get_context(), args.outputVariables)

    finally:
        StatusBar._debug_log(f"runConversationLoop: finally block executing")
        # Cleanup event dispatcher
        event_dispatcher.cleanup()
        # Cleanup
        interrupt_token.unbind()
        if args.interactive:
            layout.end_session()

    return enterPostmortemAfterInteractive


async def _promptUserInput(
    args: Args,
    interrupt_token: Optional[InterruptToken] = None
) -> Tuple[Optional[Any], bool, Optional[str]]:
    """Prompt user for input in interactive mode with ESC interrupt support.

    Simplified version: input follows content naturally, no scroll region management.

    Args:
        args: Parsed CLI arguments
        interrupt_token: Optional InterruptToken for ESC handling

    Returns:
        Tuple of (query, shouldBreak, debugCommand)
        - query: User query string or None
        - shouldBreak: Whether to break the conversation loop
        - debugCommand: Debug command if user requested live debug, else None
    """
    try:
        from dolphin.cli.ui.input import (
            prompt_conversation_with_multimodal,
            EscapeInterrupt
        )
        from dolphin.cli.ui.components import StatusBar

        StatusBar._debug_log(f"_promptUserInput: starting (simplified)")

        # Ensure cursor is visible before prompting
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

        try:
            # Get any real-time input buffered while the agent was running
            default_text = ""
            if interrupt_token:
                default_text = interrupt_token.get_realtime_input(consume=True)
                if default_text:
                    StatusBar._debug_log(f"_promptUserInput: found realtime buffer: {default_text!r}")

            # Use multimodal-aware prompt that processes @paste, @image:, @url: syntax
            # Returns: str for plain text, List[Dict] for multimodal content
            currentQuery = await prompt_conversation_with_multimodal(
                prompt_text="> ",
                interrupt_token=interrupt_token,
                verbose=True
            )
            StatusBar._debug_log(f"_promptUserInput: got input: {currentQuery!r}")

        except EscapeInterrupt:
            # ESC pressed during input - treat as empty input
            StatusBar._debug_log(f"_promptUserInput: EscapeInterrupt")
            return None, False, None

    except (EOFError, KeyboardInterrupt):
        from dolphin.cli.ui.console import console_conversation_end
        console_conversation_end()
        return None, True, None

    # Handle multimodal content (List[Dict]) - return directly without string checks
    if isinstance(currentQuery, list):
        # This is multimodal content, return as-is
        return currentQuery, False, None

    # For string input, check exit commands and debug prefixes
    if not currentQuery or currentQuery.lower().strip() in ["exit", "quit", "q", ""]:
        console("Conversation ended", verbose=args.saveHistory)
        return None, True, None

    # Check for debug command prefixes (live debug mode)
    # /debug enters REPL, others execute once and return to conversation
    debugPrefixes = {
        "/debug": None,      # /debug or /debug <cmd> -> enters REPL or executes single cmd
        "/trace": "trace",
        "/snapshot": "snapshot",
        "/vars": "vars",
        "/var": "var",
        "/progress": "progress",
        "/help": "help",
    }

    queryLower = currentQuery.lower()
    for prefix, defaultCmd in debugPrefixes.items():
        if queryLower.startswith(prefix):
            # Extract the debug command
            remainder = currentQuery[len(prefix):].strip()
            if defaultCmd:
                # For /trace, /snapshot, etc., the command is the prefix itself
                debugCmd = f"{defaultCmd} {remainder}".strip() if remainder else defaultCmd
            else:
                # For /debug, remainder is the full command (or 'help' if empty)
                debugCmd = remainder if remainder else "help"
            return None, False, debugCmd

    return currentQuery, False, None
