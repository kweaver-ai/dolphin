import asyncio
import os
import json
import time
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, TYPE_CHECKING

from dolphin.core.common.enums import MessageRole, SkillInfo, Messages, SkillType
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.common.constants import (
    KEY_MAX_ANSWER_CONTENT_LENGTH,
    KEY_SESSION_ID,
    KEY_USER_ID,
    KEY_HISTORY,
    MAX_ANSWER_CONTENT_LENGTH,
    MAX_LOG_LENGTH,
    MAX_OUTPUT_EVENTS,
)
from dolphin.core.context_engineer.core.context_manager import (
    ContextManager,
)
from dolphin.core.runtime.runtime_graph import RuntimeGraph
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skillset import Skillset
from dolphin.core.skill.skill_matcher import SkillMatcher

from dolphin.core.common.types import Var
from dolphin.core.context.var_output import VarOutput, SourceType
from dolphin.core.context.variable_pool import VariablePool
from dolphin.core.logging.logger import get_logger
from dolphin.core.trajectory.trajectory import Trajectory

# Import sdk/lib modules under TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from dolphin.sdk.skill.global_skills import GlobalSkills
    from dolphin.lib.memory.manager import MemoryManager
    from dolphin.lib.skill_results.skillkit_hook import SkillkitHook


logger = get_logger("context")


