"""
Agent Lifecycle Management Module

This module contains functions for managing the lifecycle of Dolphin agents,
including loading, preparation, error recovery, and metadata extraction.

Functions:
- loadAndPrepareAgent: Load and prepare agent for execution
- _recoverAgentFromError: Recover agent from ERROR state
- _get_skillkit_info: Extract skillkit information from agent
"""

import sys
from typing import Any, Dict, Optional

from dolphin.core.logging.logger import console
from dolphin.cli.args.parser import Args


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
