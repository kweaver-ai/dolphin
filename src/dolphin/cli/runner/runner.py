"""
Dolphin Agent Runner

This module contains the execution logic for running Dolphin agents.
The main runDolphinAgent function has been refactored into smaller,
single-responsibility functions for better maintainability.

Features:
- Fixed bottom input layout with scrollable content
- ESC key interrupt support for agent execution
- Status bar with spinner animation during processing
"""

import asyncio
import datetime
import json
import logging
import os
import random
import sys
import traceback
import uuid
from typing import Any, Dict, Optional

from rich.console import Console as RichConsole

from dolphin.core import flags
from dolphin.core.common.exceptions import DebuggerQuitException, UserInterrupt
from dolphin.core.agent.agent_state import AgentState, PauseType
from dolphin.core.logging.logger import console
from dolphin.cli.ui.console import console_session_start, console_display_session_info

from dolphin.cli.args.parser import Args
from dolphin.cli.utils.helpers import buildVariables, outputVariablesToJson
from dolphin.cli.interrupt.handler import InterruptToken
from dolphin.cli.ui.layout import LayoutManager


async def initializeEnvironment(args: Args):
    """Initialize Dolphin environment
    
    Args:
        args: Parsed CLI arguments
        
    Returns:
        Tuple of (env, globalConfig)
    """
    from dolphin.sdk.runtime.env import Env
    from dolphin.core.config.global_config import GlobalConfig
    
    globalConfigPath = args.config if args.config else "./config/global.yaml"
    globalConfig = GlobalConfig.from_yaml(globalConfigPath)
    
    env = Env(
        globalConfig=globalConfig,
        agentFolderPath=args.folder,
        skillkitFolderPath=args.skillFolder,
        output_variables=[],
        verbose=args.saveHistory,
        is_cli=True,  # CLI mode: enable Rich/terminal beautification
        log_level=(
            logging.DEBUG if flags.is_enabled(flags.DEBUG_MODE) else logging.INFO
        ),
    )
    
    return env, globalConfig


async def loadAndPrepareAgent(env, args: Args, initialVariables: Dict[str, Any]):
    """Load and prepare agent for execution
    
    Args:
        env: Dolphin environment
        args: Parsed CLI arguments
        initialVariables: Initial variables to pass to agent
        
    Returns:
        Prepared agent instance
    """
    from dolphin.sdk.agent.dolphin_agent import DolphinAgent
    
    availableAgents = env.getAgentNames()
    
    if args.agent not in availableAgents:
        console(f"Error: Agent '{args.agent}' not found in folder '{args.folder}'")
        console(f"Available agents: {availableAgents}")
        sys.exit(1)
    
    agent = env.getAgent(args.agent)
    
    # Check if agent is in ERROR state and reset if needed
    if (agent is not None and hasattr(agent, "state") and agent.state.name == "ERROR"):
        agent = await _recoverAgentFromError(env, args, agent)
    
    await agent.initialize()
    
    if agent is None:
        console(f"Error: Failed to get agent instance for '{args.agent}'")
        sys.exit(1)
    
    # Configure trajectory
    if args.trajectoryPath:
        agent.set_trajectorypath(args.trajectoryPath)
    agent.set_agent_name(args.agent)
    
    # Setup context
    env._setupAgentContext(agent)
    
    # Initialize with variables
    if initialVariables:
        initParams = {"variables": initialVariables}
        await agent.executor.executor_init(initParams)
    
    return agent


async def _recoverAgentFromError(env, args: Args, agent):
    """Recover agent from ERROR state
    
    Args:
        env: Dolphin environment
        args: Parsed CLI arguments
        agent: Agent in error state
        
    Returns:
        Recovered agent instance
    """
    from dolphin.sdk.agent.dolphin_agent import DolphinAgent
    
    agentFilePath = None
    for filePath in env._scanDolphinFiles(args.folder):
        try:
            tempAgent = DolphinAgent(
                file_path=filePath,
                global_config=env.globalConfig,
                global_skills=env.globalSkills,
                global_types=env.global_types,
            )
            if tempAgent.get_name() == args.agent:
                agentFilePath = filePath
                break
        except Exception:
            continue
    
    if agentFilePath:
        freshAgent = DolphinAgent(
            file_path=agentFilePath,
            global_config=env.globalConfig,
            global_skills=env.globalSkills,
            global_types=env.global_types,
        )
        env.agents[args.agent] = freshAgent
        return freshAgent
    else:
        console(
            f"Warning: Could not find file path for agent '{args.agent}', "
            "proceeding with existing instance"
        )
        return agent


