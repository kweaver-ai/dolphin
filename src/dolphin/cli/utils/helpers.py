"""
Utility functions for Dolphin CLI

This module contains helper functions used by the CLI.
"""

import json
import sys
from typing import Any, Dict, List

from dolphin.core.common.constants import (
    DOLPHIN_VARIABLES_OUTPUT_START,
    DOLPHIN_VARIABLES_OUTPUT_END,
)
from dolphin.core.logging.logger import console

from dolphin.cli.args.parser import Args


def readFile(filePath: str) -> str:
    """Read content from file
    
    Args:
        filePath: Path to the file
        
    Returns:
        File content as string
    """
    try:
        with open(filePath, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        console(f"Error: File not found: {filePath}")
        sys.exit(1)
    except Exception as e:
        console(f"Error reading file {filePath}: {e}")
        sys.exit(1)


def buildVariables(args: Args) -> Dict[str, Any]:
    """Build variables dictionary from arguments
    
    Args:
        args: Parsed CLI arguments
        
    Returns:
        Dictionary of variables to pass to the agent
    """
    variables = {}
    
    if args.query is not None:
        variables["query"] = args.query
    
    if args.userId is not None:
        variables["user_id"] = args.userId
    
    if args.runArgs:
        variables.update(args.runArgs)
    
    return variables


def outputVariablesToJson(context, variableNames: List[str]) -> None:
    """Output specified variables in JSON format
    
    Args:
        context: Dolphin context object
        variableNames: List of variable names to output (empty = all)
    """
    if not variableNames:
        allVariables = context.get_all_variables_values()
    else:
        allVariables = {}
        for varName in variableNames:
            try:
                varValue = context.get_var_path_value(varName)
                if varValue is not None:
                    allVariables[varName] = varValue
            except Exception:
                allVariables[varName] = None
    
    if "_all_stages" not in allVariables:
        allVariables["_all_stages"] = context.get_runtime_graph().get_all_stages()
    
    variablesJson = json.dumps(
        allVariables, ensure_ascii=False, default=str, indent=2
    )
    console(f"\n{DOLPHIN_VARIABLES_OUTPUT_START}")
    console(variablesJson)
    console(f"{DOLPHIN_VARIABLES_OUTPUT_END}\n")


def validateArgs(args: Args) -> None:
    """Validate CLI arguments before execution
    
    Args:
        args: Parsed CLI arguments
        
    Raises:
        SystemExit: If validation fails
    """
    import os
    
    if args.folder and not os.path.exists(args.folder):
        console(f"Error: Folder not found: {args.folder}")
        sys.exit(1)
    
    if args.skillFolder and not os.path.exists(args.skillFolder):
        console(f"Error: Skill folder not found: {args.skillFolder}")
        sys.exit(1)


def setupFlagsFromArgs(args: Args) -> None:
    """Set feature flags from CLI arguments
    
    Args:
        args: Parsed CLI arguments
    """
    from dolphin.core import flags
    
    if not args.flagsOverrides:
        return
    
    for flagName, flagValue in args.flagsOverrides.items():
        # Convert string "true"/"false" to boolean, handle boolean directly
        if isinstance(flagValue, str):
            boolValue = flagValue.lower() in ('true', '1', 'yes', 'on', 'True')
        else:
            boolValue = bool(flagValue)
        
        flags.set_flag(flagName, boolValue)
        # Cleaner flag output
        state = "Enabled" if boolValue else "Disabled"
        console(f"[Flag] {flagName}: {state}")

