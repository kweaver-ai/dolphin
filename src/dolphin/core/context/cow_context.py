"""Copy-On-Write Context for Subtask Isolation.

This module provides isolated context for subtasks in plan mode.

Logging conventions:
- DEBUG: Variable operations (set/delete/merge), initialization details
- INFO: Significant events (merge completion with summary)
- WARNING: Unexpected but recoverable situations
- ERROR: Critical failures requiring attention
"""

import copy
from typing import Any, Dict, Optional, Set

from dolphin.core.common.types import SourceType, Var
from dolphin.core.context.context import Context
from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.logging.logger import get_logger
from dolphin.core.skill.skillset import Skillset
from dolphin.core.context.variable_pool import VariablePool

logger = get_logger("cow_context")


class _TrackingVariablePool(VariablePool):
    """A VariablePool that tracks COWContext writes/deletes.

    This ensures that callers who bypass COWContext.set_variable()/delete_variable()
    and directly mutate `context.variable_pool` still participate in copy-on-write
    semantics and can be merged back to the parent context.
    """

    def __init__(self, owner: "COWContext"):
        super().__init__()
        self._owner = owner

    def set_var(self, name, value):
        super().set_var(name, value)
        tracked_value = value.value if isinstance(value, Var) else value
        self._owner.writes[name] = tracked_value
        self._owner.deletes.discard(name)

    def set_var_output(
        self, name, value, source_type: SourceType = SourceType.OTHER, skill_info=None
    ):
        super().set_var_output(name, value, source_type=source_type, skill_info=skill_info)
        # Track the user-facing value for merging behavior consistency.
        self._owner.writes[name] = value
        self._owner.deletes.discard(name)

    def delete_var(self, name):
        super().delete_var(name)
        self._owner.deletes.add(name)
        self._owner.writes.pop(name, None)