def _get_skillkit_info(agent) -> Optional[Dict[str, int]]:
    """Extract skillkit information from agent for display.

    Args:
        agent: The DolphinAgent instance

    Returns:
        Dict mapping skillkit name to tool count, or None if unavailable
    """
    try:
        context = agent.get_context()
        if context is None:
            return None

        all_skills = context.all_skills.getSkills() if context.all_skills else []
        if not all_skills:
            return None

        # Group skills by owner skillkit name
        skillkit_counts: Dict[str, int] = {}
        for skill in all_skills:
            owner_name = getattr(skill, 'owner_name', None)
            if owner_name:
                skillkit_counts[owner_name] = skillkit_counts.get(owner_name, 0) + 1
            else:
                # Skills without owner go to "builtin"
                skillkit_counts["builtin"] = skillkit_counts.get("builtin", 0) + 1

        return skillkit_counts if skillkit_counts else None
    except Exception:
        return None


def _handle_user_interrupt(agent, layout, source: str) -> None:
    """Handle user interrupt (ESC or Ctrl-C) by setting up agent state for resumption.

    This is a shared handler for both UserInterrupt and asyncio.CancelledError,
    as they have identical semantics: user wants to provide new input.

    Args:
        agent: The DolphinAgent instance
        layout: The LayoutManager instance
        source: String identifying the interrupt source for logging ("UserInterrupt" or "CancelledError")
    """
    from dolphin.core.agent.agent_state import AgentState, PauseType
    from dolphin.cli.ui.console import StatusBar
    
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

    currentQuery = args.query

    if currentQuery:
        agent.add_bucket(bucket_name="_query", content=currentQuery)

    if args.interactive:
        mode = "Interactive"
        # Setup scroll region FIRST, then print banner inside the scrollable area
        layout.start_session(mode, args.agent)
        console_session_start(mode, args.agent)

        # Display available skillkits and command hints
        skillkit_info = _get_skillkit_info(agent)
        console_display_session_info(skillkit_info, show_commands=True)

        if flags.is_enabled(flags.DEBUG_MODE):
            console("💡 输入 /debug 进入实时调试，/trace /snapshot /vars 快速查看", verbose=args.saveHistory)
    else:
        mode = "Execution"
        # No layout for non-interactive mode, just print banner
        console_session_start(mode, args.agent)

        # Display available skillkits (no command hints in non-interactive mode)
        skillkit_info = _get_skillkit_info(agent)
        console_display_session_info(skillkit_info, show_commands=False)

    isFirstExecution = True
    enterPostmortemAfterInteractive = False

    # DEBUG: Import StatusBar for logging
    from dolphin.cli.ui.console import StatusBar
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
                        await _runFirstExecution(agent, args, initialVariables)
                        isFirstExecution = False
                        StatusBar._debug_log(f"runConversationLoop: first execution done")
                    else:
                        await _runSubsequentExecution(agent, args, currentQuery)
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
        # Cleanup
        interrupt_token.unbind()
        if args.interactive:
            layout.end_session()

    return enterPostmortemAfterInteractive


async def _promptUserInput(
    args: Args,
    interrupt_token: Optional[InterruptToken] = None
) -> tuple:
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
        from dolphin.cli.ui.console import StatusBar
        import sys

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


async def _handleLiveDebugCommand(agent, debugCommand: str) -> None:
    """Handle live debug command during conversation
    
    Args:
        agent: Agent instance
        debugCommand: Debug command string (e.g., "trace", "vars", "snapshot json")
    """
    debugCtrl = getattr(agent.executor, 'debug_controller', None)
    
    if debugCtrl is None:
        # No debug controller yet, create a temporary one for inspection
        from dolphin.core.executor.debug_controller import DebugController
        context = agent.get_context()
        if context is None:
            console("⚠️ Agent 尚未初始化，无法进入调试模式")
            return
        debugCtrl = DebugController(context)
    
    await debugCtrl.enter_live_debug(debugCommand)


