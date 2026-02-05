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
from dolphin.cli.runner.modules.environment import initializeEnvironment
from dolphin.cli.runner.modules.errors import handle_execution_error
from dolphin.cli.runner.modules.debugger import (
    _handleLiveDebugCommand,
    enterPostmortemIfNeeded
)
from dolphin.cli.runner.modules.execution import _runFirstExecution, _runSubsequentExecution
from dolphin.cli.runner.modules.agent_lifecycle import (
    loadAndPrepareAgent,
    _recoverAgentFromError,
    _get_skillkit_info,
)
from dolphin.cli.runner.modules.conversation import (
    runConversationLoop,
    _handle_user_interrupt,
    _promptUserInput,
)
from dolphin.cli.runner.modules.artifacts import (
    saveExecutionArtifacts,
    _saveExecutionTrace,
    _saveSnapshotAnalysis,
)
from dolphin.core.utils.rich_status import safe_rich_status


# Note: The following functions have been moved to modules/:
# - conversation.py: _handle_user_interrupt, runConversationLoop, _promptUserInput
# - artifacts.py: saveExecutionArtifacts, _saveExecutionTrace, _saveSnapshotAnalysis
# - execution.py: _runFirstExecution, _runSubsequentExecution
# - agent_lifecycle.py: loadAndPrepareAgent, _recoverAgentFromError, _get_skillkit_info
# - debugger.py: _handleLiveDebugCommand, enterPostmortemIfNeeded
# - errors.py: handle_execution_error
# - environment.py: initializeEnvironment

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
        with safe_rich_status(
            "[bold green]Initializing Dolphin Environment...",
            console=richConsole,
        ) as status:
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
        handle_execution_error(e, args)
        if env is not None and hasattr(env, "ashutdown"):
            await env.ashutdown()
        sys.exit(1)


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
        with safe_rich_status(
            "[bold green]Initializing agent...[/]",
            console=richConsole,
        ) as status:
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
        handle_execution_error(e, args)
        if env is not None and hasattr(env, "ashutdown"):
            await env.ashutdown()
        sys.exit(1)
