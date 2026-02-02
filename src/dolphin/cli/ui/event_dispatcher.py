"""
CLI Event Dispatcher - Bridge between Core Events and UI Components

This module provides the event dispatching layer that connects Core's output events
to CLI UI components like LivePlanCard and StatusBar.

Architecture:
    Core Layer (context.write_output)
         ↓
    Event Buffer (context._output_events)
         ↓
    drain_output_events() [called in runner.py]
         ↓
    CLIEventDispatcher.dispatch() [this module]
         ↓
    UI Components (LivePlanCard, StatusBar, etc.)
"""

import logging
import threading
from typing import Any, Dict, List, Optional

from dolphin.cli.ui.components import LivePlanCard
from dolphin.cli.ui.theme import Theme
from dolphin.cli.ui.layout import LayoutManager
from dolphin.cli.config import SILENT_TOOLS

logger = logging.getLogger(__name__)


class CLIEventDispatcher:
    """
    Event dispatcher that routes Core output events to appropriate UI components.

    Responsibilities:
    - Consume events from context.drain_output_events()
    - Maintain Plan state (task list, current task, status)
    - Route events to LivePlanCard for real-time updates
    - Coordinate with LayoutManager for status bar control

    Design Principles:
    - Stateless where possible (Plan state is minimal for UI sync only)
    - Fail-silent: UI rendering errors should never break execution
    - Thread-safe: All UI updates use thread-safe methods
    """

    def __init__(self, layout: LayoutManager, verbose: bool = True):
        """Initialize event dispatcher.

        Args:
            layout: LayoutManager instance for status bar coordination
            verbose: Whether to print UI updates
        """
        self.layout = layout
        self.verbose = verbose

        # Plan state (for UI synchronization only)
        self.plan_card: Optional[LivePlanCard] = None
        self.plan_id: Optional[str] = None
        self.task_list: List[Dict[str, Any]] = []
        self.task_id_to_index: Dict[str, int] = {}  # Map task_id -> 1-based index
        self.execution_mode: str = "parallel"
        
        # Thread safety: lock for task_list access
        self._task_list_lock = threading.Lock()

        # Streaming renderer for non-plan LLM output
        self._stream_renderer = None

        # Event handlers registry
        self._handlers = {
            'plan_created': self._handle_plan_created,
            'plan_task_update': self._handle_plan_task_update,
            'plan_task_output': self._handle_plan_task_output,
            'plan_finished': self._handle_plan_finished,
            'llm_stream': self._handle_llm_stream,
            # Add more handlers as needed
            # 'skill_start': self._handle_skill_start,
            # 'skill_end': self._handle_skill_end,
        }

    def dispatch(self, event: Dict[str, Any]) -> None:
        """Dispatch a single event to appropriate handler.

        Args:
            event: Event dict with keys: event_type, data, timestamp_ms
        """
        if not self.verbose:
            return

        event_type = event.get('event_type')
        if not event_type:
            logger.warning(f"Event missing event_type: {event}")
            return

        handler = self._handlers.get(event_type)
        if handler:
            try:
                handler(event.get('data', {}))
            except Exception as e:
                # Fail-silent: UI rendering errors should not break execution
                logger.debug(f"Error handling event {event_type}: {e}", exc_info=True)

    def dispatch_batch(self, events: List[Dict[str, Any]]) -> None:
        """Dispatch a batch of events (optimized for multiple updates).

        Args:
            events: List of event dicts
        """
        for event in events:
            self.dispatch(event)

    def _handle_plan_created(self, data: Dict[str, Any]) -> None:
        """Handle plan_created event - initialize LivePlanCard.

        Event data schema:
            {
                "plan_id": str,
                "tasks": [{"id": str, "name": str, "prompt": str}, ...],
                "execution_mode": "parallel" | "sequential",
                "max_concurrency": int (optional)
            }
        """
        try:
            self.plan_id = data.get('plan_id')
            tasks = data.get('tasks', [])
            self.execution_mode = data.get('execution_mode', 'parallel')

            # Build task list for UI (with lock protection)
            with self._task_list_lock:
                self.task_list = []
                self.task_id_to_index = {}

                for idx, task in enumerate(tasks):
                    task_id = task.get('id', f"task_{idx+1}")
                    task_name = task.get('name', f"Task {idx+1}")
                    task_prompt = task.get('prompt', '')

                    # Store mapping: task_id -> 1-based index (for LivePlanCard)
                    self.task_id_to_index[task_id] = idx + 1

                    # Build UI task entry
                    self.task_list.append({
                        'id': task_id,
                        'name': task_name,
                        'content': task_name,  # LivePlanCard expects 'content' field
                        'status': 'pending',
                    })

            # Stop existing plan_card if running (for replan scenarios)
            if self.plan_card and self.plan_card.running:
                logger.debug("Stopping existing LivePlanCard for replan")
                self.plan_card.stop()

            # Pause the status bar temporarily to prevent conflicts during layout change
            status_bar_was_active = False
            if self.layout._status_bar and self.layout._status_bar.running:
                self.layout._status_bar.pause()
                status_bar_was_active = True
                logger.debug("Paused status bar for plan panel activation")

            # 1. Update Layout to reserve space for Plan (fixed bottom panel)
            # This will output newlines to push content up and set scroll region
            # Calculate safe panel height with minimum threshold
            term_height = self.layout._terminal_height if hasattr(self.layout, '_terminal_height') else 24

            # Minimum requirements:
            # - MIN_PANEL_HEIGHT: Minimum usable panel height (8 lines)
            # - MIN_CONTENT_HEIGHT: Ensure at least 10 lines for main content area
            MIN_PANEL_HEIGHT = 8
            MIN_CONTENT_HEIGHT = 10
            MIN_TOTAL_HEIGHT = MIN_PANEL_HEIGHT + MIN_CONTENT_HEIGHT + self.layout.BOTTOM_RESERVE

            # Check if terminal is too small
            if term_height < MIN_TOTAL_HEIGHT:
                logger.warning(
                    f"Terminal height ({term_height}) too small for plan panel. "
                    f"Minimum required: {MIN_TOTAL_HEIGHT} lines. "
                    f"Plan UI will be disabled."
                )
                # Still track plan state but don't activate UI
                return

            # Calculate panel height with safety bounds
            # - Cap at 15 lines max
            # - Ensure at least MIN_CONTENT_HEIGHT for main content
            # - Require at least MIN_PANEL_HEIGHT for usability
            max_panel_height = min(15, term_height - MIN_CONTENT_HEIGHT - self.layout.BOTTOM_RESERVE)
            panel_height = min(max_panel_height, len(tasks) + 6)
            panel_height = max(MIN_PANEL_HEIGHT, panel_height)  # Enforce minimum

            logger.debug(f"Plan panel: term_height={term_height}, panel_height={panel_height}")
            self.layout.update_layout_for_plan(active=True, height=panel_height)

            # Resume the status bar if it was active
            if status_bar_was_active and self.layout._status_bar:
                self.layout._status_bar.resume()
                logger.debug("Resumed status bar after plan panel activation")

            # 2. Get the target fixed row for the card
            plan_range = self.layout.get_plan_panel_range()
            fixed_row = plan_range[0] if plan_range else None

            # Note: No need to manually clear the plan panel area because:
            # - update_layout_for_plan() already pushed content up with newlines
            # - The bottom area is now empty
            # - LivePlanCard.start() will immediately render content there

            # Initialize LivePlanCard with the fixed location
            if not self.plan_card:
                self.plan_card = LivePlanCard(fixed_row_start=fixed_row)
            else:
                self.plan_card.fixed_row_start = fixed_row

            # Start animation - this will immediately render the card
            self.plan_card.start(
                tasks=self.task_list,
                current_task_id=None,
                current_action='create',
                current_task_content=f"{len(tasks)} tasks ({self.execution_mode} mode)",
                fixed_row_start=fixed_row
            )

            logger.debug(f"Plan created: {len(tasks)} tasks at row {fixed_row}")

        except Exception as e:
            logger.error(f"Error handling plan_created: {e}", exc_info=True)

    def _handle_plan_task_update(self, data: Dict[str, Any]) -> None:
        """Handle plan_task_update event - update task status in LivePlanCard.

        Event data schema:
            {
                "plan_id": str,
                "task_id": str,
                "status": "pending" | "running" | "completed" | "failed" | "cancelled",
                "duration_ms": int (optional),
                "error": str (optional)
            }
        """
        if not self.plan_card:
            logger.debug("Received plan_task_update but plan_card not initialized")
            return

        try:
            task_id = data.get('task_id')
            status = data.get('status', 'pending')
            error = data.get('error')

            # Update task status in local cache (with lock protection)
            with self._task_list_lock:
                for task in self.task_list:
                    if task['id'] == task_id:
                        task['status'] = status
                        if error:
                            task['error'] = error
                        break
                # Create a copy of task_list for LivePlanCard update
                task_list_copy = self.task_list.copy()

            # Get task index for LivePlanCard (1-based)
            task_index = self.task_id_to_index.get(task_id)

            # Determine current action for display
            action = None
            if status == 'running':
                action = 'start'
            elif status == 'completed':
                action = 'done'
            elif status == 'failed':
                action = 'error'

            # Update LivePlanCard (using copied task list)
            self.plan_card.update(
                tasks=task_list_copy,
                current_task_id=task_index if status == 'running' else None,
                current_action=action,
                current_task_content=self._get_task_name(task_id)
            )

            logger.debug(f"Task {task_id} status updated: {status}")

        except Exception as e:
            logger.error(f"Error handling plan_task_update: {e}", exc_info=True)

    def _handle_plan_task_output(self, data: Dict[str, Any]) -> None:
        """Handle plan_task_output event - display task output.

        Event data schema:
            {
                "plan_id": str,
                "task_id": str,
                "answer": str,
                "think": str (optional),
                "is_final": bool,
                "stream_mode": "delta" | "cumulative"
            }

        Note:
            This handler renders only final task output (is_final=True) to avoid
            interleaving multiple subtasks' streaming deltas in parallel mode.
        """
        try:
            task_id = data.get('task_id')
            answer = data.get('answer', '')
            is_final = data.get('is_final', False)

            if is_final:
                from dolphin.cli.ui.state import safe_print
                from dolphin.cli.ui.stream_renderer import LiveStreamRenderer

                safe_print(f"\n--- Task {task_id} Output ---")
                renderer = LiveStreamRenderer(verbose=True)
                renderer.start()
                try:
                    renderer.on_chunk(chunk_text=answer, full_text=answer, is_final=True)
                finally:
                    renderer.stop()
                logger.debug(f"Task {task_id} output displayed")

        except Exception as e:
            logger.error(f"Error handling plan_task_output: {e}", exc_info=True)

    def _handle_llm_stream(self, data: Dict[str, Any]) -> None:
        """Handle llm_stream event - render streaming LLM output in CLI.

        Event data schema:
            {
                "chunk_text": str,
                "full_text": str,
                "is_final": bool
            }
        """
        try:
            chunk_text = data.get("chunk_text", "")
            full_text = data.get("full_text", "")
            is_final = bool(data.get("is_final", False))

            if self._stream_renderer is None:
                from dolphin.cli.ui.stream_renderer import LiveStreamRenderer

                self._stream_renderer = LiveStreamRenderer(verbose=True)
                self._stream_renderer.start()

            # Always forward the chunk to renderer; it internally buffers and flushes.
            self._stream_renderer.on_chunk(
                chunk_text=chunk_text,
                full_text=full_text,
                is_final=is_final,
            )

            if is_final and self._stream_renderer is not None:
                try:
                    self._stream_renderer.stop()
                finally:
                    self._stream_renderer = None

        except Exception as e:
            logger.debug(f"Error handling llm_stream: {e}", exc_info=True)

    def _handle_plan_finished(self, data: Dict[str, Any]) -> None:
        """Handle plan_finished event - stop LivePlanCard and reset layout.

        Event data schema:
            {
                "plan_id": str,
                "total_tasks": int,
                "completed": int,
                "failed": int
            }
        """
        try:
            logger.debug(f"Plan finished: {data.get('completed')}/{data.get('total_tasks')} tasks completed")

            # Stop the LivePlanCard animation
            if self.plan_card and self.plan_card.running:
                self.plan_card.stop()
                self.plan_card = None

            # Reset the layout (remove Plan Panel reserve)
            self.layout.update_layout_for_plan(active=False, height=0)

        except Exception as e:
            logger.error(f"Error handling plan_finished: {e}", exc_info=True)

    def _get_task_name(self, task_id: str) -> str:
        """Get task name by task_id.

        Args:
            task_id: Task identifier

        Returns:
            Task name or task_id if not found
        """
        with self._task_list_lock:
            for task in self.task_list:
                if task['id'] == task_id:
                    return task.get('name', task_id)
            return task_id

    def cleanup(self) -> None:
        """Cleanup resources (stop animations, clear state)."""
        if self.plan_card:
            try:
                self.plan_card.stop()
            except Exception as e:
                logger.debug(f"Error stopping plan_card: {e}")
            self.plan_card = None

        # Clear state (with lock protection)
        with self._task_list_lock:
            self.plan_id = None
            self.task_list = []
            self.task_id_to_index = {}

    def is_plan_active(self) -> bool:
        """Check if a plan is currently active.

        Returns:
            True if plan_card is running
        """
        return self.plan_card is not None and self.plan_card.running

    def should_show_tool_card(self, tool_name: str) -> bool:
        """Check if a tool call should display a tool card.

        Args:
            tool_name: Name of the tool being called

        Returns:
            True if tool card should be displayed, False if silent
        """
        return tool_name not in SILENT_TOOLS