async def _runFirstExecution(agent, args: Args, initialVariables: Dict[str, Any]) -> None:
    """Run first execution of agent"""
    from dolphin.cli.ui.console import StatusBar
    StatusBar._debug_log(f"_runFirstExecution: starting")
    
    debugKwargs = {"debug_mode": flags.is_enabled(flags.DEBUG_MODE)}
    if flags.is_enabled(flags.DEBUG_MODE):
        if args.breakOnStart:
            debugKwargs["break_on_start"] = True
        if args.breakAt:
            debugKwargs["break_at"] = args.breakAt
    
    try:
        async for result in agent.arun(**debugKwargs, **initialVariables):
            pass
        StatusBar._debug_log(f"_runFirstExecution: arun completed")
    except Exception as e:
        StatusBar._debug_log(f"_runFirstExecution: exception during arun: {e}")
        raise
    
    if args.outputVariables and not args.interactive:
        outputVariablesToJson(agent.get_context(), args.outputVariables)
    
    StatusBar._debug_log(f"_runFirstExecution: done")


async def _runSubsequentExecution(agent, args, query) -> None:
    """Run subsequent execution (chat mode or resume)
    
    Args:
        query: User input - can be str for text or List[Dict] for multimodal content
    """
    from dolphin.core.agent.agent_state import AgentState, PauseType

    # Check if the agent is paused due to user interrupt
    # We use getattr/direct access for performance in CLI
    is_user_interrupted = (
        agent.state == AgentState.PAUSED and 
        getattr(agent, '_pause_type', None) == PauseType.USER_INTERRUPT
    )

    if is_user_interrupted:
        # For UserInterrupt, we treat it as a multi-turn conversation continuation
        # rather than a block restart. This allows LLM to see the partial output
        # it was generating and continue from there with the new user input.
        # 
        # Key insight: UserInterrupt is semantically "user wants to provide new input",
        # which is the same as achat's purpose - continue the conversation.
        
        # Clear interrupt state before continuing
        if hasattr(agent, 'clear_interrupt'):
            agent.clear_interrupt()
        
        # Reset pause state for the agent so it can accept new work
        agent._pause_type = None
        if hasattr(agent, '_resume_handle'):
            agent._resume_handle = None
        
        # Reset agent state to RUNNING so interrupt() can work during execution
        agent._state = AgentState.RUNNING
        
        # Use achat with preserve_context=True to keep the scratchpad content
        # This ensures LLM can see its partial output from before the interrupt
        async for result in agent.achat(message=query, preserve_context=True):
            pass
    else:
        # Also set state to RUNNING for normal achat path
        agent._state = AgentState.RUNNING
        async for result in agent.achat(message=query):
            pass
    
    if args.outputVariables:
        outputVariablesToJson(agent.get_context(), args.outputVariables)


async def saveExecutionArtifacts(agent, args: Args) -> None:
    """Save execution trace and snapshots
    
    Args:
        agent: Agent instance
        args: Parsed CLI arguments
    """
    if not args.saveHistory:
        return
    
    # Save trajectory if not already saved via trajectoryPath
    if not args.trajectoryPath:
        agent.save_trajectory(agent_name=args.agent, force_save=True)
    
    try:
        currentTime = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        randomSuffix = f"{random.randint(10000, 99999)}"
        
        # Save execution trace
        await _saveExecutionTrace(agent, args, currentTime, randomSuffix)
        
        # Save snapshot analysis in debug mode
        if flags.is_enabled(flags.DEBUG_MODE):
            await _saveSnapshotAnalysis(agent, args, currentTime, randomSuffix)
    
    except Exception as e:
        console(f"Warning: Failed to save execution trace: {e}")
        if args.saveHistory:
            traceback.print_exc()


async def _saveExecutionTrace(agent, args: Args, currentTime: str, randomSuffix: str) -> None:
    """Save execution trace to file"""
    traceContent = agent.get_execution_trace()
    
    if args.tracePath:
        tracePath = args.tracePath
        traceDir = os.path.dirname(tracePath)
        if traceDir:
            os.makedirs(traceDir, exist_ok=True)
    else:
        traceDir = "data/execution_trace"
        os.makedirs(traceDir, exist_ok=True)
        traceFilename = f"execution_trace_{currentTime}_{randomSuffix}.txt"
        tracePath = os.path.join(traceDir, traceFilename)
    
    with open(tracePath, "w", encoding="utf-8") as f:
        f.write(traceContent)
    
    console(f"Execution trace saved to: {tracePath}", verbose=args.saveHistory)


