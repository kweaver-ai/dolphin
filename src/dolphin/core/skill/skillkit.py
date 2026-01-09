from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable, List, Tuple, Dict, Optional

from dolphin.core.logging.logger import MaxLenLog
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skill_matcher import SkillMatcher
from dolphin.core.logging.logger import get_logger

logger = get_logger("skill")


class SkillExecRecord:
    """Skill Execution Log"""

    def __init__(self, toolCall: Tuple[str, dict], tool: SkillFunction, result: Any):
        self.toolCall = toolCall
        self.tool = tool
        self.result = result

    def __str__(self) -> str:
        return f"toolCall: {self.toolCall}, tool: {self.tool}, result: {self.result[:MaxLenLog]}"

    def get_tool_call(self) -> Tuple[str, dict]:
        return self.toolCall

    def get_tool(self) -> SkillFunction:
        return self.tool

    def get_result(self) -> Any:
        return self.result


class Skillkit:
    def __init__(self) -> None:
        self.records = []
        self.queryAsArg = False
        self._skills_cache: Optional[List[SkillFunction]] = None
        """Skill result processing strategy configuration. The strategies used must be registered strategies in StrategyRegistry.
                Example:
                [
                    {
                        "strategy": "summary",
                        "category": "llm",
                    },
                    {
                        "strategy": "preview",
                        "category": "app",
                    },
                ]
        """
        self.result_process_strategy_cfg: list[Dict[str, str]] = None

    def getName(self) -> str:
        return "skillkit"

    # ─────────────────────────────────────────────────────────────
    # UI Rendering Protocol (Custom UI Support)
    # ─────────────────────────────────────────────────────────────
    
    def has_custom_ui(self, skill_name: str) -> bool:
        """Check if this skillkit provides custom UI rendering for a skill.
        
        Subclasses can override this to indicate that they provide
        custom UI rendering instead of the default skill_call box.
        
        Args:
            skill_name: Name of the skill being rendered
            
        Returns:
            True if custom UI is provided, False to use default rendering
        """
        return False
    
    def render_skill_start(
        self,
        skill_name: str,
        params: dict,
        verbose: bool = True
    ) -> None:
        """Custom UI rendering for skill start (before execution).
        
        Called instead of skill_call_start when has_custom_ui returns True.
        Subclasses should override to provide custom rendering.
        
        Args:
            skill_name: Name of the skill being called
            params: Parameters passed to the skill
            verbose: Whether to render UI
        """
        pass  # Default: no-op, subclasses implement
    
    def render_skill_end(
        self,
        skill_name: str,
        params: dict,
        result: Any,
        success: bool = True,
        duration_ms: float = 0,
        verbose: bool = True
    ) -> None:
        """Custom UI rendering for skill end (after execution).
        
        Called instead of skill_call_end when has_custom_ui returns True.
        Subclasses should override to provide custom rendering.
        
        Args:
            skill_name: Name of the skill that completed
            params: Parameters that were passed to the skill
            result: Result from the skill execution
            success: Whether the skill succeeded
            duration_ms: Execution duration in milliseconds
            verbose: Whether to render UI
        """
        pass  # Default: no-op, subclasses implement

    def _createSkills(self) -> List[SkillFunction]:
        """Subclasses override this method to create the skill list.

        This is the template method pattern: subclasses implement skill creation,
        and the base class handles owner binding in getSkills().

        Returns:
            List[SkillFunction]: List of skills created by this skillkit
        """
        return []

    def getSkills(self) -> List[SkillFunction]:
        """Get the skill list with owner_skillkit automatically bound.

        This method caches the skills and ensures owner_skillkit is set
        for all skills. Subclasses should override _createSkills() instead
        of this method.

        Returns:
            List[SkillFunction]: List of skills with owner_skillkit set
        """
        if self._skills_cache is None:
            self._skills_cache = self._createSkills()
            self._bindOwnerToSkills(self._skills_cache)
        return self._skills_cache

    def _bindOwnerToSkills(self, skills: List[SkillFunction]) -> None:
        """Bind owner_skillkit to all skills that don't have one set.
        
        This passes the Skillkit object (self) so that metadata prompt
        can be collected dynamically via skill.owner_skillkit.get_metadata_prompt().
        """
        for skill in skills:
            if hasattr(skill, "set_owner_skillkit"):
                current_owner = getattr(skill, "get_owner_skillkit", lambda: None)()
                if current_owner is None:
                    skill.set_owner_skillkit(self)

    def invalidateSkillsCache(self) -> None:
        """Invalidate the skills cache, forcing recreation on next getSkills() call."""
        self._skills_cache = None

    def getResultProcessStrategyCfg(self) -> list[Dict[str, str]]:
        return self.result_process_strategy_cfg

    def setResultProcessStrategyCfg(
        self, result_process_strategy_cfg: list[Dict[str, str]]
    ) -> None:
        self.result_process_strategy_cfg = result_process_strategy_cfg

    def getSkillNames(self) -> List[str]:
        return [skill.get_function_name() for skill in self.getSkills()]

    def setGlobalConfig(self, globalConfig):
        self.globalConfig = globalConfig

    def getCertainSkills(
        self, skillNames: List[str] | str | None
    ) -> List[SkillFunction]:
        if skillNames is None:
            return self.getSkills()
        elif isinstance(skillNames, str):
            # Use SkillMatcher to support wildcard matching
            return SkillMatcher.filter_skills_by_pattern(self.getSkills(), skillNames)
        else:
            # Use SkillMatcher to support wildcard matching
            return SkillMatcher.filter_skills_by_patterns(self.getSkills(), skillNames)

    def hasSkill(self, skillName: str) -> bool:
        return SkillMatcher.get_skill_by_name(self.getSkills(), skillName) is not None

    def getSkill(self, skillName: str) -> Optional[SkillFunction]:
        return SkillMatcher.get_skill_by_name(self.getSkills(), skillName)

    @staticmethod
    def getSkillsWithSingleSkill(skill: Callable) -> List[SkillFunction]:
        return [SkillFunction(skill)]

    def getSkillsSchema(self) -> list:
        return [skill.get_openai_tool_schema() for skill in self.getSkills()]

    def getSkillsSchemaForCertainSkills(self, skillNames: List[str]) -> list:
        return [
            skill.get_openai_tool_schema()
            for skill in self.getCertainSkills(skillNames)
        ]

    def getSkillsDict(self) -> dict:
        return {skill.get_function_name(): skill for skill in self.getSkills()}

    def getSchemas(self, skillNames: Optional[List[str]] = None) -> str:
        skills = self.getCertainSkills(skillNames)
        functionSchemas = [
            json.dumps(skill.get_openai_tool_schema()["function"], ensure_ascii=False)
            for skill in skills
        ]
        return "|".join(functionSchemas)

    # =========================
    # Compression (generic)
    # =========================

    # Default rules for compressing skill-call messages; subclasses can override
    DEFAULT_COMPRESS_RULES: Dict[str, Dict[str, List[str]]] = {}

    def get_compress_rules(self) -> Dict[str, Dict[str, List[str]]]:
        """Return default compression rules for this skillkit instance."""
        return self.DEFAULT_COMPRESS_RULES

    @classmethod
    def set_default_compress_rules(cls, rules: Dict[str, Dict[str, List[str]]]):
        """Set default compression rules at class level."""
        cls.DEFAULT_COMPRESS_RULES = rules or {}

    @staticmethod
    def compress_message_with_rules(
        message: str,
        rules: Optional[Dict[str, Dict[str, List[str]]]] = None,
        marker_prefix: str = "=>#",
    ) -> str:
        """
        Compress skill-call messages using include/exclude rules per skill name.

        Args:
            message: Raw message text containing markers like '=>#skillName:{...}'.
            rules: Per-skill rules, e.g. {"_cog_think": {"include": ["action"]}}
            marker_prefix: Prefix that denotes a skill-call marker.

        Returns:
            Compressed message text.
        """
        import json
        import re
        from dolphin.core.utils.tools import (
            extract_json_from_response,
            safe_json_loads,
        )

        active_rules: Dict[str, Dict[str, List[str]]] = rules or {}

        def apply_rule(skill_name: str, data: dict) -> tuple[dict, bool]:
            """Return (possibly_transformed_data, applied_flag)."""
            rule = active_rules.get(skill_name) or active_rules.get("*")
            if not rule:
                return data, False
            include_fields = (
                rule.get("include") if isinstance(rule.get("include"), list) else []
            )
            exclude_fields = (
                rule.get("exclude") if isinstance(rule.get("exclude"), list) else []
            )
            if include_fields:
                return ({k: v for k, v in data.items() if k in include_fields}, True)
            if exclude_fields:
                return (
                    {k: v for k, v in data.items() if k not in exclude_fields},
                    True,
                )
            return data, False

        # Regex to find markers and capture the skill name
        pattern = re.compile(re.escape(marker_prefix) + r"([A-Za-z0-9_]+):")

        idx = 0
        out_parts: List[str] = []
        for match in pattern.finditer(message):
            start, end = match.start(), match.end()
            skill_name = match.group(1)
            # Append text before marker and the marker itself
            out_parts.append(message[idx:start])
            out_parts.append(message[start:end])

            # Locate JSON object starting after ':' using shared util
            brace_start = message.find("{", end)
            if brace_start == -1:
                idx = end
                continue

            json_text = extract_json_from_response(message[brace_start:])
            if not json_text or not json_text.startswith("{"):
                # Not a proper JSON, keep raw char and move one step
                out_parts.append(message[end : brace_start + 1])
                idx = brace_start + 1
                continue

            next_idx = brace_start + len(json_text)

            try:
                data = safe_json_loads(json_text, strict=False)
                if isinstance(data, dict):
                    transformed, applied = apply_rule(skill_name, data)
                    if applied:
                        out_parts.append(json.dumps(transformed, ensure_ascii=False))
                    else:
                        # No rule applied: keep original JSON text unchanged
                        out_parts.append(json_text)
                else:
                    # Non-dict payloads: keep original
                    out_parts.append(json_text)
            except Exception:
                out_parts.append(json_text)

            idx = next_idx

        out_parts.append(message[idx:])
        return "".join(out_parts)

    def getSkillsDescs(self) -> dict[str, str]:
        return {
            skill.get_function_name(): skill.get_function_description()
            for skill in self.getSkills()
        }

    def getFormattedToolsDescription(self, format_type: str = "medium") -> str:
        """
        Get formatted tools description for LLM prompts

        Args:
            format_type (str): Format type - "concise", "medium", or "detailed"

        Returns:
            str: Formatted tools description
        """
        skills = self.getSkills()
        if not skills:
            return "No tools available"

        if format_type.lower() == "concise":
            return self._formatToolsConcise(skills)
        elif format_type.lower() == "medium":
            return self._formatToolsMedium(skills)
        elif format_type.lower() == "detailed":
            return self._formatToolsDetailed(skills)
        else:
            return self._formatToolsMedium(skills)  # Default to medium format

    def _formatToolsConcise(self, skills: List[SkillFunction]) -> str:
        """
        Format tools in concise style: toolName - brief description
        """
        formatted_tools = []
        for skill in skills:
            name = skill.get_function_name()
            desc = skill.get_function_description()
            # Extract first sentence as brief description
            brief_desc = desc.split(".")[0] if desc else "Tool function"
            formatted_tools.append(f"- {name}: {brief_desc}")

        return "\n".join(formatted_tools)

    def _formatToolsMedium(self, skills: List[SkillFunction]) -> str:
        """
        Format tools in medium style: toolName(key_params) - description + purpose
        """
        formatted_tools = []
        for skill in skills:
            name = skill.get_function_name()
            desc = skill.get_function_description()

            # Extract key parameters from schema
            key_params = self._extractKeyParameters(skill)
            param_str = f"({key_params})" if key_params else ""

            # Format: toolName(params) - description
            formatted_tools.append(f"- {name}{param_str}: {desc}")

        return "\n".join(formatted_tools)

    def _formatToolsDetailed(self, skills: List[SkillFunction]) -> str:
        """
        Format tools in detailed style: full schema with parameters and types
        """
        formatted_tools = []
        for skill in skills:
            name = skill.get_function_name()
            desc = skill.get_function_description()

            # Get parameter details from schema
            param_details = self._extractParameterDetails(skill)

            tool_block = [f"**{name}**"]
            tool_block.append(f"  Description: {desc}")

            if param_details:
                tool_block.append("  Parameters:")
                for param_info in param_details:
                    tool_block.append(f"    - {param_info}")
            else:
                tool_block.append("  Parameters: None")

            formatted_tools.append("\n".join(tool_block))

        return "\n\n".join(formatted_tools)

    def _extractKeyParameters(self, skill: SkillFunction) -> str:
        """
        Extract key parameters from skill schema for medium format
        """
        try:
            schema = skill.get_openai_tool_schema()
            if "function" in schema and "parameters" in schema["function"]:
                params = schema["function"]["parameters"]
                if "properties" in params:
                    param_names = list(params["properties"].keys())
                    # Show first 3 key parameters
                    if len(param_names) <= 3:
                        return ", ".join(param_names)
                    else:
                        return ", ".join(param_names[:3]) + ", ..."
            return ""
        except Exception:
            return ""

    def _extractParameterDetails(self, skill: SkillFunction) -> List[str]:
        """
        Extract detailed parameter information for detailed format
        """
        try:
            schema = skill.get_openai_tool_schema()
            if "function" in schema and "parameters" in schema["function"]:
                params = schema["function"]["parameters"]
                if "properties" in params:
                    param_details = []
                    properties = params["properties"]
                    required = params.get("required", [])

                    for param_name, param_info in properties.items():
                        param_type = param_info.get("type", "any")
                        param_desc = param_info.get("description", "")
                        is_required = (
                            " (required)" if param_name in required else " (optional)"
                        )

                        param_line = f"{param_name} ({param_type}){is_required}"
                        if param_desc:
                            param_line += f": {param_desc}"
                        param_details.append(param_line)

                    return param_details
            return []
        except Exception:
            return []

    def getSessionId(
        self,
        session_id: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        # First try to get session_id directly
        if session_id:
            return session_id

        # Fallback to the original method via props/gvp
        if props:
            context = props.get("gvp")
            if context and hasattr(context, "get_session_id"):
                session_id = context.get_session_id()
        return session_id

    def get_metadata_prompt(self) -> str:
        """Return metadata prompt to inject into system prompt.

        Subclasses can override this to provide fixed metadata content
        that should be injected into the system prompt. This is useful
        for resource/guidance type skillkits that need to expose
        available resources to the LLM upfront.

        By default, returns an empty string (no metadata injection).

        Returns:
            Markdown string to append to system prompt, or empty string
            if no metadata injection is needed.
        """
        return ""

    @staticmethod
    def collect_metadata_from_skills(skillkit: "Skillkit") -> str:
        """Collect metadata prompts from a skillkit via skill.owner_skillkit.

        This static method traverses all skills in the given skillkit and
        collects metadata prompts from their owner skillkits. Only skillkits
        that override get_metadata_prompt() (like ResourceSkillkit) will
        return non-empty metadata.

        This is the central utility for metadata collection, used by
        ExploreStrategy and ExploreBlockV2 to inject metadata into system prompt.

        Args:
            skillkit: The skillkit containing skills to inspect

        Returns:
            Combined metadata prompts separated by double newlines,
            or empty string if none
        """
        if skillkit is None:
            return ""

        # Safely get skills list, handling various skillkit implementations
        try:
            skills = skillkit.getSkills() if hasattr(skillkit, 'getSkills') else []
            if not skills:
                return ""
        except Exception:
            return ""

        seen_skillkit_ids = set()
        prompts = []

        for skill in skills:
            owner = getattr(skill, 'owner_skillkit', None)
            if owner is None:
                continue

            owner_id = id(owner)
            if owner_id in seen_skillkit_ids:
                continue
            seen_skillkit_ids.add(owner_id)

            if hasattr(owner, 'get_metadata_prompt'):
                try:
                    prompt = owner.get_metadata_prompt()
                    if prompt:
                        prompts.append(prompt)
                except Exception:
                    pass

        return "\n\n".join(prompts)

    def isEmpty(self) -> bool:
        return len(self.getSkills()) == 0

    def isQueryAsArg(self) -> bool:
        return self.queryAsArg

    def _logAndCreateRecord(
        self, skillName: str, kwargs: dict, skill: SkillFunction, result: Any
    ) -> SkillExecRecord:
        """Log execution result and create SkillExecRecord"""
        if result is None:
            raise ValueError(f"funcCall func[{skillName}] result[{result}]")

        logger.info(f"funcCall func[{skillName}] result[{str(result)[:MaxLenLog]}]")
        return SkillExecRecord((skillName, kwargs), skill, result)

    def exec(self, skillName: str, **kwargs) -> SkillExecRecord:
        skill = self.getSkill(skillName)
        if skill is None:
            raise ValueError(f"skill[{skillName}] not found")

        result = self.run(skill, **kwargs)
        return self._logAndCreateRecord(skillName, kwargs, skill, result)

    async def aexec(self, skillName: str, **kwargs) -> SkillExecRecord:
        """
        Execute a skill by name (async version)

        Args:
            skillName: Name of the skill to execute
            **kwargs: Arguments to pass to the skill

        Returns:
            SkillExecRecord containing execution results
        """
        skill = self.getSkill(skillName)
        if skill is None:
            raise ValueError(f"skill[{skillName}] not found")

        # Execute the function directly for better performance
        if not hasattr(skill, "func"):
            raise ValueError(
                f"Expected SkillFunction object with 'func' attribute, got {type(skill)}"
            )

        if inspect.iscoroutinefunction(skill.func):
            result = await skill.func(**kwargs)
        else:
            result = skill.func(**kwargs)

        return self._logAndCreateRecord(skillName, kwargs, skill, result)

    @staticmethod
    def run(func: SkillFunction, **kwargs):
        # Check if the function is async and handle accordingly
        if inspect.iscoroutinefunction(func.func):
            # Handle async function in sync context
            try:
                # Try to get the current event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an event loop, we need to handle this specially
                    # This is typically for MCP skills that need to run in event loop context

                    # Create a task and wait for it using Future
                    future = asyncio.Future()

                    def on_task_complete(task):
                        try:
                            if task.cancelled():
                                future.set_exception(asyncio.CancelledError())
                            elif task.exception():
                                future.set_exception(task.exception())
                            else:
                                future.set_result(task.result())
                        except Exception as e:
                            future.set_exception(e)

                    # Schedule the async function as a task
                    task = loop.create_task(func.func(**kwargs))
                    task.add_done_callback(on_task_complete)

                    # Wait for the task to complete using a polling approach
                    import time

                    timeout = 30  # 30 second timeout
                    start_time = time.time()

                    while not future.done():
                        if time.time() - start_time > timeout:
                            task.cancel()
                            raise asyncio.TimeoutError(
                                f"Async skill function timeout after {timeout}s"
                            )
                        time.sleep(0.01)  # Small sleep to avoid busy waiting

                    # Get the result
                    if future.cancelled():
                        raise asyncio.CancelledError(
                            "Async skill function was cancelled"
                        )
                    elif future.exception():
                        raise future.exception()  # type: ignore
                    else:
                        return future.result()
                else:
                    return loop.run_until_complete(func.func(**kwargs))
            except RuntimeError:
                # No event loop, create a new one
                return asyncio.run(func.func(**kwargs))
        else:
            # Handle sync function directly
            return func.func(**kwargs)

    @staticmethod
    async def arun(skill: SkillFunction, skill_params: Optional[dict] = None, **kwargs):
        """
        Execute a SkillFunction skill and yield results as an async generator

        Args:
            skill: SkillFunction object to execute
            **kwargs: Arguments to pass to the function

        Yields:
            Execution results from the function
        """
        if not hasattr(skill, "func"):
            raise ValueError(
                f"Expected SkillFunction object with 'func' attribute, got {type(skill)}"
            )

        if inspect.isasyncgenfunction(skill.func):
            # For async generator functions, yield each result
            # Merge parameter dictionaries to avoid duplicate keyword arguments
            merged_params = {**skill_params} if skill_params else {}
            merged_params.update(kwargs)
            async for result in skill.func(**merged_params):
                yield result

        elif inspect.iscoroutinefunction(skill.func):
            # For regular async functions, await and yield single result
            # Merge parameter dictionaries to avoid duplicate keyword arguments
            merged_params = {**skill_params} if skill_params else {}
            merged_params.update(kwargs)
            result = await skill.func(**merged_params)
            yield result
        else:
            # Merge parameter dictionaries to avoid duplicate keyword arguments
            merged_params = {**skill_params} if skill_params else {}
            merged_params.update(kwargs)
            result = skill.func(**merged_params)
            yield result
