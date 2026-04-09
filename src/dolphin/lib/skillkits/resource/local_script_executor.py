"""Local skill script executor for testing mode.

This module is only used in local testing mode. It executes skill scripts
directly in the current runtime environment without any installer, marketplace,
or registry logic.

For online mode, script execution is handled by factory_skill_runtime on the
agent-executor side; this module is not involved.

Execution strategy:
- Executes entry_shell command directly (e.g., 'python scripts/analyze.py')
- Validates that the script path in the command is inside the skill's scripts/ subdirectory
- Returns a unified structured result matching the builtin_skill_execute_script contract
- Matches the online factory execution behavior
"""

import subprocess
import shlex
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dolphin.core.logging.logger import get_logger
from .skill_validator import resolve_safe_path

logger = get_logger("local_script_executor")

# Default script execution timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 120


class LocalScriptExecutorError(Exception):
    """Raised for local script execution errors."""
    pass


def _extract_script_path_from_command(entry_shell: str) -> Optional[str]:
    """Extract the script path from a shell command.
    
    Args:
        entry_shell: Shell command like 'python scripts/analyze.py' or 'bash scripts/run.sh'
        
    Returns:
        The script path if found, None otherwise
    """
    try:
        tokens = shlex.split(entry_shell)
        # Look for a token that starts with 'scripts/'
        for token in tokens:
            normalized = token.replace("\\", "/")
            if normalized.startswith("scripts/"):
                return normalized
        return None
    except Exception:
        return None


def _validate_entry_shell(entry_shell: str) -> Tuple[bool, Optional[str]]:
    """Validate the format of an entry_shell command.

    Args:
        entry_shell: Shell command to validate

    Returns:
        (is_valid, error_message) — error_message is None when valid
    """
    if not entry_shell or not entry_shell.strip():
        return False, "entry_shell must not be empty"

    # Extract script path from command
    script_path = _extract_script_path_from_command(entry_shell)
    if not script_path:
        return False, (
            f"entry_shell must contain a script path starting with 'scripts/': {entry_shell}"
        )

    # Validate the script path portion
    normalized = script_path.replace("\\", "/")

    # Reject absolute paths
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return False, f"Absolute paths are not allowed: {script_path}"

    # Reject path traversal
    for part in normalized.split("/"):
        if part in ("..", ""):
            return False, f"Path contains illegal segment: {script_path}"

    # Must be under scripts/
    if not normalized.startswith("scripts/"):
        return False, f"Script path must start with 'scripts/': {script_path}"

    return True, None


def execute_skill_script(
    skill_dir: Path,
    entry_shell: str,
    extra: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Execute a skill script in the local environment using shell command.

    For local testing mode only. Performs path safety validation before
    execution to ensure the script is inside the skill's scripts/ subdirectory.
    Matches the online factory execution behavior.

    Args:
        skill_dir: Absolute path to the skill directory
        entry_shell: Shell command to execute (e.g., 'python scripts/analyze.py')
        extra: Additional parameters for the script (reserved for future use;
               currently not forwarded to the subprocess)
        timeout_seconds: Execution timeout in seconds

    Returns:
        Dict with the following fields:
        - stdout: Standard output
        - stderr: Standard error output
        - exit_code: Exit code (0 = success, -1 = internal error)
        - duration_ms: Execution time in milliseconds
        - artifacts: List of produced artifacts (empty at this stage)
        - source: "local"
    """
    # Step 1: Validate command format
    is_valid, error = _validate_entry_shell(entry_shell)
    if not is_valid:
        return _error_result(error)

    # Step 2: Extract script path from command
    script_path = _extract_script_path_from_command(entry_shell)
    if not script_path:
        return _error_result(f"Could not extract script path from entry_shell: {entry_shell}")

    # Step 3: Resolve safe path (prevents traversal and symlink attacks)
    normalized_path = script_path.replace("\\", "/")
    full_path, resolve_error = resolve_safe_path(normalized_path, skill_dir)
    if resolve_error:
        return _error_result(f"Path resolution failed: {resolve_error}")
    if full_path is None:
        return _error_result(f"Invalid path: {script_path}")

    # Step 4: Confirm script file exists
    if not full_path.is_file():
        return _error_result(f"Script file not found: {script_path}")

    # Step 5: Confirm the script is under scripts/
    try:
        rel = full_path.relative_to(skill_dir.resolve())
        if not rel.parts or rel.parts[0] != "scripts":
            return _error_result(f"Script must reside under the scripts/ directory: {script_path}")
    except ValueError:
        return _error_result(f"Script path is outside the skill directory: {script_path}")

    # Step 6: Parse the shell command
    try:
        cmd_tokens = shlex.split(entry_shell)
    except Exception as e:
        return _error_result(f"Failed to parse entry_shell command: {e}")

    logger.info(f"[local_script_executor] Executing: {entry_shell}")

    # Step 7: Run script
    start_time = time.monotonic()
    try:
        result = subprocess.run(
            cmd_tokens,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(skill_dir),
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
            "artifacts": [],
            "source": "local",
        }

    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            f"[local_script_executor] Script timed out ({timeout_seconds}s): {entry_shell}"
        )
        return {
            "stdout": "",
            "stderr": f"Script execution timed out (exceeded {timeout_seconds} seconds)",
            "exit_code": -1,
            "duration_ms": duration_ms,
            "artifacts": [],
            "source": "local",
        }

    except FileNotFoundError as e:
        logger.error(f"[local_script_executor] Command not found: {e}")
        return _error_result(
            f"Command not found — ensure the required runtime is installed: {e}"
        )

    except Exception as e:
        logger.error(f"[local_script_executor] Execution failed: {e}")
        return _error_result(f"Script execution failed: {e}")


def _error_result(message: str) -> Dict[str, Any]:
    """Build a standardized error result dict."""
    return {
        "stdout": "",
        "stderr": message,
        "exit_code": -1,
        "duration_ms": 0,
        "artifacts": [],
        "source": "local",
    }