async def _saveSnapshotAnalysis(agent, args: Args, currentTime: str, randomSuffix: str) -> None:
    """Save snapshot analysis in debug mode"""
    try:
        snapshotDir = "data/snapshot_analysis"
        os.makedirs(snapshotDir, exist_ok=True)
        
        # Save Markdown format
        snapshotAnalysis = agent.get_snapshot_analysis(
            title=f"Debug Snapshot Analysis - {args.agent}"
        )
        snapshotFilename = f"snapshot_analysis_{currentTime}_{randomSuffix}.md"
        snapshotPath = os.path.join(snapshotDir, snapshotFilename)
        
        with open(snapshotPath, "w", encoding="utf-8") as f:
            f.write(snapshotAnalysis)
        
        console(f"Snapshot analysis saved to: {snapshotPath}", verbose=args.saveHistory)
        
        # Save JSON format
        snapshotJson = agent.get_snapshot_analysis(format='json')
        snapshotJsonFilename = f"snapshot_analysis_{currentTime}_{randomSuffix}.json"
        snapshotJsonPath = os.path.join(snapshotDir, snapshotJsonFilename)
        
        with open(snapshotJsonPath, "w", encoding="utf-8") as f:
            json.dump(snapshotJson, f, ensure_ascii=False, indent=2)
        
        console(f"Snapshot analysis JSON saved to: {snapshotJsonPath}", verbose=args.saveHistory)
    
    except Exception as e:
        console(f"Warning: Failed to save snapshot analysis: {e}")
        if args.saveHistory:
            traceback.print_exc()


async def enterPostmortemIfNeeded(agent, args: Args, enterPostmortem: bool) -> None:
    """Enter post-mortem debug mode if conditions are met
    
    Args:
        agent: Agent instance
        args: Parsed CLI arguments
        enterPostmortem: Whether to enter post-mortem
    """
    try:
        shouldEnter = (
            flags.is_enabled(flags.DEBUG_MODE)
            and not getattr(args, 'autoContinue', False)
            and (not args.interactive or enterPostmortem)
        )
        
        if shouldEnter:
            debugCtrl = getattr(agent.executor, 'debug_controller', None)
            if debugCtrl is not None:
                console("\n✅ 程序执行完毕，已进入 Post-Mortem 调试模式。输入 'help' 查看命令，'quit' 退出。")
                await debugCtrl.post_mortem_loop()
            else:
                console("⚠️ 未找到调试控制器，无法进入 Post-Mortem 模式。")
    except Exception as e:
        console(f"Warning: Post-Mortem 调试模式发生错误: {e}")
        if args.saveHistory:
            traceback.print_exc()


async def runDolphinAgent(args: Args) -> None:
    """Run Dolphin Language agent
    
    This is the main orchestrator function that coordinates:
    1. Environment initialization
    2. Agent loading and preparation
    3. Conversation loop execution
    4. Artifact saving
    5. Post-mortem debugging (if applicable)
    
    Args:
        args: Parsed CLI arguments
    """
    from dolphin.cli.utils.helpers import validateArgs
    
    validateArgs(args)
    
    richConsole = RichConsole()
    initialVariables = buildVariables(args)
    
    userId = args.userId if args.userId else str(uuid.uuid4())
    sessionId = args.sessionId if args.sessionId else str(uuid.uuid4())
    
    env = None
    try:
        with richConsole.status("[bold green]Initializing Dolphin Environment...") as status:
            status.update("[bold blue]Loading configuration...[/]")
            env, _ = await initializeEnvironment(args)
            
            status.update(f"[bold blue]Loading agents from:[/][white] {args.folder}[/]")
            if args.skillFolder:
                status.update(
                    f"[bold blue]Loading agents from:[/][white] {args.folder}[/] "
                    f"[dim](& skills from {args.skillFolder})[/]"
                )
            
            status.update(f"[bold blue]Initializing agent:[/][white] {args.agent}[/]")
            agent = await loadAndPrepareAgent(env, args, initialVariables)
            
            agent.set_user_id(userId)
            agent.set_session_id(sessionId)
            
            status.update("[bold green]Ready![/]")
        
        # Run conversation
        enterPostmortem = await runConversationLoop(agent, args, initialVariables)
        
        # Save artifacts
        await saveExecutionArtifacts(agent, args)
        
        # Post-mortem
        await enterPostmortemIfNeeded(agent, args, enterPostmortem)
        
        await env.ashutdown()
    
    except Exception as e:
        _handle_execution_error(e, args)
        if env is not None and hasattr(env, "ashutdown"):
            await env.ashutdown()
        sys.exit(1)


