# -*- coding: utf-8 -*-
"""
Environment Executor Module

This module defines the abstract interface for environment executors
and provides concrete implementations for different execution environments.

Executors are responsible for executing Python and Bash commands in
specific environments (local, VM, Docker, etc.)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
import os
import subprocess
import tempfile
import random
import string
import shlex
import threading
import uuid
import time
from dataclasses import dataclass
from enum import Enum

from dolphin.core.logging.logger import get_logger

logger = get_logger("env_executor")


class CommandStatus(Enum):
    """Status of an async command."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class AsyncCommand:
    """Represents an async command execution."""
    command_id: str
    command: str
    cwd: str
    process: subprocess.Popen
    start_time: float
    output_buffer: str = ""
    error_buffer: str = ""
    status: CommandStatus = CommandStatus.RUNNING
    return_code: Optional[int] = None


class AsyncCommandManager:
    """Manager for async command execution and monitoring.
    
    This allows commands to be started and monitored incrementally,
    giving LLMs the ability to decide whether to continue waiting.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._commands: Dict[str, AsyncCommand] = {}
                    cls._instance._output_lock = threading.Lock()
        return cls._instance
    
    def start_command(
        self, 
        command: str, 
        cwd: str, 
        env: Optional[Dict[str, str]] = None
    ) -> str:
        """Start a command asynchronously.
        
        Args:
            command: Command to execute
            cwd: Working directory
            env: Environment variables
            
        Returns:
            Command ID for tracking
        """
        command_id = str(uuid.uuid4())[:8]
        
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
                text=True,
                bufsize=1,  # Line buffered
            )
            
            async_cmd = AsyncCommand(
                command_id=command_id,
                command=command,
                cwd=cwd,
                process=process,
                start_time=time.time(),
            )
            
            self._commands[command_id] = async_cmd
            logger.debug(f"[{command_id}] Command started: {command[:80]}...")
            
            # Start output collection threads
            # unique thread for stdout
            threading.Thread(
                target=self._collect_stream,
                args=(command_id, 'stdout'),
                daemon=True
            ).start()
            logger.debug(f"[{command_id}] stdout collector thread started")
            
            # unique thread for stderr
            threading.Thread(
                target=self._collect_stream,
                args=(command_id, 'stderr'),
                daemon=True
            ).start()
            logger.debug(f"[{command_id}] stderr collector thread started")
            
            return command_id
            
        except Exception as e:
            logger.error(f"Failed to start async command: {e}")
            raise
    
    def _collect_stream(self, command_id: str, stream_name: str):
        """Collect output from a specific stream."""
        cmd = self._commands.get(command_id)
        if not cmd:
            logger.debug(f"[{command_id}] {stream_name} collector: command not found")
            return
            
        try:
            stream = cmd.process.stdout if stream_name == 'stdout' else cmd.process.stderr
            if not stream:
                logger.debug(f"[{command_id}] {stream_name} collector: stream is None")
                return

            logger.debug(f"[{command_id}] {stream_name} collector: starting to read")
            line_count = 0
            # Read stream line by line
            for line in iter(stream.readline, ''):
                if not line:
                    break
                line_count += 1
                with self._output_lock:
                    if stream_name == 'stdout':
                        cmd.output_buffer += line
                    else:
                        cmd.error_buffer += line
            
            logger.debug(f"[{command_id}] {stream_name} collector: finished, read {line_count} lines")
            # Stream ended, try to update status non-blockingly
            self._update_status(cmd)
            
        except Exception as e:
            logger.error(f"Error collecting {stream_name} for {command_id}: {e}")

    def _update_status(self, cmd: AsyncCommand):
        """Update command status non-blockingly."""
        if cmd.status in (CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED):
            return

        return_code = cmd.process.poll()
        if return_code is not None:
            cmd.return_code = return_code
            cmd.status = CommandStatus.COMPLETED if return_code == 0 else CommandStatus.FAILED
            logger.debug(f"[{cmd.command_id}] Status updated: {cmd.status.value}, return_code={return_code}")

    def wait_command(
        self, 
        command_id: str, 
        timeout: float = 60
    ) -> Tuple[CommandStatus, str, Optional[int]]:
        """Wait for a command to complete or timeout.
        
        Args:
            command_id: Command ID to wait for
            timeout: Maximum seconds to wait
            
        Returns:
            Tuple of (status, output, return_code)
        """
        cmd = self._commands.get(command_id)
        if not cmd:
            return CommandStatus.FAILED, f"Command {command_id} not found", None
        
        # Check status first
        self._update_status(cmd)
        if cmd.status in (CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED):
            with self._output_lock:
                output = cmd.output_buffer
                if cmd.error_buffer:
                    if cmd.return_code != 0:
                        output += f"\nSTDERR:\n{cmd.error_buffer}"
                    else:
                        output += f"\n{cmd.error_buffer}"
            return cmd.status, output, cmd.return_code

        try:
            logger.debug(f"[{command_id}] Waiting with timeout={timeout}s...")
            # Wait with timeout - this is safe now as no other thread holds the lock
            cmd.process.wait(timeout=timeout)
            
            logger.debug(f"[{command_id}] Wait completed, process exited")
            # Command completed
            self._update_status(cmd)
            with self._output_lock:
                output = cmd.output_buffer
                if cmd.error_buffer:
                    if cmd.return_code != 0:
                        output += f"\nSTDERR:\n{cmd.error_buffer}"
                    else:
                        output += f"\n{cmd.error_buffer}"
            
            logger.debug(f"[{command_id}] Returning status={cmd.status.value}, output_len={len(output)}")
            return cmd.status, output, cmd.return_code
            
        except subprocess.TimeoutExpired:
            # Still running
            logger.debug(f"[{command_id}] Timeout expired after {timeout}s, command still running")
            cmd.status = CommandStatus.TIMEOUT
            
            with self._output_lock:
                partial_output = cmd.output_buffer
            
            logger.debug(f"[{command_id}] Returning TIMEOUT with partial_output_len={len(partial_output)}")
            return CommandStatus.TIMEOUT, partial_output, None
    
    def cancel_command(self, command_id: str) -> bool:
        """Cancel a running command.
        
        Args:
            command_id: Command ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        cmd = self._commands.get(command_id)
        if not cmd:
            return False
        
        self._update_status(cmd)
        if cmd.status in (CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED):
            return True
        
        try:
            cmd.process.terminate()
            try:
                cmd.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cmd.process.kill()
                cmd.process.wait(timeout=1)
        except Exception:
            pass
        
        cmd.status = CommandStatus.CANCELLED
        return True
    
    def get_command_info(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a command.
        
        Args:
            command_id: Command ID
            
        Returns:
            Command info dict or None
        """
        cmd = self._commands.get(command_id)
        if not cmd:
            return None
        
        self._update_status(cmd)
        
        elapsed = time.time() - cmd.start_time
        with self._output_lock:
            output_size = len(cmd.output_buffer)
        
        return {
            "command_id": cmd.command_id,
            "command": cmd.command[:100] + "..." if len(cmd.command) > 100 else cmd.command,
            "status": cmd.status.value,
            "elapsed_seconds": round(elapsed, 1),
            "output_size": output_size,
            "return_code": cmd.return_code,
        }
    
    def cleanup_old_commands(self, max_age_seconds: float = 3600):
        """Remove old completed/failed commands."""
        now = time.time()
        to_remove = []
        
        for cmd_id, cmd in self._commands.items():
            if cmd.status in (CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED):
                if now - cmd.start_time > max_age_seconds:
                    to_remove.append(cmd_id)
        
        for cmd_id in to_remove:
            del self._commands[cmd_id]


class EnvExecutor(ABC):
    """
    Abstract base class for environment executors.
    
    An executor is responsible for executing commands (Python, Bash)
    in a specific environment. Different implementations handle
    different execution contexts (local machine, remote VM, Docker, etc.)
    """
    
    @abstractmethod
    def exec_python(self, code: str, varDict: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        """Execute Python code in the environment.
        
        Args:
            code: Python code to execute
            varDict: Optional dictionary of variables to inject
            **kwargs: Additional execution parameters
            
        Returns:
            Execution result as string
        """
        pass
    
    @abstractmethod
    def exec_bash(self, command: str, **kwargs) -> str:
        """Execute a Bash command in the environment.
        
        Args:
            command: Bash command to execute
            **kwargs: Additional execution parameters
            
        Returns:
            Execution result as string
        """
        pass

    @property
    @abstractmethod
    def env_type(self) -> str:
        """Get the environment type identifier.
        
        Returns:
            str: Environment type (e.g., 'local', 'vm')
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the executor is connected/ready.
        
        Returns:
            True if ready to execute, False otherwise
        """
        pass
    
    def _preprocess_code(self, code: str, lang: str) -> str:
        """Remove markdown code block wrappers if present.
        
        Args:
            code: Code that may be wrapped in markdown
            lang: Language identifier (python, bash)
            
        Returns:
            Clean code without markdown wrappers
        """
        start_flag = f"```{lang}"
        end_flag = "```"
        
        idx_start = code.find(start_flag)
        if idx_start == -1:
            return code
        
        idx_end = code.find(end_flag, idx_start + len(start_flag))
        if idx_end == -1:
            return code[idx_start + len(start_flag):]
        
        return code[idx_start + len(start_flag):idx_end]


class LocalExecutor(EnvExecutor):
    """
    Executor for running commands on the local machine.
    
    This executor runs commands directly on the machine where
    dolphin is running. Useful for:
    - Local development servers
    - Node.js/npm operations
    - Browser automation
    - Local file operations
    """
    
    def __init__(self, working_dir: Optional[str] = None, timeout: int = 60):
        """
        Initialize the local executor.
        
        Args:
            working_dir: Default working directory for commands
            timeout: Default command timeout in seconds (default 60 seconds)
                    Commands that exceed this timeout will return with a command_id
                    that can be used to continue waiting via wait_command().
        """
        self.working_dir = working_dir or os.getcwd()
        self.default_timeout = timeout
        self._session_namespace: Dict[str, Any] = {}
        self._async_manager = AsyncCommandManager()
    
    @property
    def env_type(self) -> str:
        return "local"

    def is_connected(self) -> bool:
        """Local executor is always connected."""
        return True
    
    def exec_bash(self, command: str, cwd: Optional[str] = None, **kwargs) -> str:
        """Execute a Bash command locally.
        
        Args:
            command: Bash command to execute
            cwd: Working directory (overrides default)
            timeout: Command timeout in seconds (default 60).
                    If command exceeds timeout, returns with a command_id for continuation.
            background: If True, run command in background (for long-running servers).
                       Also auto-detects trailing '&' in command.
            
        Returns:
            Command output (stdout and stderr), or:
            - Startup message for background commands
            - Timeout message with command_id for long-running commands
        """
        work_dir = cwd or self.working_dir
        command = self._preprocess_code(command, "bash")
        background = kwargs.get("background", False)
        timeout = kwargs.get("timeout", self.default_timeout)
        
        # Validate timeout
        if timeout is not None:
            timeout = max(1, min(timeout, 3600))  # Clamp between 1s and 1 hour
        
        # Auto-detect trailing & as background execution request
        if not background and command.rstrip().endswith('&'):
            background = True
            logger.info("Detected trailing '&' in command, switching to background execution")
        
        logger.debug(f"Executing local bash in {work_dir}: {command[:100]}... (timeout={timeout}s)")
        
        # Handle background execution for long-running processes
        if background:
            return self._exec_bash_background(command, work_dir)
        
        # Use async execution for better timeout handling
        try:
            command_id = self._async_manager.start_command(
                command, 
                work_dir, 
                self._get_enhanced_env()
            )
            
            status, output, return_code = self._async_manager.wait_command(
                command_id, 
                timeout=timeout
            )
            
            if status == CommandStatus.TIMEOUT:
                # Command still running - provide command_id for continuation
                elapsed = timeout
                partial_info = f"\nPartial output:\n{output[:2000]}" if output else ""
                
                return (
                    f"⏳ Command still running after {elapsed} seconds.\n"
                    f"Command ID: {command_id}\n"
                    f"{partial_info}\n\n"
                    f"To continue waiting, call _bash with: command_id=\"{command_id}\"\n"
                    f"To cancel, call _bash with: command_id=\"{command_id}\", cancel=True"
                )
            
            elif status in (CommandStatus.COMPLETED, CommandStatus.FAILED):
                if return_code != 0:
                    output = f"Command exited with code {return_code}\n{output}"
                return output.strip() if output else "(no output)"
            
            else:
                return f"Command ended with status: {status.value}\n{output}"
                
        except Exception as e:
            logger.error(f"Error executing local bash: {e}")
            return f"Error executing command: {str(e)}"
    
    def wait_command(self, command_id: str, timeout: int = 60) -> str:
        """Continue waiting for a previously started command.
        
        Use this when a command times out and you want to wait longer.
        
        Args:
            command_id: The command ID from a previous timeout message
            timeout: Additional seconds to wait (default 60)
            
        Returns:
            Command output if completed, or timeout message if still running
        """
        timeout = max(1, min(timeout, 3600))
        
        cmd_info = self._async_manager.get_command_info(command_id)
        if not cmd_info:
            return f"Error: Command {command_id} not found. It may have already completed or been cleaned up."
        
        if cmd_info["status"] in ("completed", "failed", "cancelled"):
            # Command already finished, get the result
            status, output, return_code = self._async_manager.wait_command(command_id, timeout=0)
            if return_code is not None and return_code != 0:
                output = f"Command exited with code {return_code}\n{output}"
            return output.strip() if output else "(no output)"
        
        # Continue waiting
        status, output, return_code = self._async_manager.wait_command(command_id, timeout=timeout)
        
        if status == CommandStatus.TIMEOUT:
            elapsed = cmd_info["elapsed_seconds"] + timeout
            partial_info = f"\nPartial output:\n{output[:2000]}" if output else ""
            
            return (
                f"⏳ Command still running after {elapsed:.0f} seconds total.\n"
                f"Command ID: {command_id}\n"
                f"{partial_info}\n\n"
                f"To continue waiting, call _bash with: command_id=\"{command_id}\"\n"
                f"To cancel, call _bash with: command_id=\"{command_id}\", cancel=True"
            )
        
        elif status in (CommandStatus.COMPLETED, CommandStatus.FAILED):
            if return_code is not None and return_code != 0:
                output = f"Command exited with code {return_code}\n{output}"
            return output.strip() if output else "(no output)"
        
        else:
            return f"Command ended with status: {status.value}\n{output}"
    
    def cancel_command(self, command_id: str) -> str:
        """Cancel a running command.
        
        Args:
            command_id: The command ID to cancel
            
        Returns:
            Cancellation status message
        """
        cmd_info = self._async_manager.get_command_info(command_id)
        if not cmd_info:
            return f"Error: Command {command_id} not found."
        
        if cmd_info["status"] != "running" and cmd_info["status"] != "timeout":
            return f"Command {command_id} is already {cmd_info['status']}."
        
        success = self._async_manager.cancel_command(command_id)
        if success:
            return f"Command {command_id} has been cancelled."
        else:
            return f"Failed to cancel command {command_id}."
    
    def _exec_bash_background(self, command: str, work_dir: str) -> str:
        """Execute a command in the background, detached from the parent process.
        
        Used for long-running processes like development servers.
        
        Args:
            command: Bash command to execute
            work_dir: Working directory
            
        Returns:
            Status message with PID
        """
        import time
        
        try:
            # Strip trailing & if present (we add our own)
            command = command.rstrip().rstrip('&').rstrip()
            
            # Use nohup and redirect all output to detach properly
            # Create a log file for the background process output
            log_file = os.path.join(work_dir, ".background_process.log")
            
            # Wrap in bash -c to handle complex commands (like cd && ./script)
            safe_command = shlex.quote(command)
            bg_command = f"nohup bash -c {safe_command} > {log_file} 2>&1 & echo $!"
            
            result = subprocess.run(
                bg_command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120,  # Longer timeout for commands that do setup (npm install etc.)
                env=self._get_enhanced_env()
            )
            
            pid = result.stdout.strip()
            
            # Give the process a moment to start
            time.sleep(2)
            
            # Check if process is still running
            try:
                check_result = subprocess.run(
                    f"ps -p {pid} > /dev/null 2>&1 && echo 'running' || echo 'stopped'",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                status = check_result.stdout.strip()
                
                if status == "running":
                    # Try to read initial log output
                    try:
                        with open(log_file, 'r') as f:
                            initial_output = f.read()[:500]  # First 500 chars
                        if initial_output:
                            return f"Background process started (PID: {pid})\nInitial output:\n{initial_output}"
                    except Exception:
                        pass
                    return f"Background process started successfully (PID: {pid})\nLog file: {log_file}"
                else:
                    # Process failed, read log for error
                    try:
                        with open(log_file, 'r') as f:
                            error_log = f.read()
                        return f"Background process failed to start (PID: {pid})\nError log:\n{error_log}"
                    except Exception:
                        return f"Background process failed to start (PID: {pid})"
                        
            except Exception as e:
                return f"Background process started (PID: {pid}), but status check failed: {e}"
                
        except subprocess.TimeoutExpired:
            return "Error: Failed to start background process (timeout getting PID)"
        except Exception as e:
            logger.error(f"Error starting background process: {e}")
            return f"Error starting background process: {str(e)}"
    
    def exec_python(self, code: str, varDict: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        """Execute Python code locally.
        
        Args:
            code: Python code to execute
            varDict: Variables to inject into namespace
            
        Returns:
            Execution result
        """
        code = self._preprocess_code(code, "python")
        cwd = kwargs.get("cwd", self.working_dir)
        
        logger.debug(f"Executing local Python in {cwd}")
        
        try:
            old_cwd = os.getcwd()
            os.chdir(cwd)
            
            try:
                # Create execution namespace
                namespace = {
                    '__builtins__': __builtins__,
                    '__name__': '__main__',
                }

                # Preload common data-science aliases if available.
                # This reduces "NameError: name 'np' is not defined" noise in typical analysis workflows.
                try:
                    import numpy as np  # type: ignore
                    namespace.setdefault("np", np)
                except ImportError:
                    pass
                try:
                    import pandas as pd  # type: ignore
                    namespace.setdefault("pd", pd)
                except ImportError:
                    pass
                
                # Restore previous session state
                namespace.update(self._session_namespace)
                
                # Inject provided variables
                if varDict:
                    namespace.update(varDict)
                
                # Capture stdout
                import io
                import sys
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = captured_stdout = io.StringIO()
                sys.stderr = captured_stderr = io.StringIO()
                
                try:
                    # Execute the code
                    exec(code, namespace)
                    
                    # Get output
                    stdout_val = captured_stdout.getvalue()
                    stderr_val = captured_stderr.getvalue()
                    
                    output = stdout_val
                    if stderr_val:
                        output += f"\n{stderr_val}"
                    
                    # Check for return_value
                    if 'return_value' in namespace:
                        output += f"\nReturn value: {namespace['return_value']}"
                    
                    # Save session state (filter non-pickleable)
                    for key, value in list(namespace.items()):
                        if not key.startswith('_'):
                            try:
                                import pickle
                                pickle.dumps(value)
                                self._session_namespace[key] = value
                            except Exception:
                                pass
                    
                    return output.strip() if output else "(no output)"
                    
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
                    
            finally:
                os.chdir(old_cwd)
                
        except Exception as e:
            import traceback
            logger.error(f"Error executing local Python: {e}")
            return f"Error: {str(e)}\n{traceback.format_exc()}"
    
    def _get_enhanced_env(self) -> dict:
        """Get environment with NVM/Node.js paths added."""
        env = os.environ.copy()
        
        # Add NVM paths if available
        nvm_dir = os.path.expanduser("~/.nvm")
        if os.path.exists(nvm_dir):
            versions_dir = os.path.join(nvm_dir, "versions", "node")
            if os.path.exists(versions_dir):
                try:
                    versions = sorted(os.listdir(versions_dir), reverse=True)
                    if versions:
                        node_bin = os.path.join(versions_dir, versions[0], "bin")
                        if os.path.exists(node_bin):
                            env["PATH"] = f"{node_bin}:{env.get('PATH', '')}"
                except OSError:
                    pass
        
        return env


class VMExecutor(EnvExecutor):
    """
    Executor for running commands on a remote VM via SSH.
    
    This executor connects to a remote virtual machine and
    executes commands there. Useful for:
    - Isolated execution environments
    - Remote server operations
    - Sandboxed code execution
    """
    
    def __init__(self, vm):
        """
        Initialize the VM executor.
        
        Args:
            vm: VM instance (VMSSH or similar)
        """
        self.vm = vm
        self._session_manager = None
    
    def set_session_manager(self, session_manager):
        """Set the Python session manager for state persistence."""
        self._session_manager = session_manager
    
    @property
    def env_type(self) -> str:
        return "vm"

    def is_connected(self) -> bool:
        """Check if VM is connected."""
        if self.vm is None:
            return False
        return getattr(self.vm, 'connected', False)
    
    def exec_bash(self, command: str, **kwargs) -> str:
        """Execute a Bash command on the remote VM.
        
        Args:
            command: Bash command to execute
            
        Returns:
            Command output
        """
        if self.vm is None:
            raise RuntimeError("VM is not configured")
        return self.vm.execBash(command)
    
    def exec_python(self, code: str, varDict: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        """Execute Python code on the remote VM.
        
        Args:
            code: Python code to execute
            varDict: Variables to inject
            
        Returns:
            Execution result
        """
        if self.vm is None:
            raise RuntimeError("VM is not configured")
        
        # Handle session management
        session_id = kwargs.get("session_id")
        if session_id and self._session_manager:
            kwargs["session_id"] = session_id
            kwargs["session_manager"] = self._session_manager
        
        return self.vm.execPython(code, varDict, **kwargs)


def create_executor(config) -> EnvExecutor:
    """
    Factory function to create the appropriate executor based on config.
    
    Args:
        config: GlobalConfig or similar configuration object
        
    Returns:
        EnvExecutor instance
        
    Note:
        - Default is LocalExecutor (local execution)
        - Use env.type: 'vm' to explicitly use VMExecutor
        - Having vm: config alone does NOT switch to VMExecutor
    """
    # Check for explicit env config
    env_config = getattr(config, 'env_config', None)
    
    if env_config is not None:
        env_type = getattr(env_config, 'type', 'local')
    else:
        # Default to local execution
        # Note: Just having vm_config does NOT automatically use VM
        # User must explicitly set env.type: 'vm' to use VMExecutor
        env_type = 'local'
    
    if env_type == 'local':
        working_dir = getattr(env_config, 'working_dir', None) if env_config else None
        return LocalExecutor(working_dir=working_dir)
    
    elif env_type == 'vm':
        from dolphin.lib.vm.vm import VMFactory
        vm_config = getattr(config, 'vm_config', None)
        if vm_config is None:
            raise ValueError("VM configuration is required for 'vm' environment type")
        
        vm = VMFactory.createVM(vm_config)
        executor = VMExecutor(vm)
        
        # Set up session manager
        from dolphin.lib.vm.python_session_manager import PythonSessionManager
        executor.set_session_manager(PythonSessionManager())
        
        return executor
    
    else:
        raise ValueError(f"Unknown environment type: {env_type}")