class Context:
    """Runtime conversation state container.

    Architecture notes:
    - `context_manager` is the single source of truth for model-facing messages.
      It stores bucketed messages (`_system`, `_history`, `_query`, `_scratchpad`)
      and assembles them via `to_dph_messages()`.
    - Tool-call and tool-result messages are preserved in `_scratchpad` during a
      running explore session and are visible to subsequent LLM turns in the same
      session.
    - `reset_for_block()` clears transient buckets (`_scratchpad`, `_system`,
      `_query`) at the start of a new block, so those messages are not guaranteed
      to survive across block boundaries.
    - Cross-turn persistence primarily relies on `_history` in the variable pool.
      Current default history persistence is lightweight (mainly user/assistant,
      plus pinned content), not a full native tool message chain.
    - `trajectory` is an optional execution record for debugging/replay and can
      keep complete staged messages (including tool interactions) when enabled.
    - Context-window pruning/compression for final LLM requests is handled by the
      message compressor in the LLM client layer, not by this class itself.
    """

    def __init__(
        self,
        config: Optional[GlobalConfig] = None,
        global_skills: Optional["GlobalSkills"] = None,
        memory_manager: Optional["MemoryManager"] = None,
        global_types=None,
        skillkit_hook: Optional["SkillkitHook"] = None,
        context_manager: Optional[ContextManager] = None,
        verbose: bool = False,
        is_cli: bool = False,
    ):
        self.config = config
        self.global_skills = global_skills
        self.memory_manager = memory_manager
        self.global_types = global_types
        self.variable_pool = VariablePool()
        self.skillkit = Skillkit()
        self.messages: Dict[str, Messages] = (
            dict()
        )  # Use Messages class instead of list
        self.messages_dirty: bool = True  # Initially dirty, ensure synchronization on first use
        self.user_id = None
        self.session_id = None
        self.cur_agent = None
        self.max_answer_len = MAX_ANSWER_CONTENT_LENGTH
        self.verbose = verbose  # Control log detail level
        self.is_cli = is_cli    # Control CLI rendering (Rich/Live Markdown)

        self.time_extracted_knowledge = None

        self.runtime_graph = RuntimeGraph()
        
        # Initialize all_skills to avoid AttributeError
        self.all_skills = Skillset()

        # Initialize skillkit_hook
        if skillkit_hook is not None:
            self.skillkit_hook = skillkit_hook
        else:
            self.skillkit_hook = None

        # Initialize context_manager
        self.context_manager = context_manager or ContextManager()

        # Initialize trajectory (disabled by default, enabled via init_trajectory)
        self.trajectory: Optional[Trajectory] = None

        # Historical injection idempotency flag: avoid re-injecting variable history within the same context lifecycle
        self.history_injected: bool = False

        # The name of the model used last (to maintain model consistency in multi-turn conversations)
        self._last_model_name: Optional[str] = None

        # The final skills configuration used (inherited skill filtering configuration for multi-turn conversations)
        self._last_skills: Optional[List[str]] = None

        # The final exploration mode used (when conducting multi-turn conversations, inherits the mode configuration)
        self._last_explore_mode: Optional[str] = None

        # The last system prompt used (to maintain consistent system bucket across multi-turn conversations)
        self._last_system_prompt: Optional[str] = None

        # User interrupt event (injected by Agent layer for cooperative cancellation)
        self._interrupt_event: Optional[asyncio.Event] = None

        # Plan Mode support (unified architecture)
        self._plan_enabled: bool = False
        self._plan_id: Optional[str] = None
        self.task_registry: Optional["TaskRegistry"] = None

        # Nesting level tracking (to prevent infinite recursion in plan mode)
        # Incremented when fork() is called
        self._nesting_level: int = 0

        # Output event buffer (for UI/SDK consumption)
        # Use bounded deque to prevent unbounded memory growth in long-running sessions
        self._output_events: deque = deque(maxlen=MAX_OUTPUT_EVENTS)

        # Calculate all skills initially
        self._calc_all_skills()

    def set_skillkit_hook(self, skillkit_hook: "SkillkitHook"):
        """Set skillkit_hook"""
        self.skillkit_hook = skillkit_hook
        logger.debug("skillkit_hook has been set")

    def get_skillkit_hook(self) -> Optional["SkillkitHook"]:
        """Get skillkit_hook"""
        return self.skillkit_hook

    def has_skillkit_hook(self) -> bool:
        """Check if skillkit_hook exists"""
        return self.skillkit_hook is not None

    def init_trajectory(self, trajectory_path: str, overwrite: bool = True):
        """Initialize trajectory recording

        Args:
            trajectory_path: Path to save the trajectory file
            overwrite: Whether to overwrite existing trajectory files (default is True)
        """
        self.trajectory = Trajectory(trajectory_path, overwrite=overwrite)
        logger.debug(f"Trajectory initialized: {trajectory_path} (overwrite={overwrite})")

    def copy(self):
        copied = Context(
            config=self.config,
            global_skills=self.global_skills,
            memory_manager=self.memory_manager,
            global_types=self.global_types,
            verbose=self.verbose,
            is_cli=self.is_cli,
        )
        copied.variable_pool = self.variable_pool.copy()
        copied.skillkit = self.skillkit
        # Copy Messages object
        copied.messages = {}
        for agent_name, messages in self.messages.items():
            copied.messages[agent_name] = messages.copy()
        # copied.compressed_messages = self.compressed_messages  # Commented out this line because the attribute does not exist
        copied.cur_agent = self.cur_agent
        copied.user_id = self.user_id
        copied.session_id = self.session_id
        copied.cur_agent = self.cur_agent
        copied.max_answer_len = self.max_answer_len
        copied.verbose = self.verbose
        copied.is_cli = self.is_cli
        copied.runtime_graph = self.runtime_graph.copy()
        return copied

    def set_cur_agent(self, agent):
        self.cur_agent = agent
        self.runtime_graph.set_agent(agent)

    def get_cur_agent(self):
        return self.cur_agent

    def get_cur_agent_name(self):
        return self.cur_agent.get_name() if self.cur_agent else None

    def set_user_id(self, user_id: str):
        self.user_id = user_id

    def get_user_id(self):
        return self.user_id

    def set_session_id(self, session_id: str):
        self.session_id = session_id

    def get_session_id(self):
        return self.session_id

    def set_max_answer_len(self, max_answer_len: int):
        self.max_answer_len = max_answer_len

    def get_max_answer_len(self):
        return self.max_answer_len

    def set_verbose(self, verbose: bool):
        """Set verbose mode"""
        self.verbose = verbose

    def get_verbose(self) -> bool:
        """Get verbose mode status"""
        return self.verbose

    def is_verbose(self) -> bool:
        """Check if verbose mode is enabled (detailed logging)"""
        return self.verbose

    def set_cli_mode(self, is_cli: bool):
        """Set CLI mode (controls Rich/terminal beautification)"""
        self.is_cli = is_cli

    def is_cli_mode(self) -> bool:
        """Check if running in CLI mode (controls Rich/terminal beautification)
        
        This is separate from verbose:
        - verbose: controls log detail level
        - is_cli: controls terminal beautification (Rich Live Markdown, colors, etc.)
        
        Use cases:
        - verbose=True, is_cli=True: CLI with detailed beautiful output
        - verbose=True, is_cli=False: API/script with detailed plain text logs
        - verbose=False, is_cli=True: CLI with quiet but beautiful output
        - verbose=False, is_cli=False: API/script in silent mode
        """
        return self.is_cli

    def get_config(self):
        return self.config

    def get_memory_manager(self):
        return self.memory_manager

    def get_global_types(self):
        return self.global_types

    def get_history_messages(self, normalize: bool = True, projected: bool = False):
        """Get history, default normalized to Messages without modifying the original storage structure of the variable pool.

        Args:
            normalize: Whether to convert history into a Messages object
            projected: When True, apply HistoryProjector to trim older turns
                       (drops tool chains from old turns, keeps recent ones intact).
                       Only effective when normalize=True.

        Returns:
            Messages or the original stored history
        """
        history_raw = self.get_var_value(KEY_HISTORY)
        if not normalize:
            return history_raw

        if isinstance(history_raw, Messages):
            result = history_raw.copy()
        elif history_raw is None:
            result = Messages()
        elif isinstance(history_raw, list):
            result = Messages()
            result.extend_plain_messages(history_raw)
        else:
            raise ValueError(f"Invalid history format: {type(history_raw)}, expected list or Messages object.")

        if projected and result.get_messages():
            from dolphin.core.context.history_projector import HistoryProjector
            result = HistoryProjector().project(result)

        return result

    def set_variable(self, name, value):
        if name == KEY_USER_ID:
            self.set_user_id(value)
        elif name == KEY_SESSION_ID:
            self.set_session_id(value)
        elif name == KEY_MAX_ANSWER_CONTENT_LENGTH:
            self.set_max_answer_len(int(value))

        self.variable_pool.set_var(name, value)

    def set_var_output(
        self,
        name,
        value,
        source_type=SourceType.OTHER,
        skill_info: Optional[SkillInfo] = None,
    ):
        """Set variable
                :param name: variable name
                :param value: variable value
                :param source_type: variable source type
                :param skill_info: skill information
        """
        self.variable_pool.set_var_output(name, value, source_type, skill_info)

    def init_variables(self, variables):
        """Initialize variable pool
                :param variables: variable dictionary
        """
        self.variable_pool.init_variables(variables)

    def init_skillkit(self, skillkit: Skillkit):
        self.set_skills(skillkit)

    def init_agents(self, agents):
        self.agents = agents

    def add_agents(self, agents):
        for key, value in agents.items():
            self.agents[key] = value

    def get_agent(self, agent_name):
        return self.agents[agent_name]

    def get_agents(self):
        return self.agents

    def has_agent(self, agent_name):
        """Check if the specified agent skill exists
                :param agent_name: agent name
                :return: whether it exists
        """
        # Support direct use of agent_name and skill names with prefixes
        return (
            self.skillkit.hasSkill(agent_name)
            or self.skillkit.hasSkill(f"run_{agent_name}")
            or self.skillkit.hasSkill(f"arun_{agent_name}")
        )

    def exec_agent(self, agent_name, **kwargs):
        """Synchronous execution of agent (via skill system)
                :param agent_name: agent name
                :param kwargs: parameters passed to the agent
                :return: execution result
        """
        # First try directly using agent_name, then try the run_ prefix
        skill_name = agent_name
        if not self.skillkit.hasSkill(skill_name):
            skill_name = f"run_{agent_name}"

        if not self.skillkit.hasSkill(skill_name):
            raise ValueError(
                f"Agent skill not found: {agent_name} (tried: {agent_name}, run_{agent_name})"
            )

        result = self.skillkit.exec(skill_name, **kwargs)
        return result.result if hasattr(result, "result") else result

    async def aexec_agent(self, agent_name, **kwargs):
        """Asynchronously execute agent (via skill system)
                :param agent_name: agent name
                :param kwargs: parameters to pass to the agent
                :return: execution result
        """
        # First try directly using agent_name, then try the arun_ prefix
        skill_name = agent_name
        if not self.skillkit.hasSkill(skill_name):
            skill_name = f"arun_{agent_name}"

        if not self.skillkit.hasSkill(skill_name):
            raise ValueError(
                f"Agent skill not found: {agent_name} (tried: {agent_name}, arun_{agent_name})"
            )

        result = await self.skillkit.aexec(skill_name, **kwargs)
        return result.result if hasattr(result, "result") else result

    def get_var_value(self, name, default_value=None):
        """Get variable
                :param name: variable name
                :return: variable value, or None if it does not exist
        """
        # Compatibility layer: If it's a known flag, redirect to the new system
        # Return string ("true"/"false") or boolean (True/False) based on the caller's default value type
        # - If default_value is None or str: return the string "true"/"false" (compatible with the old string comparison style)
        # - Otherwise: return boolean True/False (compatible with scenarios where it's used directly as a boolean)
        # Lazy import to avoid circular dependencies; use definitions.DEFAULT_VALUES as the true source
        try:
            from dolphin.core.flags.definitions import DEFAULT_VALUES

            if name in DEFAULT_VALUES:
                from dolphin.core import flags

                enabled = bool(flags.is_enabled(name))
                if default_value is None or isinstance(default_value, str):
                    return "true" if enabled else "false"
                return enabled
        except Exception:
            pass

        # --- Backward Compatibility Layer ---
        # To prevent the system internal conversation history from being overwritten by 
        # user assignments like '-> history', the internal key was renamed to '_history'.
        # However, to avoid breaking existing code or snapshots:
        # 1. If 'history' is requested, we first check if there is a user-defined 'history'.
        # 2. If not found, we fallback to the internal '_history' (KEY_HISTORY).
        if name == "history":
            val = self.variable_pool.get_var_value("history")
            # Only honour user-defined "history" when it carries a meaningful
            # value (non-None and non-empty-string).  An empty string assignment
            # like ``-> history`` should not shadow the internal _history.
            if val is not None and val != "":
                return val
            # Return internal conversation history if user hasn't overridden it
            return self.variable_pool.get_var_value(KEY_HISTORY, default_value)
        # ------------------------------------

        return self.variable_pool.get_var_value(name, default_value)

    def get_var_path_value(self, varpath, default_value=None):
        """Get variable path value
                :param varpath: variable path
                :return: variable path value, returns None if it does not exist
        """
        return self.variable_pool.get_var_path_value(varpath, default_value)

    def get_var_obj(self, name):
        """Get the variable object
                :param name: variable name
                :return: Variable object, or None if it does not exist
        """
        return self.variable_pool.get_var(name)

    def get_all_variables(self):
        """Get all variables
                :return: Dictionary mapping variable names to variable values
        """
        return self.variable_pool.get_all_variables()

    def get_user_variables(self, include_system_context_vars=False):
        """Get user-defined variables, excluding internal variables.

                Parameters:
                    include_system_context_vars: Whether to include system context variables (e.g., _user_id, _session_id, etc.)
                                                 Default is False for backward compatibility

                :return: Dictionary mapping user variable names to their values
        """
        return self.variable_pool.get_user_variables(include_system_context_vars)

    def get_all_variables_values(self):
        """Get all variable values
                :return: List of variable values
        """
        return self.variable_pool.get_all_variables_values()

    def get_variables_values(self, variable_names: list[str]):
        """Get the variable dictionary for the specified variable names to improve performance and avoid retrieving all variables.
                :param variable_names: List of variable names to retrieve
                :return: Dictionary containing the specified variables, in the format {variable name: variable value}
        """
        if not variable_names:
            return {}

        result = {}
        for var_name in variable_names:
            if self.variable_pool.contain_var(var_name):
                var = self.variable_pool.get_var(var_name)
                result[var_name] = (
                    var.value if var is not None and hasattr(var, "value") else None
                )
        return result

    def get_skillkit(self, skillNames: Optional[List[str]] = None):
        """Get the skill set, supporting wildcard (glob), exact matching, and optional skillkit namespace.

        Args:
            skillNames: List of skill patterns.
                               - Plain tool name/pattern: "_python", "*_resource*"
                               - Namespaced pattern: "<skillkit>.<pattern>", e.g. "resource_skillkit.*"
                               If None, return the merged skill set;
                               If empty list [], indicates no skills are enabled

        Returns:
            Skillset: The matched skill set, or the merged skill set if no skills match
        """

        # If no matching pattern is provided, return the merged skill set
        if skillNames is None:
            return self.all_skills

        # When an explicit empty list is passed in, it indicates that the caller does not wish to expose any tools.
        # For example, the scenario where tools=[] is configured in DPH
        if isinstance(skillNames, list) and len(skillNames) == 0:
            return Skillset()

        skills = self.all_skills.getSkills()
        owner_names = SkillMatcher.get_owner_skillkits(skills)

        # Use optimized batch matching (pre-parses patterns, deduplicates results)
        matched_skills, any_namespaced_pattern = SkillMatcher.match_skills_batch(
            skills, skillNames, owner_names
        )

        # If no skills match:
        # - if namespaced patterns were used, return an empty set (safer default)
        # - otherwise keep the historical behavior and return the merged skill set
        if not matched_skills:
            if any_namespaced_pattern:
                return Skillset()
            return self.all_skills

        # Return the matching skill set
        result_skillset = Skillset()
        for skill in matched_skills:
            result_skillset.addSkill(skill)
        
        # Auto-inject _get_result_detail if needed
        self._inject_detail_skill_if_needed(result_skillset)
        
        return result_skillset

    def _inject_detail_skill_if_needed(self, skillset: Skillset):
        """Auto-inject _get_cached_result_detail if any skill uses omitting modes (SUMMARY/REFERENCE)"""
        try:
            from dolphin.core.skill.context_retention import ContextRetentionMode
            from dolphin.lib.skillkits.system_skillkit import SystemFunctions
        except ImportError:
            return

        skills = skillset.getSkills()
        should_inject = False
        
        for skill in skills:
            # Check for configured retention strategy
            config = getattr(skill.func, '_context_retention', None)
            if config and config.mode in (
                ContextRetentionMode.SUMMARY,
                ContextRetentionMode.REFERENCE,
            ):
                should_inject = True
                break
        
        if should_inject:
            # Check if already exists in skillset
            has_detail_skill = any(
                "_get_cached_result_detail" in s.get_function_name()
                for s in skills
            )
            
            if not has_detail_skill:
                # Try to get the skill from SystemFunctions
                # We try different name variations just in case
                detail_skill = SystemFunctions.getSkill("_get_cached_result_detail")
                if not detail_skill:
                    detail_skill = SystemFunctions.getSkill("system_functions._get_cached_result_detail")
                
                # If still not found (e.g. SystemFunctions not initialized with it), we can pick it manually if possible
                # But typically SystemFunctions singleton has it.
                if detail_skill:
                     skillset.addSkill(detail_skill)
                else:
                    # Fallback: look through SystemFunctions.getSkills() manually
                    for s in SystemFunctions.getSkills():
                        if "_get_cached_result_detail" in s.get_function_name():
                            skillset.addSkill(s)
                            break

    def get_skill(self, name):
        return self.skillkit.getSkill(name)

    def get_skill_type(self, skill_name: str) -> SkillType:
        """Get the type of a skill

        Args:
            skill_name: The name of the skill

        Returns:
            SkillType: The type of the skill
        """
        skill = self.get_skill(skill_name)
        if skill:
            # Try to get the tool type, return the default type if not available
            return getattr(skill, "tool_type", SkillType.TOOL)
        else:
            # Default returns TOOL type
            return SkillType.TOOL

    def is_skillkit_empty(self):
        return self.skillkit is None or self.skillkit.isEmpty()

    def exec_skill(self, name, **kwargs):
        return self.skillkit.exec(name, **kwargs)

    async def aexec_skill(self, name, **kwargs):
        return self.skillkit.aexec(name, **kwargs)

    def get_agent_skill(self, skill_function: SkillFunction):
        if self.global_skills is None:
            return None
        return self.global_skills.getAgent(skill_function.get_function_name())

    def sync_variables(self, context: "Context"):
        self.variable_pool.sync_variables(context.variable_pool)

    def delete_variable(self, name):
        """Delete variable
                :param name: variable name
        """
        self.variable_pool.delete_var(name)

    def clear_variables(self):
        """Clear all variables"""
        self.variable_pool.clear()

    def list_variables(self):
        """List all variables
                :return: A list containing all variable names
        """
        return self.variable_pool.keys()

    def set_skills(self, skillkit):
        self.skillkit = skillkit
        self._calc_all_skills()

    def append_var_output(
        self, name, value, source_type=SourceType.OTHER, skill_info=None
    ):
        var = self.variable_pool.get_var(name)
        if not var:
            var = VarOutput(
                name=name, value=[], source_type=SourceType.LIST, skill_info=skill_info
            )

        if not isinstance(var, VarOutput):
            if isinstance(var, Var):
                if var.value:
                    if isinstance(var.value, list):
                        init_var = VarOutput(
                            name=name,
                            value=[],
                            source_type=SourceType.LIST,
                            skill_info=skill_info,
                        )
                        for item in var.value:
                            init_var.add(
                                VarOutput(
                                    name=name,
                                    value=item,
                                    source_type=source_type,
                                    skill_info=skill_info,
                                )
                            )
                        var = init_var
                    else:
                        var = VarOutput(
                            name=name,
                            value=[var],
                            source_type=SourceType.LIST,
                            skill_info=skill_info,
                        )
                else:
                    var = VarOutput(
                        name=name,
                        value=[],
                        source_type=SourceType.LIST,
                        skill_info=skill_info,
                    )
            else:
                var = VarOutput(
                    name=name,
                    value=[var],
                    source_type=SourceType.LIST,
                    skill_info=skill_info,
                )

        new_var = var.add(
            VarOutput(
                name=name, value=value, source_type=source_type, skill_info=skill_info
            )
        )
        self.variable_pool.set_var(name, new_var)

    def set_last_var_output(
        self, name, value, source_type=SourceType.OTHER, skill_info=None
    ):
        var = self.variable_pool.get_var(name)
        if var:
            var.set_last(
                VarOutput(
                    name=name,
                    value=value,
                    source_type=source_type,
                    skill_info=skill_info,
                )
            )
            self.variable_pool.set_var(name, var)

    def update_var_output(
        self, name, value, source_type=SourceType.OTHER, skill_info=None
    ):
        """Update variable
                :param name: Variable name
                :param value: Variable value
                :param source_type: Variable source type
                :param skill_info: Skill information
        """
        var = self.variable_pool.get_var(name)
        if var:
            # Check if the variable has the corresponding attribute and attempt to update it
            if hasattr(var, "value"):
                if isinstance(getattr(var, "value", None), list):
                    var.value[-1] = value  # type: ignore
                else:
                    setattr(var, "value", value)
            # Try to update source_type and skill_info
            if hasattr(var, "source_type"):
                setattr(var, "source_type", source_type)
            if hasattr(var, "skill_info"):
                setattr(var, "skill_info", skill_info)
        else:
            self.set_var_output(name, value, source_type, skill_info)

    def recognize_variable(self, dolphin_str):
        # Identify the positions of all variables in a string - Simple variables: `$variableName` - Array indices: `$variableName[index]` - Nested properties: `$variableName.key1.key2`
        """Identify the positions of all variables in a string
                :param dolphin_str: The string to be identified
                :return: A list of tuples containing variable names and their positions [('variable name', (start position, end position)), ...]
        """
        return self.variable_pool.recognize_variable(dolphin_str)

    def get_variable_type(self, variable_str):
        return self.variable_pool.get_variable_type(variable_str)

    def reset_messages(self):
        agent_name = self.get_cur_agent_name()
        if agent_name is None:
            agent_name = "default"
        self.messages[agent_name] = Messages()
        # Note: This only clears the image, messages in context_manager still exist
        # If you need to clear the context_manager, you should call context_manager.clear_bucket()
        # Here maintain the original behavior, only clear the image
        self.messages_dirty = False  # The mirror has already been explicitly set, no synchronization is needed.

        # Reset the historical injection flag to allow new sessions to re-inject history.
        self.history_injected = False

    def reset_for_block(self):
        """Reset context state for new code blocks.

        This method uniformly handles the reset logic before executing a code block, including:
        1. Mark trajectory stage baseline (needs to be done before clearing, as current state is required)
        2. Reset message mirroring
        3. Clean up temporary buckets (SCRATCHPAD, SYSTEM, QUERY)

        Note: This method is specifically designed for resetting before executing code blocks and should not be used in other scenarios.
        """
        # Step 1: Mark stage baseline BEFORE clearing (trajectory needs current state)
        # The baseline captures the message count before this block starts executing
        if getattr(self, "trajectory", None):
            try:
                self.trajectory.begin_stage(self.context_manager)
                logger.debug("Trajectory stage baseline marked")
            except (AttributeError, TypeError) as e:
                logger.debug(f"Failed to mark trajectory baseline: {e}")

        # Step 2: Reset message mirror for fresh block execution
        # This prevents message accumulation across blocks and ensures clean state
        self.reset_messages()

        # Step 3: Clear transient buckets that should not persist across blocks:
        # - SCRATCHPAD: temporary working memory for current block only
        # - SYSTEM: system prompt may be different per block
        # - QUERY: user query changes per block
        # Note: These buckets will be re-populated by specific blocks (e.g., llm_chat)
        try:
            from dolphin.core.context_engineer.config.settings import BuildInBucket
            
            cm = self.context_manager
            removed_buckets = []
            for bucket in [BuildInBucket.SCRATCHPAD.value,
                          BuildInBucket.SYSTEM.value,
                          BuildInBucket.QUERY.value]:
                try:
                    cm.remove_bucket(bucket)
                    removed_buckets.append(bucket)
                except (AttributeError, KeyError):
                    pass  # Bucket doesn't exist, which is fine

            if removed_buckets:
                logger.debug(f"Cleared buckets for fresh block state: {removed_buckets}")
        except Exception as e:
            # Log unexpected errors but don't fail block execution
            logger.warning(f"Unexpected error during bucket cleanup: {e}")

    def clear_messages(self):
        """Clear message history - alias of reset_messages"""
        self.reset_messages()

    def set_messages(self, messages: Messages):
        self.get_messages().set_messages(messages)  # Use Messages.set_messages

    def sync_messages_from_llm_context(self, force: bool = False) -> Messages:
        """Core synchronization method: synchronize messages from the context_manager single data source to the current Agent's mirror.

        Args:
            force: Whether to force synchronization (ignore dirty flag optimization)

        Returns:
            Messages: The updated Messages object

        Raises:
            SyncError: An error occurred during synchronization

        Note:
            1. Uses a lazy loading strategy: synchronization is performed only when the dirty flag is True or force=True
            2. Synchronization scope: Only updates the current Agent's mirror (self.messages[self.agent_name])
            3. Thread safety: Ensured by the locking mechanism inside context_manager
        """
        from dolphin.core.common.exceptions import SyncError

        agent_name = self.get_cur_agent_name() or "default"

        # Performance optimization: Check dirty flags
        if not force and not self.messages_dirty:
            return self.messages.get(agent_name, Messages())

        try:
            # 1. Obtain the authoritative, deduplicated, and policy-sorted final message list from context_manager
            llm_messages = self.context_manager.to_dph_messages()

            # 2. Get the current agent's image container (create one if it does not exist)
            if agent_name not in self.messages:
                self.messages[agent_name] = Messages()
            target_mirror = self.messages[agent_name]

            # 3. Update the image content in place, keeping references unchanged
            # Messages.set_messages() already exists (common.py line 366-368)
            target_mirror.set_messages(llm_messages)

            # 4. Clear dirty marks
            self.messages_dirty = False

            logger.debug(f"Synced messages for agent '{agent_name}': {len(llm_messages.get_messages())} messages")

            return target_mirror

        except Exception as e:
            logger.error(f"Failed to sync messages from context_manager: {e}")
            raise SyncError(f"Message synchronization failed: {e}") from e

    def get_messages(self):
        """Get the message mirror of the current Agent (auto-sync)"""
        agent_name = self.get_cur_agent_name()
        if agent_name is None:
            agent_name = "default"

        # Auto Sync
        self.sync_messages_from_llm_context()

        if agent_name not in self.messages:
            self.messages[agent_name] = Messages()

        return self.messages[agent_name]

    def get_messages_with_tool_calls(self):
        """Get all messages that have tool calls"""
        return self.get_messages().get_messages_with_tool_calls()

    def get_tool_response_messages(self):
        """Get all tool response messages"""
        return self.get_messages().get_tool_response_messages()

    # ============ Added: Unified message management convenience methods ============
    def add_user_message(self, content, bucket: str = None):
        """Add user message (unified interface)

        Args:
            content: Message content, can be:
                     - str: Plain text message
                     - List[Dict]: Multimodal content (e.g., [{"type": "text", "text": "..."}, {"type": "image_url", ...}])
            bucket: Bucket name, default is SCRATCHPAD

        Note:
            Only written to context_manager (single data source),
            Mirrors are synchronized on-demand via sync_messages_from_llm_context().
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SCRATCHPAD.value

        # Unique write path: added to context_manager
        messages = Messages()
        messages.add_message(content, MessageRole.USER)
        self.context_manager.add_bucket(bucket, messages)

        # Mark as dirty (remove double writing)
        self.messages_dirty = True

    def add_assistant_message(self, content: str, bucket: str = None):
        """Add assistant message (unified interface)

        Args:
            content: Message content
            bucket: Bucket name, default is SCRATCHPAD

        Note:
            Only written to context_manager (single data source),
            Mirrors are synchronized on-demand via sync_messages_from_llm_context().
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SCRATCHPAD.value

        # Unique write path: added to context_manager
        messages = Messages()
        messages.add_message(content, MessageRole.ASSISTANT)
        self.context_manager.add_bucket(bucket, messages)

        # Mark as dirty (remove double writing)
        self.messages_dirty = True

    def add_system_message(self, content: str, bucket: str = None):
        """Add system message (unified interface)

        Args:
            content: Message content
            bucket: Bucket name, default is SYSTEM

        Note:
            Only written to context_manager (single data source),
            Mirrors are synchronized on-demand via sync_messages_from_llm_context().
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SYSTEM.value

        messages = Messages()
        messages.add_message(content, MessageRole.SYSTEM)
        # If the corresponding bucket already exists, replace its content directly; otherwise, create a new bucket.
        if self.context_manager is not None:
            if bucket in self.context_manager.state.buckets:
                # Directly replace the content, avoid merging Messages again
                self.context_manager.replace_bucket_content(bucket, messages)
                # Mark the message mirror as dirty to ensure subsequent synchronization.
                self.messages_dirty = True
            else:
                # The initial creation still uses context_manager.add_bucket, with message_role set to SYSTEM
                self.context_manager.add_bucket(
                    bucket_name=bucket,
                    content=messages,
                    message_role=MessageRole.SYSTEM,
                )
                self.messages_dirty = True

    def add_tool_call_message_v2(self, content: str, tool_calls: list, bucket: str = None):
        """Add tool call messages (unified interface)

        Args:
            content: Message content
            tool_calls: List of tool calls
            bucket: Bucket name, default is SCRATCHPAD

        Note:
            Only write to context_manager (single data source),
            Mirrors are synchronized on-demand via sync_messages_from_llm_context().
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SCRATCHPAD.value

        # Unique write path: added to context_manager
        messages = Messages()
        messages.add_tool_call_message(content=content, tool_calls=tool_calls)
        self.context_manager.add_bucket(bucket, messages)

        # Mark as dirty (remove double writing)
        self.messages_dirty = True

    def add_tool_response_message_v2(self, content: str, tool_call_id: str, bucket: str = None):
        """Add tool response message (unified interface)

        Args:
            content: Message content
            tool_call_id: Tool call ID
            bucket: Bucket name, default is SCRATCHPAD

        Note:
            Only write to context_manager (single data source),
            Mirrors are synchronized on-demand via sync_messages_from_llm_context().
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SCRATCHPAD.value

        # Unique write path: added to context_manager
        messages = Messages()
        messages.add_tool_response_message(content=content, tool_call_id=tool_call_id)
        self.context_manager.add_bucket(bucket, messages)

        # Mark as dirty (remove double writing)
        self.messages_dirty = True

    def set_messages_batch(self, messages: Messages, bucket: str = None):
        """Batch set messages (uniform interface)
                Used to restore the previous messages state

        Args:
            messages: Messages object
            bucket: bucket name, default is SCRATCHPAD
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if bucket is None:
            bucket = BuildInBucket.SCRATCHPAD.value

        # Replace bucket content (or create if not exists)
        if self.context_manager.has_bucket(bucket):
            # Use replace_bucket_content to directly replace existing bucket
            self.context_manager.replace_bucket_content(bucket, messages)
        else:
            # Create new bucket if it doesn't exist
            self.context_manager.add_bucket(bucket, messages)

        # Mark as dirty
        self.messages_dirty = True

    def set_history_bucket(self, messages: Messages):
        """Set or override the content of the history bucket to always remain consistent with the history snapshot in the variable pool.

        Args:
            messages: Normalized historical messages (Messages)
        """
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        if not self.context_manager:
            return

        bucket_name = BuildInBucket.HISTORY.value

        # If the bucket already exists, directly replace the content to avoid duplicate merge at the Messages level
        if bucket_name in self.context_manager.state.buckets:
            self.context_manager.replace_bucket_content(bucket_name, messages)
            self.messages_dirty = True
        else:
            # First created, unified through add_bucket to maintain consistent configuration
            self.add_bucket(
                bucket_name=bucket_name,
                content=messages,
                message_role=MessageRole.USER,
            )

    def add_bucket(
        self,
        bucket_name: str,
        content: Union[str, Messages],
        priority: float = 1.0,
        allocated_tokens: Optional[int] = None,
        message_role: Optional[MessageRole] = None,
    ) -> None:
        """Unified bucket addition interface (wraps context_manager.add_bucket)

                This is the recommended way to add a bucket, automatically handling the messages_dirty flag.
                External direct calls to self.context_manager.add_bucket() are prohibited.

        Args:
            bucket_name: Bucket name
            content: Content, supports string or Messages type
            priority: Priority
            allocated_tokens: Number of allocated tokens
            message_role: Message role

        Note:
            This method ensures the messages_dirty flag is correctly set,
            guaranteeing the message synchronization mechanism works properly.
        """
        self.context_manager.add_bucket(
            bucket_name=bucket_name,
            content=content,
            priority=priority,
            allocated_tokens=allocated_tokens,
            message_role=message_role,
        )
        # Automatically mark as dirty to ensure message synchronization
        self.messages_dirty = True

    # ============ End: Unified Message Management Convenience Methods ============

    async def update_usage(self, final_chunk):
        if not self.get_var_value("usage"):
            default_uasge = {
                "prompt_tokens": 0,
                "total_tokens": 0,
                "completion_tokens": 0,
            }
            self.set_variable("usage", default_uasge)

        if not hasattr(final_chunk, "usage") or (
            hasattr(final_chunk, "usage") and not final_chunk.usage
        ):
            return

        try:
            usage = (
                final_chunk.usage if final_chunk.usage 
                else (final_chunk.choices[0].usage if final_chunk.choices else None)
            )  # SDK after AD packaging and DeepSeek native interface
        except:
            usage = (
                final_chunk["usage"]
                if final_chunk.get("usage", 0)
                else (final_chunk["choices"][0]["usage"] if final_chunk.get("choices") and len(final_chunk["choices"]) > 0 else None)
            )  # Current API request method for obtaining usage
        # If usage information cannot be obtained, return directly.
        if usage is None:
            return

        llm_tokens = self.get_var_value("usage")
        if llm_tokens is None:
            llm_tokens = {
                "prompt_tokens": 0,
                "total_tokens": 0,
                "completion_tokens": 0,
            }

        if isinstance(usage, dict):
            llm_tokens["prompt_tokens"] += usage.get("prompt_tokens", 0)
            llm_tokens["total_tokens"] += usage.get("total_tokens", 0)
            llm_tokens["completion_tokens"] += usage.get("completion_tokens", 0)
        else:
            llm_tokens["prompt_tokens"] += usage.prompt_tokens
            llm_tokens["total_tokens"] += usage.total_tokens
            llm_tokens["completion_tokens"] += usage.completion_tokens
        self.set_variable("usage", llm_tokens)

    def get_runtime_graph(self):
        return self.runtime_graph

    def set_last_model_name(self, model_name: str):
        """
        Set the last used model name.
        This should be called when making LLM calls to maintain model consistency across multiple rounds.

        Args:
            model_name: The model name to store
        """
        if model_name:
            self._last_model_name = model_name

    def get_last_model_name(self) -> Optional[str]:
        """
        Get the last used model name.
        This is useful for maintaining model consistency across multiple rounds of conversation.

        Returns:
            Optional[str]: The model name if found, None otherwise
        """
        return self._last_model_name

    def set_last_skills(self, skills: Optional[List[str]]):
        """
        Set the last used skills configuration.
        This should be called when executing explore blocks to maintain skills consistency across multiple rounds.

        Args:
            skills: The skills list to store (can be None to clear)
        """
        self._last_skills = skills

    def get_last_skills(self) -> Optional[List[str]]:
        """
        Get the last used skills configuration.
        This is useful for maintaining skills consistency across multiple rounds of conversation.

        Returns:
            Optional[List[str]]: The skills list if found, None otherwise
        """
        return self._last_skills

    def set_last_explore_mode(self, mode: Optional[str]):
        """
        Set the last used explore mode.
        This should be called when executing explore blocks to maintain mode consistency across multiple rounds.

        Args:
            mode: The explore mode to store ('prompt' or 'tool_call', can be None to clear)
        """
        self._last_explore_mode = mode

    def get_last_explore_mode(self) -> Optional[str]:
        """
        Get the last used explore mode.
        This is useful for maintaining mode consistency across multiple rounds of conversation.

        Returns:
            Optional[str]: The explore mode if found ('prompt' or 'tool_call'), None otherwise
        """
        return self._last_explore_mode

    def set_last_system_prompt(self, system_prompt: str):
        """
        Set the last used system prompt.
        This is useful for restoring the _system bucket during multi-turn conversations (e.g., continue_exploration).

        Args:
            system_prompt: The system prompt to store
        """
        if system_prompt and str(system_prompt).strip():
            self._last_system_prompt = str(system_prompt)

    def get_last_system_prompt(self) -> Optional[str]:
        """
        Get the last used system prompt.

        Returns:
            Optional[str]: The system prompt if found, otherwise None
        """
        return self._last_system_prompt

    def get_execution_trace(self, title=None) -> Dict[str, Any]:
        """Generate and return runtime execution trace information (Execution Trace)

                The execution trace records the complete execution flow of the Agent, including:
                - Execution order and duration of each code block
                - LLM call details (input/output tokens, model, etc.)
                - Variable changes and state transitions

        Args:
            title (str, optional): Trace title. If not provided, a default title is used.

        Returns:
            Dict[str, Any]: Execution trace information containing call_chain and LLM details
        """
        return self.runtime_graph.profile(title or "")

    # Backward compatibility: retain old method names
    def get_profile(self, title=None):
        """[Deprecated] Please use get_execution_trace() instead"""
        import warnings
        warnings.warn("get_profile() 已废弃，请使用 get_execution_trace()", DeprecationWarning, stacklevel=2)
        return self.get_execution_trace(title)

    def get_snapshot_analysis(self, title=None, format='markdown', options=None):
        """Generate and return a visualization analysis report for ContextSnapshot (Snapshot Analysis)

                Snapshot analysis creates a snapshot of the current context and generates a detailed analysis report, including:
                - Message statistics (bucketed by role, size, type)
                - Variable statistics (bucketed by type, size, namespace)
                - Memory usage analysis (original size, compressed size, compression ratio)
                - Optimization suggestions

        Args:
            title (str, optional): Title of the analysis report
            format (str): Output format, either 'markdown' or 'json'
            options (dict, optional): Configuration options, including thresholds, rendering options, etc.

        Returns:
            str or dict: Markdown-formatted report (if format='markdown') or JSON-formatted data (if format='json')

        Examples:
            # Get Markdown report
            analysis = context.get_snapshot_analysis(title="Step 5 Analysis")
            print(analysis)

                    # Get JSON data
            analysis_data = context.get_snapshot_analysis(format='json')
            print(f"Compression: {analysis_data['compression_ratio']:.1%}")
        """
        # Create Snapshot
        snapshot = self.export_runtime_state(frame_id="analysis_snapshot")

        # Generate analysis report
        return snapshot.profile(format=format, title=title, options=options)

    def save_trajectory(
        self,
        agent_name: str = "main",
        trajectory_path: Optional[str] = None,
        force_save: bool = False,
        pretty_format: bool = False,
        stage: Optional[str] = None,
    ):
        """
        Save dialog messages to file (legacy/simple mode).

        Note: Stage-based trajectory saving is now handled by the Trajectory class.
        This method delegates to Trajectory.save_simple() for consistency.

        Args:
            agent_name: The agent name, defaults to "main"
            trajectory_path: Custom trajectory path
            force_save: Force save even if memory is not enabled
            pretty_format: Save in pretty formatted text instead of JSON
            stage: [Deprecated] Use context.trajectory.finalize_stage()
        """
        # Stage-based saving should use Trajectory class
        if stage is not None:
            logger.warning(
                "Stage-based trajectory saving via save_trajectory() is deprecated. "
                "Use context.trajectory.finalize_stage() instead."
            )
            return

        if not (force_save or (self.config and self.config.memory_config and self.config.memory_config.enabled)):
            return

        # Determine trajectory file path
        if not trajectory_path:
            current_date = datetime.now().strftime("%Y%m%d%H%M")
            dialog_base_path = (
                getattr(self.config.memory_config, "dialog_path", "data/dialog/")
                if self.config and self.config.memory_config
                else "data/dialog/"
            )
            user_id = self.user_id or "_default_user_"
            dialog_dir = f"{dialog_base_path}{agent_name}/user_{user_id}"
            trajectory_path = f"{dialog_dir}/dialog_{current_date}.json"
            os.makedirs(dialog_dir, exist_ok=True)

        # Delegate to Trajectory class for actual saving
        Trajectory.save_simple(
            messages=self.get_messages().get_messages(),
            tools=self.skillkit.getSkillsSchema(),
            file_path=trajectory_path,
            pretty_format=pretty_format,
            user_id=self.user_id
        )

    def info(self, log_str):
        logger.info(self._make_log(log_str))

    def debug(self, log_str):
        logger.debug(self._make_log(log_str))

    def warn(self, log_str):
        logger.warning(self._make_log(log_str))

    def error(self, log_str):
        logger.error(self._make_log(log_str))

    def _calc_all_skills(self):
        """
        Calculate all skills
        """
        self.all_skills = Skillset()

        # Add skills from self.skillkit
        if self.skillkit and not self.skillkit.isEmpty():
            self.all_skills.addSkillkit(self.skillkit)

        # Add skills from global_skills
        if self.global_skills is not None:
            self.all_skills.addSkillkit(self.global_skills.getAllSkills())

    def _make_log(self, log_str):
        if len(log_str) < MAX_LOG_LENGTH:
            return "session[{}] {}".format(
                self.session_id, log_str.replace("\n", "\\n")
            )
        else:
            log_str = (
                log_str[: int(MAX_LOG_LENGTH * 1 / 3)]
                + "..."
                + log_str[-int(MAX_LOG_LENGTH * 2 / 3) :]
            )
            return "session[{}] {}".format(
                self.session_id, log_str.replace("\n", "\\n")
            )

    def _export_context_manager_state(self) -> Dict[str, Any]:
        """Export the complete state of context_manager

        Returns:
            A dictionary containing information about all buckets
        """
        buckets_state = []

        for bucket_name, bucket in self.context_manager.state.buckets.items():
            # Serializing ContextBucket
            bucket_data = {
                "name": bucket_name,
                "priority": bucket.priority,
                "allocated_tokens": bucket.allocated_tokens,
                "message_role": bucket.message_role.value,
                "is_compressed": bucket.is_compressed,
                "messages": []
            }

            # Extract message content
            if isinstance(bucket.content, Messages):
                for msg in bucket.content.get_messages():
                    bucket_data["messages"].append({
                        "role": msg.role.value,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "user_id": msg.user_id,
                        "tool_calls": msg.tool_calls,
                        "tool_call_id": msg.tool_call_id,
                        "metadata": msg.metadata,
                    })
            elif isinstance(bucket.content, str):
                # If it is a string type, save as a single message
                bucket_data["messages"].append({
                    "role": bucket.message_role.value,
                    "content": bucket.content,
                    "timestamp": None,
                    "user_id": "",
                    "tool_calls": None,
                    "tool_call_id": None,
                    "metadata": {},
                })

            buckets_state.append(bucket_data)

        return {
            "buckets": buckets_state,
            "layout_policy": self.context_manager.state.layout_policy,
            "bucket_order": self.context_manager.state.bucket_order,
            "total_tokens": self.context_manager.state.total_tokens,
        }

    def export_runtime_state(self, frame_id: str) -> "ContextSnapshot":
        """Export runtime state as a snapshot"""
        from dolphin.core.coroutine.context_snapshot import ContextSnapshot

        # Ensure the image is up to date
        self.sync_messages_from_llm_context(force=True)

        # Export variable state
        variables = {}
        for name, var_obj in self.variable_pool.get_all_variables().items():
            if isinstance(var_obj, VarOutput):
                # VarOutput knows how to serialize itself into a dict
                variables[name] = var_obj.to_dict()
            elif isinstance(var_obj, Var):
                # It's a simple Var wrapper. We only want to store the value.
                value = var_obj.value
                if isinstance(value, Messages):
                    # This is the problematic type. Serialize it.
                    variables[name] = value.to_dict()
                else:
                    # Assume other values are primitives and store them directly.
                    variables[name] = value
            # This case is for values stored in the pool without a Var wrapper.
            elif isinstance(var_obj, Messages):
                variables[name] = var_obj.get_messages_as_dict()
            else:
                variables[name] = var_obj

        # Export message history (export from the synchronized mirror)
        messages = []
        for agent_name, agent_messages in self.messages.items():
            for msg in agent_messages.get_messages():
                messages.append(
                    {
                        "agent": agent_name,
                        "role": msg.role.value,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "user_id": msg.user_id,
                        "tool_calls": msg.tool_calls,
                        "tool_call_id": msg.tool_call_id,
                        "metadata": msg.metadata,
                    }
                )

        # Export runtime state
        runtime_state = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "cur_agent": self.cur_agent.getName() if self.cur_agent else None,
            "max_answer_len": self.max_answer_len,
            "plan_enabled": self._plan_enabled,
            "plan_id": self._plan_id,
            "task_registry": self.task_registry.to_dict() if self.task_registry else None,
            "nesting_level": self._nesting_level,
        }

        # Export skill set status
        skillkit_state = {}
        if self.skillkit and not self.skillkit.isEmpty():
            try:
                skillkit_state = {
                    "skills_schema": self.skillkit.getSkillsSchema(),
                    "skill_count": len(self.skillkit.getSkills()),
                }
            except Exception as e:
                logger.warning(f"Failed to export skillkit state: {e}")

        # Export the complete state of context_manager (including bucket structure)
        context_manager_state = self._export_context_manager_state()
        return ContextSnapshot.create_snapshot(
            frame_id=frame_id,
            variables=variables,
            messages=messages,
            runtime_state=runtime_state,
            skillkit_state=skillkit_state,
            context_manager_state=context_manager_state,
        )

    def apply_runtime_state(self, snapshot: "ContextSnapshot"):
        """Restore runtime state from snapshot"""
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        # Restore variable state
        self.variable_pool.clear()
        for name, value in snapshot.variables.items():
            # Support restoring VarOutput structure from snapshot
            try:
                from dolphin.core.context.var_output import VarOutput

                if VarOutput.is_serialized_dict(value):
                    # This is the serialized structure of VarOutput
                    self.variable_pool.set_var(name, VarOutput.from_dict(value))
                else:
                    # Other simple types are restored by value
                    self.variable_pool.set_var(name, value)
            except Exception:
                # Fallback: Set to original value to avoid execution interruption due to restore failure
                self.variable_pool.set_var(name, value)

        # Restore message history to context_manager (single data source)
        self.context_manager.state.buckets.clear()

        # Check if there is a complete context_manager_state (new version snapshot)
        # Note: Even if buckets is an empty list, use the new version restore logic as long as context_manager_state exists
        # Full restoration: Reconstruct the complete bucket structure from context_manager_state
        bucket_count = len(snapshot.context_manager_state.get('buckets', []))
        logger.info(f"Restoring {bucket_count} buckets from context_manager_state")

        for bucket_data in snapshot.context_manager_state['buckets']:
            # Reconstruct Messages object
            messages = Messages()
            for msg_data in bucket_data['messages']:
                messages.append_message(
                    role=MessageRole(msg_data['role']),
                    content=msg_data['content'],
                    user_id=msg_data.get('user_id', ''),
                    tool_calls=msg_data.get('tool_calls'),
                    tool_call_id=msg_data.get('tool_call_id'),
                    metadata=msg_data.get('metadata', {}),
                )

            # Reconstruct ContextBucket (preserving original priority and other attributes)
            if messages.get_messages():  # Only add non-empty messages
                self.context_manager.add_bucket(
                    bucket_name=bucket_data['name'],
                    content=messages,
                    priority=bucket_data['priority'],
                    allocated_tokens=bucket_data['allocated_tokens'],
                    message_role=MessageRole(bucket_data['message_role']),
                )

        # Restore bucket_order and layout_policy
        self.context_manager.state.bucket_order = snapshot.context_manager_state.get('bucket_order', [])
        self.context_manager.state.layout_policy = snapshot.context_manager_state.get('layout_policy', 'default')

        logger.info("Successfully restored complete bucket structure from snapshot")

        # Synchronize from context_manager to mirror (ensure symmetry)
        self.messages.clear()
        self.messages_dirty = True  # Force Synchronization
        self.sync_messages_from_llm_context(force=True)

        # Resume runtime state
        runtime_state = snapshot.runtime_state
        if runtime_state:
            self.user_id = runtime_state.get("user_id")
            self.session_id = runtime_state.get("session_id")
            self.max_answer_len = runtime_state.get(
                "max_answer_len", MAX_ANSWER_CONTENT_LENGTH
            )

            # Restore plan state
            self._plan_enabled = runtime_state.get("plan_enabled", False)
            self._plan_id = runtime_state.get("plan_id")
            
            task_registry_data = runtime_state.get("task_registry")
            if task_registry_data:
                from dolphin.core.task_registry import TaskRegistry
                self.task_registry = TaskRegistry.from_dict(task_registry_data)
            else:
                self.task_registry = None

            self._nesting_level = runtime_state.get("nesting_level", 0)

            # Resume the current agent (to be handled in the calling function above)
            # The restoration of self.cur_agent requires external coordination

        # Verify recovery results
        bucket_count = len(self.context_manager.state.buckets)
        total_messages = sum(
            len(bucket.content.get_messages()) if isinstance(bucket.content, Messages) else 1
            for bucket in self.context_manager.state.buckets.values()
        )

        logger.info(
            f"Restored context state from snapshot {snapshot.snapshot_id}: "
            f"{bucket_count} buckets, {total_messages} total messages, "
            f"schema_version={snapshot.schema_version}"
        )

    # === User Interrupt API ===

    def set_interrupt_event(self, interrupt_event: asyncio.Event) -> None:
        """Set the user interrupt event (injected by Agent layer).

        Args:
            interrupt_event: asyncio.Event that will be set when user requests interrupt
        """
        self._interrupt_event = interrupt_event

    def get_interrupt_event(self) -> Optional[asyncio.Event]:
        """Get the user interrupt event.

        Returns:
            The interrupt event, or None if not set
        """
        return self._interrupt_event

    def is_interrupted(self) -> bool:
        """Check if user has requested an interrupt.

        Returns:
            True if interrupt event is set, False otherwise
        """
        return self._interrupt_event is not None and self._interrupt_event.is_set()

    def check_user_interrupt(self) -> None:
        """Check user interrupt status and raise exception if interrupted.

        This is the primary checkpoint method to be called at strategic locations
        during execution (e.g., LLM streaming loop, before skill execution).

        Raises:
            UserInterrupt: If user has requested interrupt
        """
        if self.is_interrupted():
            from dolphin.core.common.exceptions import UserInterrupt
            raise UserInterrupt("User interrupted execution")

    def clear_interrupt(self) -> None:
        """Clear the interrupt status (called when resuming execution)."""
        if self._interrupt_event is not None:
            self._interrupt_event.clear()

    # === Output Events API ===

    def write_output(self, event_type: "str | OutputEventType", data: Dict[str, Any]) -> None:
        """Record an output event for UI/SDK consumers.

        Args:
            event_type: Event type (OutputEventType enum or string for backward compatibility)
            data: Event payload data

        Notes:
            - This is an in-memory buffer only (process-local).
            - Consumers can call drain_output_events() to fetch and clear.
            - Prefer using OutputEventType enum for type safety.
        """
        from dolphin.core.task_registry import OutputEventType

        # Convert enum to string for backward compatibility
        event_type_str = event_type.value if isinstance(event_type, OutputEventType) else event_type

        event = {
            "event_type": event_type_str,
            "data": data,
            "timestamp_ms": int(time.time() * 1000),
        }
        self._output_events.append(event)

    def drain_output_events(self) -> List[Dict[str, Any]]:
        """Drain and clear buffered output events."""
        events = list(self._output_events)
        self._output_events.clear()
        return events

    # === Plan Mode API ===

    async def enable_plan(
        self,
        plan_id: Optional[str] = None,
        cancel_timeout: float = 5.0,
        cancel_warning_threshold: float = 2.0
    ) -> None:
        """Enable plan mode (lazy initialization).

        This method can be called multiple times for replan scenarios.

        Args:
            plan_id: Optional plan identifier (auto-generated if not provided)
            cancel_timeout: Maximum time to wait for task cancellation (default: 5.0s)
            cancel_warning_threshold: Threshold to emit early warning to UI (default: 2.0s)

        Behavior:
            - First call: Creates TaskRegistry
            - Subsequent calls (replan): Generates new plan_id, resets TaskRegistry
        """
        import uuid
        from dolphin.core.task_registry import TaskRegistry

        if not self._plan_enabled:
            self._plan_enabled = True
            self.task_registry = TaskRegistry()
            logger.info("Plan mode enabled")
        else:
            # Replan: gracefully cancel running tasks
            if self.task_registry:
                # Send UI event: starting to cancel
                self.write_output("plan_replan_start", {
                    "plan_id": self._plan_id,
                    "message": "Cancelling previous plan tasks...",
                    "timeout": cancel_timeout,
                    "warning_threshold": cancel_warning_threshold
                })

                # Start cancellation with progress tracking
                cancel_start = time.time()
                warning_emitted = False

                # Cancel all running tasks (with graceful shutdown)
                # Use shorter timeout for initial attempt to prevent UI hang
                initial_timeout = min(cancel_warning_threshold, cancel_timeout)
                result = await self.task_registry.cancel_all_running(
                    timeout=initial_timeout,
                    force=False,
                )

                elapsed = time.time() - cancel_start

                # If some tasks are still running, emit warning and continue waiting
                if result["timeout"] > 0 and elapsed < cancel_timeout:
                    if not warning_emitted:
                        self.write_output("plan_replan_waiting", {
                            "plan_id": self._plan_id,
                            "message": f"Some tasks are taking longer to stop ({elapsed:.1f}s elapsed)...",
                            "elapsed": elapsed,
                            "total_timeout": cancel_timeout
                        })
                        warning_emitted = True

                    # Continue waiting for remaining tasks
                    remaining_timeout = cancel_timeout - elapsed
                    extra_result = await self.task_registry.cancel_all_running(
                        timeout=remaining_timeout
                    )
                    # Merge results
                    result["cancelled"] += extra_result["cancelled"]
                    result["timeout"] = extra_result["timeout"]
                    result["task_ids"] = extra_result["task_ids"]

                if result["cancelled"] > 0:
                    logger.info(f"Replan: cancelled {result['cancelled']} tasks")

                if result["timeout"] > 0:
                    logger.warning(
                        f"Replan: {result['timeout']} tasks did not respond to cancel within {cancel_timeout}s"
                    )

                # Reset registry (already waited, so no need for timeout again)
                await self.task_registry.reset(cancel_timeout=0)

                # Send UI event: cancellation complete
                self.write_output("plan_replan_complete", {
                    "old_plan_id": self._plan_id,
                    "cancelled": result["cancelled"],
                    "timeout": result["timeout"],
                    "elapsed": time.time() - cancel_start
                })

            logger.info("Plan mode replan triggered")

        self._plan_id = plan_id or str(uuid.uuid4())
        logger.debug(f"Plan ID: {self._plan_id}")

    async def disable_plan(self) -> None:
        """Disable plan mode and cleanup resources."""
        if self.task_registry:
            await self.task_registry.cancel_all_running()
            self.task_registry = None
        self._plan_enabled = False
        self._plan_id = None
        logger.info("Plan mode disabled")

    def is_plan_enabled(self) -> bool:
        """Check if plan mode is enabled.

        Returns:
            True if plan mode is enabled, False otherwise
        """
        return self._plan_enabled

    async def has_active_plan(self) -> bool:
        """Check if there is an active plan with non-terminal tasks.

        Returns:
            True if plan is enabled, has tasks, and not all tasks are done
        """
        if not self._plan_enabled:
            return False
        if not self.task_registry or not await self.task_registry.has_tasks():
            return False
        return not await self.task_registry.is_all_done()

    def get_plan_id(self) -> Optional[str]:
        """Get the current plan ID.

        Returns:
            Plan ID string, or None if plan mode is not enabled
        """
        return self._plan_id

    def fork(self, task_id: str) -> "COWContext":
        """Create a Copy-On-Write child context for subtask isolation.

        Args:
            task_id: Task identifier for the child context

        Returns:
            COWContext instance that isolates writes

        Raises:
            RuntimeError: If nesting level exceeds maximum allowed depth (3 levels)

        Note:
            Maximum nesting depth is enforced to prevent memory overflow from
            deeply nested subtasks (e.g., subtask creates subtask creates subtask...).
        """
        MAX_NESTING_LEVEL = 3

        if self._nesting_level >= MAX_NESTING_LEVEL:
            raise RuntimeError(
                f"Maximum subtask nesting depth ({MAX_NESTING_LEVEL}) exceeded. "
                f"Current level: {self._nesting_level}. "
                "Deeply nested subtasks can cause memory overflow. "
                "Consider flattening your task structure or breaking it into sequential steps."
            )

        from dolphin.core.context.cow_context import COWContext
        child = COWContext(self, task_id)
        child._nesting_level = self._nesting_level + 1
        return child
