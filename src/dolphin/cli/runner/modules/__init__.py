"""
Runner Modules for Dolphin CLI

This package contains modular components for the Dolphin agent runner,
refactored from the monolithic runner.py for better maintainability.
"""

# Environment initialization
from dolphin.cli.runner.modules.environment import (
    initializeEnvironment,
    _print_flags_status,
    _should_print_flags_status,
)

# Agent lifecycle management
from dolphin.cli.runner.modules.agent_lifecycle import (
    loadAndPrepareAgent,
    _recoverAgentFromError,
    _get_skillkit_info,
)

# Execution control
from dolphin.cli.runner.modules.execution import (
    _runFirstExecution,
    _runSubsequentExecution,
)

# Artifact management
from dolphin.cli.runner.modules.artifacts import (
    saveExecutionArtifacts,
    _saveExecutionTrace,
    _saveSnapshotAnalysis,
)

# Debugger integration
from dolphin.cli.runner.modules.debugger import (
    enterPostmortemIfNeeded,
    _handleLiveDebugCommand,
)

# Conversation loop
from dolphin.cli.runner.modules.conversation import (
    runConversationLoop,
    _handle_user_interrupt,
    _promptUserInput,
)

# Error handling
from dolphin.cli.runner.modules.errors import (
    handle_execution_error,
    extract_root_cause,
    extract_skill_error_message,
)

__all__ = [
    # Environment
    'initializeEnvironment',
    '_print_flags_status',
    '_should_print_flags_status',
    # Agent lifecycle
    'loadAndPrepareAgent',
    '_recoverAgentFromError',
    '_get_skillkit_info',
    # Conversation
    'runConversationLoop',
    '_handle_user_interrupt',
    '_promptUserInput',
    # Execution
    '_runFirstExecution',
    '_runSubsequentExecution',
    # Artifacts
    'saveExecutionArtifacts',
    '_saveExecutionTrace',
    '_saveSnapshotAnalysis',
    # Debugger
    'enterPostmortemIfNeeded',
    '_handleLiveDebugCommand',
    # Errors
    'handle_execution_error',
    'extract_root_cause',
    'extract_skill_error_message',
]
