"""
Execution Control Module

This module contains execution control functions for running Dolphin agents.
Handles both first execution and subsequent executions (chat mode or resume).

Functions:
- _runFirstExecution: Execute agent for the first time with initial variables
- _runSubsequentExecution: Execute agent in chat mode or resume after interrupt
"""

import asyncio
from typing import Any, Dict

from dolphin.core import flags
from dolphin.core.agent.agent_state import AgentState, PauseType
from dolphin.cli.args.parser import Args
from dolphin.cli.utils.helpers import outputVariablesToJson


async def _runFirstExecution(
    agent,
    args: Args,
    initialVariables: Dict[str, Any],
    event_dispatcher
) -> None:
    """Run first execution of agent with event dispatch.

    Args:
        agent: Agent instance
        args: Parsed CLI arguments
        initialVariables: Initial variables
        event_dispatcher: CLIEventDispatcher for Plan UI updates
    """
    from dolphin.cli.ui.components import StatusBar
    StatusBar._debug_log(f"_runFirstExecution: starting")

    debugKwargs = {"debug_mode": flags.is_enabled(flags.DEBUG_MODE)}
    if flags.is_enabled(flags.DEBUG_MODE):
        if args.breakOnStart:
            debugKwargs["break_on_start"] = True
        if args.breakAt:
            debugKwargs["break_at"] = args.breakAt

    try:
        async for result in agent.arun(**debugKwargs, **initialVariables):
            # Consume and dispatch events from context
            context = agent.get_context()
            if context:
                events = context.drain_output_events()
                if events:
                    event_dispatcher.dispatch_batch(events)

        StatusBar._debug_log(f"_runFirstExecution: arun completed")
    except Exception as e:
        StatusBar._debug_log(f"_runFirstExecution: exception during arun: {e}")
        raise

    if args.outputVariables and not args.interactive:
        outputVariablesToJson(agent.get_context(), args.outputVariables)

    StatusBar._debug_log(f"_runFirstExecution: done")


async def _runSubsequentExecution(agent, args, query, event_dispatcher) -> None:
    """Run subsequent execution (chat mode or resume) with event dispatch.

    Args:
        agent: Agent instance
        args: Parsed CLI arguments
        query: User input - can be str for text or List[Dict] for multimodal content
        event_dispatcher: CLIEventDispatcher for Plan UI updates
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
            # Consume and dispatch events from context
            context = agent.get_context()
            if context:
                events = context.drain_output_events()
                if events:
                    event_dispatcher.dispatch_batch(events)
    else:
        # Also set state to RUNNING for normal achat path
        agent._state = AgentState.RUNNING
        async for result in agent.achat(message=query):
            # Consume and dispatch events from context
            context = agent.get_context()
            if context:
                events = context.drain_output_events()
                if events:
                    event_dispatcher.dispatch_batch(events)

    if args.outputVariables:
        outputVariablesToJson(agent.get_context(), args.outputVariables)