class COWContext(Context):
    """Copy-On-Write Context for subtask isolation.

    Contract:
    - Variables: COW isolation (read-through + local writes).
    - Messages: isolated (subtask-local).
    - Interrupt/output: delegated to parent for unified control and UI routing.
    - Output events are tagged with task_id for UI routing.
    """

    def __init__(self, parent: Context, task_id: str):
        """Initialize COWContext with parent and task ID.

        Args:
            parent: Parent context to delegate to
            task_id: Task identifier for event tagging
        """
        # In Plan mode, subtasks should run in "silent" mode (is_cli=False) to avoid
        # their output interfering with the LivePlanCard and StatusBar UI components.
        # Subtask outputs are captured in task.answer and can be retrieved via _get_task_output().
        super().__init__(
            config=parent.config,
            global_skills=parent.global_skills,
            memory_manager=parent.memory_manager,
            global_types=parent.global_types,
            skillkit_hook=getattr(parent, "skillkit_hook", None),
            context_manager=ContextManager(),
            # Subtasks should not stream raw output to stdout. Their outputs are
            # captured and surfaced via plan events (plan_task_output) instead.
            verbose=False,
            is_cli=False,  # Subtasks run silently to avoid output conflicts with plan UI
        )

        self.parent = parent
        self.task_id = task_id
        self.writes: Dict[str, Any] = {}
        self.deletes: Set[str] = set()

        # Create a new isolated VariablePool to prevent direct mutations to parent's pool.
        # This ensures COW isolation even if code bypasses set_variable() and directly
        # calls context.variable_pool.set_var().
        self._parent_pool = parent.variable_pool  # Keep reference for read-through
        self.variable_pool = _TrackingVariablePool(self)  # New empty pool for local writes (tracked)

        # Isolate messages/buckets for subtask execution.
        self.messages = {}
        self.messages_dirty = True

        # Keep IDs aligned for observability.
        self.user_id = parent.user_id
        self.session_id = parent.session_id
        self.cur_agent = parent.cur_agent

        # Share the interrupt event for cooperative cancellation.
        self._interrupt_event = parent.get_interrupt_event()

        # Subtasks must NOT be considered "plan-enabled" to avoid infinite loops.
        self._plan_enabled = False
        # Keep plan_id aligned for observability, while still disabling plan mode APIs.
        self._plan_id = parent.get_plan_id()
        self.task_registry = None

        # Filter out orchestration-only tools (e.g., PlanSkillkit) from subtask toolset.
        # Create a new isolated Skillset instead of referencing parent's skillkit directly
        # to prevent permission escalation via context.skillkit.getSkills()
        self._calc_all_skills()
        self.all_skills = self._filter_subtask_skills(self.all_skills)
        # Create a new Skillset that contains only filtered skills
        # This ensures context.get_skill() and context.skillkit.getSkills() both respect filtering
        filtered_skillkit = Skillset()
        for skill in self.all_skills.getSkills():
            filtered_skillkit.addSkill(skill)
        self.skillkit = filtered_skillkit

        # Inherit last-session configs where safe.
        self._last_model_name = getattr(parent, "_last_model_name", None)
        self._last_explore_mode = getattr(parent, "_last_explore_mode", None)
        self._last_system_prompt = getattr(parent, "_last_system_prompt", None)
        self._last_skills = None

        logger.debug(f"COWContext initialized for task: {task_id}")

    @staticmethod
    def _filter_subtask_skills(skillset: Skillset) -> Skillset:
        """Filter out skillkits that should not be exposed to subtasks."""
        filtered = Skillset()
        for skill in skillset.getSkills():
            owner = None
            if hasattr(skill, "get_owner_skillkit"):
                owner = skill.get_owner_skillkit()
            if owner is not None:
                should_exclude = getattr(owner, "should_exclude_from_subtask", None)
                if callable(should_exclude):
                    try:
                        if bool(should_exclude()):
                            continue
                    except Exception:
                        # Fail-open: do not exclude if the hook misbehaves.
                        pass
            filtered.addSkill(skill)
        return filtered

    def get_variable(self, key: str, default_value: Any = None) -> Any:
        """Get a variable (check local layer first, then parent).

        Args:
            key: Variable key
            default_value: Default value if not found

        Returns:
            Variable value, or default_value if deleted or not found

        Note:
            Container types (list, dict, set) are deep-copied to prevent
            accidental mutation of parent context's data through in-place operations
            like list.append() or dict.update().
        """
        if key in self.deletes:
            return default_value
        # Check local variable_pool first (for compatibility with direct variable_pool.set_var()).
        # NOTE: Variable values can legitimately be None, so use a sentinel to distinguish
        # "missing key" vs "stored None".
        sentinel = object()
        local_value = self.variable_pool.get_var_value(key, sentinel)
        if local_value is not sentinel:
            return self._safe_copy_if_mutable(local_value, key)
        # Check writes dict (explicit set_variable() calls)
        if key in self.writes:
            return self._safe_copy_if_mutable(self.writes[key], key)
        # Fall back to parent context (keeps compatibility logic such as flags).
        parent_value = self.parent.get_var_value(key, default_value)
        return self._safe_copy_if_mutable(parent_value, key)

    @staticmethod
    def _safe_copy_if_mutable(value: Any, key: str) -> Any:
        """Deep copy mutable container types to prevent accidental mutation.

        Args:
            value: Variable value
            key: Variable key (for error reporting)

        Returns:
            Deep copy if value is a mutable container (list/dict/set or custom object),
            original value otherwise.

        Raises:
            TypeError: If a mutable object cannot be deep-copied, ensuring isolation.

        Note:
            Isolation is guaranteed by deepcopy. If an object is not deepcopy-able,
            it cannot be safely used in a COWContext as mutation would leak to parent.
        """
        if value is None:
            return None

        # Fast path for immutable primitives: return as-is
        if isinstance(value, (str, int, float, bool, bytes)):
            return value

        # Mutable types (containers and custom objects): try deepcopy
        try:
            return copy.deepcopy(value)
        except Exception as e:
            # Item 3: Fail-fast for non-deepcopyable objects to ensure isolation.
            logger.warning(
                f"Isolation failure for variable '{key}': Object of type {type(value).__name__} is not deepcopyable. "
                "Explicitly raising TypeError to prevent silent parent context corruption."
            )
            raise TypeError(
                f"Cannot safely isolate variable '{key}': "
                f"Object of type {type(value).__name__} is not deepcopyable. "
                "Ensure task variables are serializable (e.g., data classes, dicts, primitives)."
            ) from e

    def get_var_value(self, key: str, default_value: Any = None) -> Any:
        """Get variable value (alias for get_variable for Context compatibility).

        Args:
            key: Variable key
            default_value: Default value if not found

        Returns:
            Variable value
        """
        return self.get_variable(key, default_value)

    def set_variable(self, key: str, value: Any):
        """Set a variable in the local layer only (copy-on-write).

        Args:
            key: Variable key
            value: Variable value

        Note:
            This does NOT modify parent's variable_pool, ensuring isolation.
            Use merge_to_parent() to propagate changes after task completion.
            Updates both self.writes (tracking) and self.variable_pool (isolation).
        """
        self.writes[key] = value
        self.deletes.discard(key)
        # Update local variable_pool to catch both set_variable() and variable_pool.set_var() paths
        self.variable_pool.set_var(key, value)
        logger.debug(f"COWContext[{self.task_id}] set variable: {key}")

    def delete_variable(self, key: str):
        """Delete a variable in the local layer (tombstone, copy-on-write).

        Args:
            key: Variable key to delete

        Note:
            This does NOT modify parent's variable_pool, ensuring isolation.
            The delete is recorded as a tombstone in self.deletes.
        """
        self.deletes.add(key)
        self.writes.pop(key, None)
        # Delete from local variable_pool to ensure isolation
        self.variable_pool.delete_var(key)
        logger.debug(f"COWContext[{self.task_id}] deleted variable: {key}")

    def get_local_changes(self) -> Dict[str, Any]:
        """Return all local writes.

        Returns:
            Dictionary of local variable writes
        """
        return self.writes.copy()

    def clear_local_changes(self):
        """Clear local writes and deletes to release memory.

        Note:
            This should be called after merge_to_parent() to free memory held by
            intermediate variables. Useful for long-running subtasks that generate
            many temporary variables (e.g., web scraping loops).

        Warning:
            Do NOT call this before merge_to_parent() unless you want to discard changes.
        """
        self.writes.clear()
        self.deletes.clear()
        # Also clear the local variable pool
        if hasattr(self.variable_pool, 'clear'):
            self.variable_pool.clear()
        logger.debug(f"COWContext[{self.task_id}] cleared local changes to release memory")

    def merge_to_parent(self, keys: Optional[Set[str]] = None):
        """Merge local variable writes and deletes back to parent.

        Args:
            keys: Optional set of keys to merge (if None, merge all)

        Note:
            Merges both writes (set operations) and deletes (delete operations).
        """
        if keys:
            # Selective merge
            merged_count = 0
            deleted_count = 0
            for key in keys:
                if key in self.deletes:
                    self.parent.delete_variable(key)
                    deleted_count += 1
                elif key in self.writes:
                    self.parent.set_variable(key, self.writes[key])
                    merged_count += 1
            logger.debug(
                f"COWContext[{self.task_id}] merged {merged_count} variables, "
                f"deleted {deleted_count} variables to parent"
            )
        else:
            # Full merge
            # First apply deletes
            for key in self.deletes:
                self.parent.delete_variable(key)
            # Then apply writes
            for key, value in self.writes.items():
                self.parent.set_variable(key, value)
            logger.debug(
                f"COWContext[{self.task_id}] merged {len(self.writes)} variables, "
                f"deleted {len(self.deletes)} variables to parent"
            )

    def check_user_interrupt(self) -> None:
        """Delegate interrupt checks to parent."""
        return self.parent.check_user_interrupt()

    def write_output(self, event_type: str, data: Dict[str, Any]) -> None:
        """Tag output events with task_id and forward to parent."""
        payload = dict(data)
        payload.setdefault("task_id", self.task_id)
        payload.setdefault("plan_id", self.parent.get_plan_id())
        return self.parent.write_output(event_type, payload)

    def get_plan_id(self) -> Optional[str]:
        """Expose parent plan_id for event tagging/observability."""
        return self.parent.get_plan_id()

    def enable_plan(self, plan_id: Optional[str] = None) -> None:
        """Prevent nested plan orchestration in subtasks.

        Raises:
            RuntimeError: Always raises to prevent nested planning.

        Note:
            This is intentionally a hard error rather than a soft warning.
            Subtasks should execute their assigned work, not create sub-plans.
            The error message is designed to help models understand the constraint.
        """
        raise RuntimeError(
            "Plan orchestration is not supported inside a subtask context. "
            "Subtasks should focus on executing their assigned work directly. "
            "If you need to break down the subtask further, return the breakdown "
            "as part of your answer for the parent to orchestrate."
        )

    def __getattr__(self, name: str):
        """Delegate unknown attributes to parent with special handling for skillkit.

        Args:
            name: Attribute name

        Returns:
            Attribute value from parent, or filtered skillkit for security

        Raises:
            AttributeError: If attribute not found in parent

        Note:
            Special handling for 'skillkit' attribute to prevent subtasks from
            bypassing PLAN_ORCHESTRATION_TOOLS filtering by directly accessing
            parent's skillkit via attribute delegation.
        """
        # Intercept skillkit access to return filtered version
        if name == "skillkit":
            # Return the filtered skillkit stored in __init__
            # This prevents subtasks from accessing parent's unfiltered skillkit
            return object.__getattribute__(self, name)

        # Delegate all other attributes to parent
        return getattr(self.parent, name)