def _handle_execution_error(e: Exception, args: Args) -> None:
    """Handle execution errors with user-friendly output.
    
    For known DolphinException types, display a clean error message.
    For unknown exceptions, display the full traceback.
    
    Args:
        e: The exception that occurred
        args: Parsed CLI arguments
    """
    from dolphin.core.common.exceptions import DolphinException, SkillException
    
    # Determine verbosity level
    show_full_traceback = flags.is_enabled(flags.DEBUG_MODE) or getattr(args, 'vv', False)
    
    # Check if this is a known exception type with a friendly message
    root_cause = _extract_root_cause(e)
    
    if isinstance(root_cause, SkillException):
        # SkillException has a detailed, user-friendly message
        console(f"\n❌ Skill Error:\n{root_cause.message}")
        if show_full_traceback:
            console("\n--- Full Traceback (debug mode) ---")
            traceback.print_exc()
    elif isinstance(root_cause, DolphinException):
        # Check if the message contains embedded SkillException info
        skill_error_msg = _extract_skill_error_message(e)
        if skill_error_msg:
            # Display the extracted skill error message in a clean format
            console(f"\n❌ Skill Error:\n{skill_error_msg}")
        else:
            # Other DolphinException types - show concise error
            console(f"\n❌ Error [{root_cause.code}]: {root_cause.message}")
        if show_full_traceback:
            console("\n--- Full Traceback (debug mode) ---")
            traceback.print_exc()
    else:
        # Unknown exception - show more details
        console(f"\n❌ Error executing Dolphin agent: {e}")
        if show_full_traceback or args.saveHistory:
            traceback.print_exc()
        else:
            console("💡 Run with --vv or --debug for full traceback")


def _extract_root_cause(e: Exception) -> Exception:
    """Extract the root cause from a chain of exceptions.
    
    Traverses the exception chain (__cause__ and __context__) to find
    the original DolphinException that triggered the error.
    
    Args:
        e: The top-level exception
        
    Returns:
        The root cause exception (a DolphinException if found, otherwise the original)
    """
    from dolphin.core.common.exceptions import DolphinException
    
    # First, check if the current exception is already a DolphinException
    if isinstance(e, DolphinException):
        return e
    
    # Traverse __cause__ chain (explicit "raise ... from ...")
    current = e
    while current.__cause__ is not None:
        current = current.__cause__
        if isinstance(current, DolphinException):
            return current
    
    # Traverse __context__ chain (implicit exception chaining)
    current = e
    while current.__context__ is not None:
        current = current.__context__
        if isinstance(current, DolphinException):
            return current
    
    # No DolphinException found, return original
    return e


def _extract_skill_error_message(e: Exception) -> Optional[str]:
    """Try to extract a user-friendly skill error message from exception string.
    
    Some exceptions wrap SkillException as a string (using str(e) instead of 'from e'),
    so we need to parse the string to extract the formatted error message.
    
    Args:
        e: The exception to analyze
        
    Returns:
        The extracted skill error message if found, None otherwise
    """
    error_str = str(e)
    
    # Look for the SkillException pattern in the message
    # Pattern: "Skill 'xxx' not found.\n\nAvailable skills..."
    import re
    
    # Try to find the skill error block
    skill_error_pattern = r"(Skill '[^']+' not found\..*?Verify that the required skillkit module is loaded)"
    match = re.search(skill_error_pattern, error_str, re.DOTALL)
    
    if match:
        return match.group(1)
    
    # Alternative: look for SKILL_NOT_FOUND pattern
    if "SKILL_NOT_FOUND" in error_str and "Available skills" in error_str:
        # Extract from "Skill '" to the end of "Possible fixes" section
        start_idx = error_str.find("Skill '")
        if start_idx != -1:
            # Find the end of the message (after "Possible fixes" section)
            end_patterns = ["module is loaded", "skillkit module is loaded"]
            end_idx = len(error_str)
            for pattern in end_patterns:
                idx = error_str.find(pattern, start_idx)
                if idx != -1:
                    end_idx = min(end_idx, idx + len(pattern))
            if end_idx > start_idx:
                return error_str[start_idx:end_idx]
    
    return None


