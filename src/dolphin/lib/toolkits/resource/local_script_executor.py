"""Local skill script executor for testing mode.

This module is only used in local testing mode. It executes skill scripts
directly in the current runtime environment without any installer, marketplace,
or registry logic.

For online mode, script execution is handled by factory_skill_runtime on the
agent-executor side; this module is not involved.

Responsibilities (intentionally thin):
- Accept a command that has already been validated by SkillValidator.validate_entry_shell
- Resolve and confirm the script file path inside skill_dir/scripts/
- subprocess.run and return a unified structured result

All format and security validation (forbidden flags, path structure, injection
patterns) lives exclusively in SkillValidator.  This module must NOT re-implement
those checks.
"""

import subprocess
import shlex
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dolphin.core.logging.logger import get_logger
from .tool_validator import (
    validate_entry_shell,
    get_script_path_from_entry_shell,
    resolve_safe_path,
)

logger = get_logger("local_script_executor")

# Default script execution timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 120


class LocalScriptExecutorError(Exception):
    """Raised for local script execution errors."""
    pass


def execute_skill_script(
    skill_dir: Path,
    entry_shell: str,
    extra: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Execute a skill script in the local environment.

    Accepts a pre-validated entry_shell command (validated by
    SkillValidator.validate_entry_shell), resolves the script path inside
    skill_dir, and runs it via subprocess.  Returns a unified structured
    result matching the builtin_skill_execute_script contract.

    Args:
        skill_dir: Absolute path to the skill directory
        entry_shell: Shell command to execute, e.g. 'python scripts/analyze.py'
        extra: Reserved for future use; not forwarded to the subprocess
        timeout_seconds: Execution timeout in seconds

    Returns:
        Dict with stdout, stderr, exit_code, duration_ms, artifacts, source
    """
    # Validate command format — all security checks are owned by SkillValidator
    is_valid, error = validate_entry_shell(entry_shell)
    if not is_valid:
        return _error_result(error)

    # Derive the script path from the validated command
    script_path = get_script_path_from_entry_shell(entry_shell)

    # Resolve to an absolute path, rejecting traversal and symlinks
    full_path, resolve_error = resolve_safe_path(script_path, skill_dir)
    if resolve_error:
        return _error_result(f"Path resolution failed: {resolve_error}")

    if not full_path.is_file():
        return _error_result(f"Script file not found: {script_path}")

    try:
        cmd_tokens = shlex.split(entry_shell)
    except Exception as e:
        return _error_result(f"Failed to parse entry_shell command: {e}")

    logger.info(f"Executing: {entry_shell}")

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
        logger.warning(f"Script timed out ({timeout_seconds}s): {entry_shell}")
        return {
            "stdout": "",
            "stderr": f"Script execution timed out (exceeded {timeout_seconds} seconds)",
            "exit_code": -1,
            "duration_ms": duration_ms,
            "artifacts": [],
            "source": "local",
        }

    except FileNotFoundError as e:
        logger.error(f"Command not found: {e}")
        return _error_result(
            f"Command not found — ensure the required runtime is installed: {e}"
        )

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        return _error_result(f"Script execution failed: {e}")


def _error_result(message: str) -> Dict[str, Any]:
    """Build a standardised error result dict."""
    return {
        "stdout": "",
        "stderr": message,
        "exit_code": -1,
        "duration_ms": 0,
        "artifacts": [],
        "source": "local",
    }
