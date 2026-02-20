# -*- coding: utf-8 -*-
"""
Environment Skillkit - Unified execution environment for Python and Bash

This skillkit provides _python and _bash tools that execute in the
configured environment (local, VM, Docker, etc.). The execution
environment is determined by configuration, not by the tool name.

This replaces both vm_skillkit and local_skillkit with a unified interface.
"""

from typing import List, Optional

from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.config.global_config import GlobalConfig
from dolphin.lib.vm.env_executor import EnvExecutor, LocalExecutor, create_executor
from dolphin.core.logging.logger import get_logger
from dolphin.core.skill.context_retention import context_retention


logger = get_logger("env_skillkit")


class EnvSkillkit(Skillkit):
    """
    Unified skillkit for executing Python and Bash commands.
    
    The execution environment (local, VM, Docker, etc.) is determined
    by configuration. This provides a consistent API regardless of
    where the code actually runs.
    
    Configuration:
        # For local execution (default)
        env:
          type: local
          working_dir: /path/to/workdir  # optional
        
        # For VM execution
        vm:
          host: localhost
          port: 22
          username: user
          # ...
    
    Usage:
        # Same tools work in any environment
        _python("print('Hello')")
        _bash("ls -la")
    """
    
    def __init__(self, executor: Optional[EnvExecutor] = None):
        """
        Initialize the environment skillkit.
        
        Args:
            executor: Optional executor to use. If not provided,
                     will be created from config when setGlobalConfig is called.
        """
        super().__init__()
        self._executor = executor
        self._global_config: Optional[GlobalConfig] = None
    
    def getName(self) -> str:
        return "env_skillkit"
    
    def setGlobalConfig(self, config: GlobalConfig):
        """
        Set global config and initialize executor if needed.
        
        Args:
            config: Global configuration object
        """
        self._global_config = config
        
        # Create executor from config if not already set
        if self._executor is None:
            try:
                self._executor = create_executor(config)
                logger.info(f"Created executor: {type(self._executor).__name__}")
            except Exception as e:
                logger.warning(f"Failed to create executor from config: {e}")
                # Fallback to local executor
                self._executor = LocalExecutor()
                logger.info("Falling back to LocalExecutor")
    
    def setExecutor(self, executor: EnvExecutor):
        """
        Explicitly set the executor.
        
        Args:
            executor: EnvExecutor instance to use
        """
        self._executor = executor
    
    def _get_executor(self) -> EnvExecutor:
        """Get the executor, creating a local one if needed."""
        if self._executor is None:
            self._executor = LocalExecutor()
        return self._executor
    
    @context_retention(mode="summary", max_length=1200, detail_hint_min_omitted=1200)
    def _bash(self, cmd: str = "", **kwargs) -> str:
        """Execute a Bash command in the configured environment.
        
        The command runs in the environment specified by configuration:
        - Local machine (default)
        - Remote VM (if vm config is present)
        - Docker container (if docker config is present)

        Note: Commands are executed non-interactively (stdin is closed).
        You MUST use '-y', '--force', or similar flags for commands that normally prompt for confirmation.
        
        Timeout Behavior:
            - Default timeout is 60 seconds
            - If a command exceeds the timeout, it returns a command_id
            - Call _bash again with command_id to continue waiting or cancel
        
        Args:
            cmd (str): The Bash command to execute. Leave empty if using command_id.
            timeout (int): Command timeout in seconds. Default is 60 seconds.
                          If exceeded, returns a command_id for continuation.
                          Maximum allowed is 3600 (1 hour).
            command_id (str): ID of a previous timed-out command to continue waiting for.
            cancel (bool): If True and command_id is provided, cancel the command.
            background (bool): If True, run as a detached background process.
                               Use for long-running servers that should not block.
        
        Returns:
            str: The command output (stdout and stderr), or:
                - Startup status for background commands
                - Timeout message with command_id for long-running commands
        
        Examples:
            # Quick commands complete normally
            _bash("ls -la")
            
            # For potentially slow commands, increase timeout upfront
            _bash("npm install", timeout=300)
            
            # If a command times out, you get a command_id like "abc12345"
            # Then continue waiting or cancel:
            _bash(command_id="abc12345", timeout=60)  # wait 60 more seconds
            _bash(command_id="abc12345", cancel=True)  # cancel the command
            
            # For servers/daemons, use background mode
            _bash("./server.sh", background=True)
        """
        executor = self._get_executor()
        
        # Handle command continuation/cancellation
        command_id = kwargs.get("command_id")
        cancel = kwargs.get("cancel", False)
        
        if command_id:
            if not hasattr(executor, "wait_command"):
                return "Error: command continuation is only supported in local execution mode"
            
            if cancel:
                return executor.cancel_command(command_id)
            else:
                timeout = kwargs.get("timeout", 60)
                return executor.wait_command(command_id, timeout=timeout)
        
        # Regular command execution
        if not cmd:
            return "Error: cmd is required when not using command_id"
        
        # Pass session ID from context if available
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"),
            props=kwargs.get("props")
        )
        if session_id:
            kwargs["session_id"] = session_id
        
        return executor.exec_bash(cmd, **kwargs)
    
    @context_retention(mode="summary", max_length=2000)
    def _python(self, cmd: str, **kwargs) -> str:
        """Execute Python code in the configured environment.
        
        The code runs in the environment specified by configuration:
        - Local machine (default)
        - Remote VM (if vm config is present)
        - Docker container (if docker config is present)
        
        Supports session state persistence for simple variables (strings,
        numbers, lists, dicts).  However, **imported modules do NOT persist
        across calls** — you must include all necessary `import` statements
        in every invocation.  Common stdlib modules (json, urllib, os, re,
        math, datetime) and data-science libraries (np, pd) are pre-loaded
        and always available without importing.

        Args:
            cmd (str): The Python code to execute.
                      Assign results to 'return_value' for explicit returns.
            **kwargs: Additional parameters:
                - cwd: Working directory for execution
                - session_id: Session identifier for state persistence

        Returns:
            str: Execution result including stdout and return_value if set

        Examples:
            # Simple calculation
            _python("x = 1 + 2; print(x)")

            # Using return_value
            _python("return_value = [1, 2, 3]")

            # Stateful execution (variables persist)
            _python("data = load_data()")
            _python("result = process(data)")  # 'data' is available

            # Pre-loaded modules (no import needed)
            _python("data = json.loads(text)")
            _python("resp = urllib.request.urlopen(url)")
        """
        executor = self._get_executor()
        
        # Pass session ID from context if available
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"),
            props=kwargs.get("props")
        )
        if session_id:
            kwargs["session_id"] = session_id
        
        return executor.exec_python(cmd, **kwargs)
    
    def _get_env_info(self, **kwargs) -> str:
        """Get information about the current execution environment.
        
        Args:
            **kwargs: Optional runtime parameters injected by the skill execution
                flow (for example ``props``). They are accepted for compatibility.

        Returns:
            str: JSON string containing environment details:
                - type: 'local' or 'vm'
                - working_dir: Current working directory (if local)
                - connected: Connection status
        """
        import json
        executor = self._get_executor()
        
        info = {
            "type": executor.env_type,
            "connected": executor.is_connected()
        }
        
        if executor.env_type == "local" and hasattr(executor, "working_dir"):
            info["working_dir"] = getattr(executor, "working_dir")
            
        return json.dumps(info, indent=2)

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self._bash, block_as_parameter=("bash", "cmd")),
            SkillFunction(self._python, block_as_parameter=("python", "cmd")),
            SkillFunction(self._get_env_info),
        ]
