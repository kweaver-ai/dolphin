"""
Error handling utilities for Dolphin CLI runner.

This module provides functions for handling execution errors with user-friendly output,
extracting root causes from exception chains, and parsing tool error messages.

Functions:
    - handle_execution_error: Main error handler with user-friendly output
    - extract_root_cause: Extract root cause from exception chains
    - extract_tool_error_message: Parse tool error messages from exception strings
"""

import re
import traceback
from typing import Optional

from dolphin.core import flags
from dolphin.core.common.exceptions import DolphinException, ToolException
from dolphin.core.logging.logger import console
from dolphin.cli.args.parser import Args


def handle_execution_error(e: Exception, args: Args) -> None:
    """Handle execution errors with user-friendly output.

    For known DolphinException types, display a clean error message.
    For unknown exceptions, display the full traceback.

    Args:
        e: The exception that occurred
        args: Parsed CLI arguments
    """
    # Determine verbosity level
    show_full_traceback = flags.is_enabled(flags.DEBUG_MODE) or getattr(args, 'vv', False)

    # Check if this is a known exception type with a friendly message
    root_cause = extract_root_cause(e)

    if isinstance(root_cause, ToolException):
        # ToolException has a detailed, user-friendly message
        console(f"\n❌ Tool Error:\n{root_cause.message}")
        if show_full_traceback:
            console("\n--- Full Traceback (debug mode) ---")
            traceback.print_exc()
    elif isinstance(root_cause, DolphinException):
        # Check if the message contains embedded ToolException info
        tool_error_msg = extract_tool_error_message(e)
        if tool_error_msg:
            # Display the extracted tool error message in a clean format
            console(f"\n❌ Tool Error:\n{tool_error_msg}")
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


def extract_root_cause(e: Exception) -> Exception:
    """Extract the root cause from a chain of exceptions.

    Traverses the exception chain (__cause__ and __context__) to find
    the original DolphinException that triggered the error.

    Args:
        e: The top-level exception

    Returns:
        The root cause exception (a DolphinException if found, otherwise the original)
    """
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


def extract_tool_error_message(e: Exception) -> Optional[str]:
    """Try to extract a user-friendly tool error message from exception string.

    Some exceptions wrap ToolException as a string (using str(e) instead of 'from e'),
    so we need to parse the string to extract the formatted error message.

    Args:
        e: The exception to analyze

    Returns:
        The extracted skill error message if found, None otherwise
    """
    error_str = str(e)

    # Look for the ToolException pattern in the message
    # Pattern: "Tool 'xxx' not found.\n\nAvailable tools..."

    # Try to find the tool error block
    tool_error_pattern = r"(Tool '[^']+' not found\..*?Verify that the required toolkit module is loaded)"
    match = re.search(tool_error_pattern, error_str, re.DOTALL)

    if match:
        return match.group(1)

    # Alternative: look for TOOL_NOT_FOUND pattern
    if "TOOL_NOT_FOUND" in error_str and "Available tools" in error_str:
        # Extract from "Tool '" to the end of "Possible fixes" section
        start_idx = error_str.find("Tool '")
        if start_idx != -1:
            # Find the end of the message (after "Possible fixes" section)
            end_patterns = ["module is loaded", "toolkit module is loaded"]
            end_idx = len(error_str)
            for pattern in end_patterns:
                idx = error_str.find(pattern, start_idx)
                if idx != -1:
                    end_idx = min(end_idx, idx + len(pattern))
            if end_idx > start_idx:
                return error_str[start_idx:end_idx]

    return None
