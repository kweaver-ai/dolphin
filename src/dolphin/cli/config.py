"""
CLI Configuration Module

This module centralizes configuration constants for the CLI layer,
including UI behavior, silent tools, and event handling settings.
"""

from typing import FrozenSet

# ========================================================================
# Silent Tools Configuration
# ========================================================================
#
# Tools in this set will NOT display tool call cards in the terminal.
# These are typically system coordination tools that have dedicated UI
# components (like LivePlanCard for Plan tools, StatusBar for timing).
#
# Design rationale:
# - _check_progress: Polling tool with LivePlanCard showing real-time status
# - _wait: Wait tool with StatusBar showing elapsed time
# - _plan_tasks: Plan creation with dedicated plan_created event + LivePlanCard
#
# Note: This does NOT prevent the tools from being called or logged,
# it only controls whether a visual "tool card" is displayed in the terminal.
# ========================================================================

SILENT_TOOLS: FrozenSet[str] = frozenset({
    "_check_progress",  # Plan: Progress polling - LivePlanCard shows real-time updates
    "_wait",            # Plan: Wait for tasks - StatusBar shows elapsed time
    "_plan_tasks",      # Plan: Task creation - plan_created event + LivePlanCard display
})


# ========================================================================
# Event Dispatcher Configuration
# ========================================================================

# Maximum number of events to batch before forcing a UI update
# Higher values improve performance but may delay UI updates
EVENT_BATCH_SIZE = 10

# Minimum interval (seconds) between UI updates when batching
# Prevents UI flicker from too-frequent updates
EVENT_BATCH_INTERVAL = 0.1


# ========================================================================
# LivePlanCard Configuration
# ========================================================================

# Maximum number of tasks to display in LivePlanCard
# Tasks beyond this limit will be truncated with "... N more tasks"
MAX_PLAN_CARD_TASKS = 20

# Spinner animation frame rate (frames per second)
PLAN_CARD_FPS = 10

# Whether to show task content preview in LivePlanCard
PLAN_CARD_SHOW_CONTENT = True


# ========================================================================
# Output Limits (for preventing terminal spam)
# ========================================================================

# Maximum characters per task output (plan_task_output events)
MAX_TASK_OUTPUT_CHARS = 5000

# Maximum characters per explore iteration output
MAX_EXPLORE_ITERATION_CHARS = 3000

# Maximum characters per thinking chunk (cumulative)
MAX_THINKING_CHARS = 10000

# Maximum characters per answer chunk (cumulative)
MAX_ANSWER_CHARS = 10000