async def runDolphin(args: Args) -> None:
    """Run Dolphin Language program
    
    Args:
        args: Parsed CLI arguments
    """
    if args.agent:
        # User specified a custom agent
        await runDolphinAgent(args)
    elif args.useBuiltinAgent:
        # Use builtin explore agent (default explore mode)
        await runBuiltinExploreAgent(args)
    else:
        console("Error: Must specify --agent or use explore mode")
        sys.exit(1)


async def runBuiltinExploreAgent(args: Args) -> None:
    """Run the builtin explore agent for interactive coding assistance
    
    This provides a Claude Code / Codex-like experience with access to
    local environment tools (bash, python, file operations).
    
    Args:
        args: Parsed CLI arguments
    """
    from dolphin.cli.builtin_agents import BUILTIN_AGENTS_DIR, DEFAULT_EXPLORE_AGENT
    from dolphin.sdk.runtime.env import Env
    from dolphin.core.config.global_config import GlobalConfig
    from dolphin.lib.skillkits.env_skillkit import EnvSkillkit
    import logging
    
    # Set the builtin agent directory and agent name
    args.folder = BUILTIN_AGENTS_DIR
    args.agent = DEFAULT_EXPLORE_AGENT
    
    # Disable EXPLORE_BLOCK_V2 for explore mode (continue_exploration not yet supported in V2)
    flags.set_flag(flags.EXPLORE_BLOCK_V2, False)
    
    # Initialize environment
    globalConfigPath = args.config if args.config else "./config/global.yaml"
    globalConfig = GlobalConfig.from_yaml(globalConfigPath)
    
    # Create environment with builtin agents directory
    env = Env(
        globalConfig=globalConfig,
        agentFolderPath=BUILTIN_AGENTS_DIR,
        skillkitFolderPath=args.skillFolder,
        output_variables=[],
        verbose=args.saveHistory,
        is_cli=True,
        log_level=(
            logging.DEBUG if flags.is_enabled(flags.DEBUG_MODE) else logging.INFO
        ),
    )
    
    # Register EnvSkillkit for local bash/python execution
    env_skillkit = EnvSkillkit()
    env_skillkit.setGlobalConfig(globalConfig)
    for skill in env_skillkit.getSkills():
        env.globalSkills.installedSkillset.addSkill(skill)
    env.globalSkills._syncAllSkills()
    
    console(f"[bold green]👋 Hi! I'm Dolphin, your AI Pair Programmer.[/]")
    console(f"   I can help you write code, debug issues, and explore this project.")
    console(f"   What would you like to do today?\n")
    
    # Run the agent with the enhanced environment
    await _runDolphinAgentWithEnv(env, args)


async def _runDolphinAgentWithEnv(env, args: Args) -> None:
    """Run Dolphin agent with a pre-configured environment
    
    Args:
        env: Pre-configured Dolphin environment
        args: Parsed CLI arguments
    """
    from dolphin.cli.utils.helpers import validateArgs, buildVariables, outputVariablesToJson
    
    richConsole = RichConsole()
    initialVariables = buildVariables(args)
    
    userId = args.userId if args.userId else str(uuid.uuid4())
    sessionId = args.sessionId if args.sessionId else str(uuid.uuid4())
    
    try:
        with richConsole.status("[bold green]Initializing agent...[/]") as status:
            status.update(f"[bold blue]Loading agent:[/][white] {args.agent}[/]")
            agent = await loadAndPrepareAgent(env, args, initialVariables)
            
            agent.set_user_id(userId)
            agent.set_session_id(sessionId)
            
            status.update("[bold green]Ready![/]")
        
        # Run conversation
        enterPostmortem = await runConversationLoop(agent, args, initialVariables)
        
        # Save artifacts
        await saveExecutionArtifacts(agent, args)
        
        # Post-mortem
        await enterPostmortemIfNeeded(agent, args, enterPostmortem)
        
        await env.ashutdown()
    
    except Exception as e:
        _handle_execution_error(e, args)
        if env is not None and hasattr(env, "ashutdown"):
            await env.ashutdown()
        sys.exit(1)
