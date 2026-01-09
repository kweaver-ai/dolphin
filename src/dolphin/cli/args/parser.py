"""
Command-line argument parsing for Dolphin CLI

This module handles all CLI argument parsing with subcommand support.
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dolphin.cli.utils.version import getFullVersion
from dolphin.core.logging.logger import console


@dataclass
class Args:
    """Command-line arguments dataclass"""
    
    # Subcommand
    subcommand: Optional[str] = None  # run/debug/chat/explore
    
    # Agent related
    agent: Optional[str] = None
    folder: Optional[str] = None
    skillFolder: Optional[str] = None
    query: Optional[str] = None
    
    # Builtin agent mode
    useBuiltinAgent: bool = False  # True if using builtin explore agent
    
    # Config related
    config: Optional[str] = None
    modelName: Optional[str] = None
    apiKey: Optional[str] = None
    api: Optional[str] = None
    typeApi: Optional[str] = None
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    maxTokens: Optional[int] = None
    temperature: Optional[float] = None
    
    # Logging related
    logLevel: Optional[str] = None
    logSuffix: Optional[str] = None
    
    # Mode related
    interactive: bool = False
    saveHistory: bool = True
    
    # Output related
    trajectoryPath: Optional[str] = None
    tracePath: Optional[str] = None
    outputVariables: List[str] = field(default_factory=list)
    reportPath: Optional[str] = None
    
    # Context Engineer
    contextEngineerConfig: Optional[str] = None
    contextEngineerData: Optional[str] = None
    
    # Run subcommand options
    timeout: Optional[int] = None
    dryRun: bool = False
    
    # Debug subcommand options
    breakOnStart: bool = False
    breakAt: Optional[List[int]] = None
    snapshotOnPause: bool = False
    commands: Optional[str] = None
    autoContinue: bool = False  # Renamed from nonInteractive - debug mode: auto-run until breakpoint
    
    # Chat subcommand options
    systemPrompt: Optional[str] = None
    maxTurns: Optional[int] = None
    initMessage: Optional[str] = None
    
    # Custom arguments and flags
    runArgs: Dict[str, Any] = field(default_factory=dict)
    flagsOverrides: Dict[str, bool] = field(default_factory=dict)


def _addAgentArguments(parser: argparse.ArgumentParser, required: bool = True) -> None:
    """Add agent-related arguments
    
    Args:
        parser: The argument parser
        required: Whether --agent and --folder are required (False for explore subcommand)
    """
    parser.add_argument(
        "--agent", "-a", type=str, required=required,
        help="Agent name to execute"
    )
    parser.add_argument(
        "--folder", type=str, required=required,
        help="Directory containing agent definitions"
    )
    parser.add_argument(
        "--skill-folder", "--skill_folder", type=str, dest="skill_folder",
        help="Custom skillkit directory"
    )
    parser.add_argument(
        "--query", "-q", type=str,
        help="Query string passed to the agent as 'query' variable"
    )


def _addConfigArguments(parser: argparse.ArgumentParser) -> None:
    """Add configuration arguments"""
    parser.add_argument(
        "--config", "-c", type=str,
        help="Config file path (default: ./config/global.yaml)"
    )
    parser.add_argument("--model-name", "--model_name", type=str, dest="model_name", help="Model name")
    parser.add_argument("--api-key", "--api_key", type=str, dest="api_key", help="API Key")
    parser.add_argument("--api", type=str, help="API endpoint URL")
    parser.add_argument("--type-api", "--type_api", type=str, dest="type_api", help="API type")
    parser.add_argument("--user-id", "--user_id", type=str, dest="user_id", help="User ID")
    parser.add_argument("--session-id", "--session_id", type=str, dest="session_id", help="Session ID")
    parser.add_argument("--max-tokens", "--max_tokens", type=int, dest="max_tokens", help="Maximum tokens")
    parser.add_argument("--temperature", type=float, help="Temperature (0.0-2.0)")


def _addLoggingArguments(parser: argparse.ArgumentParser) -> None:
    """Add logging arguments"""
    verbosityGroup = parser.add_mutually_exclusive_group()
    verbosityGroup.add_argument(
        "-v", "--verbose", action="store_const", const="INFO", dest="verbosity",
        help="Verbose output (INFO level)"
    )
    verbosityGroup.add_argument(
        "-vv", "--very-verbose", action="store_const", const="DEBUG", dest="verbosity",
        help="Very verbose output (DEBUG level)"
    )
    verbosityGroup.add_argument(
        "--quiet", action="store_const", const="WARNING", dest="verbosity",
        help="Quiet mode (WARNING and above only)"
    )
    
    parser.add_argument(
        "--log-level", type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set log level directly (overrides -v/-vv)"
    )
    parser.add_argument(
        "--log-suffix", type=str,
        help="Log file name suffix for concurrent experiments"
    )


def _addOutputArguments(parser: argparse.ArgumentParser) -> None:
    """Add output-related arguments"""
    parser.add_argument(
        "--output-variables", nargs="*", default=[],
        help="List of variable names to output"
    )
    parser.add_argument(
        "--trajectory-path", "--trajectorypath", type=str, dest="trajectorypath",
        help="Dialog history save path (default: data/dialog/)"
    )
    parser.add_argument(
        "--trace-path", "--tracepath", type=str, dest="tracepath",
        help="Execution trace save path (default: data/execution_trace/)"
    )
    parser.add_argument(
        "--report-path", "--reportpath", type=str, dest="reportpath",
        help="Report output path"
    )
    parser.add_argument(
        "--context-engineer-config", "--context_engineer_config", 
        type=str, dest="context_engineer_config",
        help="Context-engineer config file path"
    )
    parser.add_argument(
        "--context-engineer-data", "--context_engineer_data",
        type=str, dest="context_engineer_data",
        help="Context-engineer data file path"
    )


def _addHistoryArguments(parser: argparse.ArgumentParser) -> None:
    """Add history saving arguments"""
    parser.add_argument(
        '--save-history', action='store_true', default=True, dest='save_history',
        help='Save dialog history to file (enabled by default)'
    )
    parser.add_argument(
        '--no-save-history', action='store_false', dest='save_history',
        help='Do not save dialog history'
    )


def _addCommonArguments(parser: argparse.ArgumentParser, agent_required: bool = True) -> None:
    """Add all common arguments shared by subcommands
    
    Args:
        parser: The argument parser
        agent_required: Whether --agent and --folder are required
    """
    _addAgentArguments(parser, required=agent_required)
    _addConfigArguments(parser)
    _addLoggingArguments(parser)
    _addOutputArguments(parser)


def _addRunSubcommandArguments(parser: argparse.ArgumentParser) -> None:
    """Add run subcommand specific arguments"""
    _addHistoryArguments(parser)
    parser.add_argument(
        '--timeout', type=int, metavar='SECONDS',
        help='Execution timeout in seconds'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Validate config and agent definition without execution'
    )
    parser.add_argument(
        '--interactive', '-i', action='store_true',
        help='Interactive mode: enter conversation loop after execution'
    )


def _addDebugSubcommandArguments(parser: argparse.ArgumentParser) -> None:
    """Add debug subcommand specific arguments"""
    parser.add_argument(
        '--break-on-start', action='store_true',
        help='Pause at the first code block'
    )
    parser.add_argument(
        '--break-at', type=int, metavar='N', action='append',
        help='Set breakpoint at block N (can be used multiple times)'
    )
    parser.add_argument(
        '--snapshot-on-pause', action='store_true',
        help='Auto-display ContextSnapshot summary on each pause'
    )
    parser.add_argument(
        '--commands', type=str, metavar='FILE',
        help='Read debug commands from file (one per line)'
    )
    parser.add_argument(
        '--auto-continue', action='store_true',
        help='Auto-continue mode: only pause at breakpoints, auto-execute otherwise'
    )
    parser.add_argument(
        '--interactive', '-i', action='store_true',
        help='Interactive mode: enter conversation loop after execution'
    )
    parser.set_defaults(save_history=True)


def _addChatSubcommandArguments(parser: argparse.ArgumentParser) -> None:
    """Add chat subcommand specific arguments"""
    parser.add_argument(
        '--system-prompt', type=str,
        help='Custom system prompt (overrides default)'
    )
    parser.add_argument(
        '--max-turns', type=int,
        help='Maximum conversation turns (auto-exit when reached)'
    )
    parser.add_argument(
        '--init-message', type=str,
        help='Initial message (auto-sent as first message)'
    )
    parser.set_defaults(interactive=True, save_history=True)


def _addExploreSubcommandArguments(parser: argparse.ArgumentParser) -> None:
    """Add explore subcommand specific arguments
    
    The explore subcommand provides a default AI coding assistant experience
    similar to Claude Code and OpenAI Codex, with access to local environment tools.
    """
    parser.add_argument(
        '--system-prompt', type=str,
        help='Custom system prompt (overrides default explore system prompt)'
    )
    parser.add_argument(
        '--max-turns', type=int,
        help='Maximum conversation turns (auto-exit when reached)'
    )
    # Note: interactive is always True for explore mode
    parser.set_defaults(interactive=True, save_history=True, use_builtin_agent=True)


def _addFlagArguments(parser: argparse.ArgumentParser) -> List[str]:
    """Add dynamic flag arguments
    
    Supports two styles:
    1. Switch style: --flag_name (True) or --no-flag_name (False)
    2. Value style: --flag_name true/false (for experiment scripts)
    
    Returns:
        List of flag names
    """
    from dolphin.core.flags import definitions as flagDefs
    
    flagShortOptions = {"debug": "-d"}
    flagNames = []
    
    for attrName in dir(flagDefs):
        if attrName.isupper() and not attrName.startswith('_'):
            flagValue = getattr(flagDefs, attrName)
            if isinstance(flagValue, str):
                flagNames.append(flagValue)
                defaultValue = flagDefs.DEFAULT_VALUES.get(flagValue, False)
                
                enableArgs = [f"--{flagValue}"]
                if flagValue in flagShortOptions:
                    enableArgs.append(flagShortOptions[flagValue])
                
                helpText = f"Set {flagValue} flag (optional: true/false)"
                
                # Support both switch style (--flag) and value style (--flag true/false)
                parser.add_argument(
                    *enableArgs, dest=flagValue, nargs='?', const=True,
                    help=helpText,
                )
                parser.add_argument(
                    f"--no-{flagValue}", dest=flagValue, action="store_const", const=False,
                    help=f"Disable {flagValue} flag",
                )
                parser.set_defaults(**{flagValue: defaultValue})
    
    return flagNames


def _parseUnknownArgs(unknownArgs: List[str]) -> Dict[str, Any]:
    """Parse unknown arguments as custom key-value pairs"""
    runArgs = {}
    i = 0
    while i < len(unknownArgs):
        if unknownArgs[i].startswith("--"):
            key = unknownArgs[i][2:]
            if i + 1 < len(unknownArgs) and not unknownArgs[i + 1].startswith("--"):
                value = unknownArgs[i + 1]
                i += 2
            else:
                value = True
                i += 1
            runArgs[key] = value
        else:
            i += 1
    return runArgs


def _resolveLogLevel(argsDict: Dict[str, Any], subcommand: str, flagsOverrides: Dict[str, bool]) -> str:
    """Resolve final log level from various sources
    
    Priority: --log-level > -v/-vv > subcommand default > INFO
    """
    if argsDict.get("log_level"):
        return argsDict["log_level"]
    
    if argsDict.get("verbosity"):
        return argsDict["verbosity"]
    
    if subcommand == 'debug':
        return "DEBUG"
    elif subcommand == 'chat':
        return "INFO"
    elif flagsOverrides.get('debug'):
        return "DEBUG"
    
    return "INFO"


def _convertToArgs(argsDict: Dict[str, Any]) -> Args:
    """Convert parsed args dict to Args dataclass with field name mapping"""
    # Map CLI argument names to Args field names
    fieldMapping = {
        'skill_folder': 'skillFolder',
        'model_name': 'modelName',
        'api_key': 'apiKey',
        'type_api': 'typeApi',
        'user_id': 'userId',
        'session_id': 'sessionId',
        'max_tokens': 'maxTokens',
        'log_level': 'logLevel',
        'log_suffix': 'logSuffix',
        'save_history': 'saveHistory',
        'trajectorypath': 'trajectoryPath',
        'tracepath': 'tracePath',
        'reportpath': 'reportPath',
        'output_variables': 'outputVariables',
        'context_engineer_config': 'contextEngineerConfig',
        'context_engineer_data': 'contextEngineerData',
        'dry_run': 'dryRun',
        'break_on_start': 'breakOnStart',
        'break_at': 'breakAt',
        'snapshot_on_pause': 'snapshotOnPause',
        'auto_continue': 'autoContinue',
        'system_prompt': 'systemPrompt',
        'max_turns': 'maxTurns',
        'init_message': 'initMessage',
        'run_args': 'runArgs',
        'flags_overrides': 'flagsOverrides',
        'use_builtin_agent': 'useBuiltinAgent',
    }
    
    convertedDict = {}
    for key, value in argsDict.items():
        newKey = fieldMapping.get(key, key)
        convertedDict[newKey] = value
    
    return Args(**convertedDict)


def parseArgs() -> Args:
    """Parse command line arguments with subcommand support
    
    Returns:
        Parsed Args object
    """
    # Main parser
    parser = argparse.ArgumentParser(
        prog="dolphin",
        description="Dolphin Language - AI Agent Development and Debugging Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Subcommands:
  (default)   Explore mode - Interactive AI coding assistant (like Claude Code)
  explore     Explore mode - Interactive AI coding assistant with local env tools
  run         Run Agent (execute and exit)
  debug       Debug mode (step-by-step execution, breakpoints, variable inspection)
  chat        Interactive chat mode (continuous conversation)

Examples:
  # Default explore mode (similar to Claude Code / Codex)
  dolphin
  dolphin explore
  dolphin explore -q "list all Python files in this directory"

  # Run a specific agent
  dolphin run --agent my_agent --folder ./agents --query "analyze data"

  # Interactive mode (continue conversation after execution)
  dolphin run --agent my_agent --folder ./agents -i

  # Debug mode
  dolphin debug --agent my_agent --folder ./agents --break-on-start

  # Interactive chat
  dolphin chat --agent my_agent --folder ./agents
""",
        # Disable long argument abbreviations to avoid conflicts with custom args
        allow_abbrev=False,
    )
    
    # Version
    parser.add_argument(
        '--version', action='version',
        version=getFullVersion(),
        help='Show version and exit'
    )
    
    # Subcommand setup
    subparsers = parser.add_subparsers(dest='subcommand', help='Subcommand')
    
    # explore subcommand (DEFAULT - similar to Claude Code / Codex)
    parserExplore = subparsers.add_parser(
        'explore', help='Interactive AI coding assistant (default mode, like Claude Code)',
        description='Start an interactive AI coding assistant with access to local environment tools'
    )
    _addCommonArguments(parserExplore, agent_required=False)  # agent/folder are optional
    _addExploreSubcommandArguments(parserExplore)
    flagNamesExplore = _addFlagArguments(parserExplore)
    
    # run subcommand
    parserRun = subparsers.add_parser(
        'run', help='Run Agent (execute and exit)',
        description='Run Agent, exit after execution'
    )
    _addCommonArguments(parserRun)
    _addRunSubcommandArguments(parserRun)
    flagNamesRun = _addFlagArguments(parserRun)
    
    # debug subcommand
    parserDebug = subparsers.add_parser(
        'debug', help='Debug mode (interactive step-by-step execution)',
        description='Start interactive debugger with step-by-step execution, breakpoints, variable inspection'
    )
    _addCommonArguments(parserDebug)
    _addDebugSubcommandArguments(parserDebug)
    flagNamesDebug = _addFlagArguments(parserDebug)
    
    # chat subcommand
    parserChat = subparsers.add_parser(
        'chat', help='Interactive chat mode',
        description='Start continuous conversation mode, multi-turn interaction until exit'
    )
    _addCommonArguments(parserChat)
    _addChatSubcommandArguments(parserChat)
    flagNamesChat = _addFlagArguments(parserChat)
    
    # Get all flag names
    flagNames = list(set(flagNamesExplore + flagNamesRun + flagNamesDebug + flagNamesChat))
    
    # Check if subcommand is provided - default to 'explore' if no subcommand
    validSubcommands = ['explore', 'run', 'debug', 'chat', '--version', '-h', '--help']
    
    if len(sys.argv) < 2:
        # No arguments - default to explore mode
        sys.argv.insert(1, 'explore')
    elif sys.argv[1] not in validSubcommands and not sys.argv[1].startswith('-'):
        # User provided something that isn't a subcommand or flag
        # It might be a query for explore mode
        if not sys.argv[1].startswith('--'):
            # Not a flag, treat as query and insert explore
            sys.argv.insert(1, 'explore')
            sys.argv.insert(2, '-q')  # The original first arg becomes the query
    elif sys.argv[1].startswith('-') and sys.argv[1] not in ['--version', '-h', '--help']:
        # User started with a flag (like -q or --config) - default to explore
        sys.argv.insert(1, 'explore')
    
    # Parse arguments
    knownArgs, unknownArgs = parser.parse_known_args()
    argsDict = vars(knownArgs)
    
    # Handle subcommand
    subcommand = argsDict.get('subcommand') or 'explore'
    argsDict['subcommand'] = subcommand
    
    # Extract flags from argsDict into flagsOverrides
    flagsOverrides = {}
    for flagName in flagNames:
        if flagName in argsDict:
            flagsOverrides[flagName] = argsDict.pop(flagName)
    
    # Apply subcommand-specific defaults
    if subcommand == 'explore':
        # Explore mode defaults
        if argsDict.get('interactive') is None:
            argsDict['interactive'] = True
        if argsDict.get('save_history') is None:
            argsDict['save_history'] = True
        if argsDict.get('use_builtin_agent') is None:
            argsDict['use_builtin_agent'] = True
    elif subcommand == 'debug':
        flagsOverrides['debug'] = True
        if argsDict.get('save_history') is None:
            argsDict['save_history'] = True
    elif subcommand == 'chat':
        if argsDict.get('interactive') is None:
            argsDict['interactive'] = True
        if argsDict.get('save_history') is None:
            argsDict['save_history'] = True
    
    argsDict["flags_overrides"] = flagsOverrides
    
    # Validate arguments - allow missing agent/folder only for explore mode with builtin agent
    if argsDict.get("agent") and not argsDict.get("folder"):
        parser.error("--agent requires --folder")
    
    if not argsDict.get("agent"):
        if subcommand != 'explore':
            parser.error("--agent is required")
        # For explore, we'll use the builtin agent (set in runner)
    
    # Parse custom arguments
    argsDict["run_args"] = _parseUnknownArgs(unknownArgs)
    
    # Resolve log level
    argsDict["log_level"] = _resolveLogLevel(argsDict, subcommand, flagsOverrides)
    argsDict.pop("verbosity", None)
    
    return _convertToArgs(argsDict)

