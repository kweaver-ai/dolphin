from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable, List, Tuple, Dict, Optional

from dolphin.core.logging.logger import MaxLenLog
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.tool_matcher import ToolMatcher
from dolphin.core.logging.logger import get_logger

logger = get_logger("tool")


class ToolExecRecord:
    """Tool Execution Log"""

    def __init__(self, toolCall: Tuple[str, dict], tool: ToolFunction, result: Any):
        self.toolCall = toolCall
        self.tool = tool
        self.result = result

    def __str__(self) -> str:
        return f"toolCall: {self.toolCall}, tool: {self.tool}, result: {self.result[:MaxLenLog]}"

    def get_tool_call(self) -> Tuple[str, dict]:
        return self.toolCall

    def get_tool(self) -> ToolFunction:
        return self.tool

    def get_result(self) -> Any:
        return self.result


class Toolkit:
    def __init__(self) -> None:
        self.records = []
        self.queryAsArg = False
        self._tools_cache: Optional[List[ToolFunction]] = None
        """Tool result processing strategy configuration. The strategies used must be registered strategies in StrategyRegistry.
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
        return "toolkit"

    # ─────────────────────────────────────────────────────────────
    # UI Rendering Protocol (Custom UI Support)
    # ─────────────────────────────────────────────────────────────

    def has_custom_ui(self, tool_name: str) -> bool:
        """Check if this toolkit provides custom UI rendering for a tool.

        Subclasses can override this to indicate that they provide
        custom UI rendering instead of the default tool_call box.

        Args:
            tool_name: Name of the tool being rendered

        Returns:
            True if custom UI is provided, False to use default rendering
        """
        return False

    def render_tool_start(
        self,
        tool_name: str,
        params: dict,
        verbose: bool = True
    ) -> None:
        """Custom UI rendering for tool start (before execution).

        Called instead of tool_call_start when has_custom_ui returns True.
        Subclasses should override to provide custom rendering.

        Args:
            tool_name: Name of the tool being called
            params: Parameters passed to the tool
            verbose: Whether to render UI
        """
        pass  # Default: no-op, subclasses implement

    def render_tool_end(
        self,
        tool_name: str,
        params: dict,
        result: Any,
        success: bool = True,
        duration_ms: float = 0,
        verbose: bool = True
    ) -> None:
        """Custom UI rendering for tool end (after execution).

        Called instead of tool_call_end when has_custom_ui returns True.
        Subclasses should override to provide custom rendering.

        Args:
            tool_name: Name of the tool that completed
            params: Parameters that were passed to the tool
            result: Result from the tool execution
            success: Whether the tool succeeded
            duration_ms: Execution duration in milliseconds
            verbose: Whether to render UI
        """
        pass  # Default: no-op, subclasses implement

    def _createTools(self) -> List[ToolFunction]:
        """Subclasses override this method to create the tool list.

        This is the template method pattern: subclasses implement tool creation,
        and the base class handles owner binding in getTools().

        Returns:
            List[ToolFunction]: List of tools created by this toolkit
        """
        return []

    def getTools(self) -> List[ToolFunction]:
        """Get the tool list with owner_toolkit automatically bound.

        This method caches the tools and ensures owner_toolkit is set
        for all tools. Subclasses should override _createTools() instead
        of this method.

        Returns:
            List[ToolFunction]: List of tools with owner_toolkit set
        """
        if self._tools_cache is None:
            self._tools_cache = self._createTools()
            self._bindOwnerToTools(self._tools_cache)
        return self._tools_cache

    def _bindOwnerToTools(self, tools: List[ToolFunction]) -> None:
        """Bind owner_toolkit to all tools that don't have one set.

        This passes the Toolkit object (self) so that metadata prompt
        can be collected dynamically via tool.owner_toolkit.get_metadata_prompt().
        """
        for tool in tools:
            if hasattr(tool, "set_owner_toolkit"):
                current_owner = getattr(tool, "get_owner_toolkit", lambda: None)()
                if current_owner is None:
                    tool.set_owner_toolkit(self)

    def invalidateToolsCache(self) -> None:
        """Invalidate the tools cache, forcing recreation on next getTools() call."""
        self._tools_cache = None

    def getResultProcessStrategyCfg(self) -> list[Dict[str, str]]:
        return self.result_process_strategy_cfg

    def setResultProcessStrategyCfg(
        self, result_process_strategy_cfg: list[Dict[str, str]]
    ) -> None:
        self.result_process_strategy_cfg = result_process_strategy_cfg

    def getToolNames(self) -> List[str]:
        return [tool.get_function_name() for tool in self.getTools()]

    def setGlobalConfig(self, globalConfig):
        self.globalConfig = globalConfig

    def getCertainTools(
        self, toolNames: List[str] | str | None
    ) -> List[ToolFunction]:
        if toolNames is None:
            return self.getTools()
        elif isinstance(toolNames, str):
            # Use ToolMatcher to support wildcard matching
            return ToolMatcher.filter_tools_by_pattern(self.getTools(), toolNames)
        else:
            # Use ToolMatcher to support wildcard matching
            return ToolMatcher.filter_tools_by_patterns(self.getTools(), toolNames)

    def hasTool(self, toolName: str) -> bool:
        return ToolMatcher.get_tool_by_name(self.getTools(), toolName) is not None

    def getTool(self, toolName: str) -> Optional[ToolFunction]:
        return ToolMatcher.get_tool_by_name(self.getTools(), toolName)

    @staticmethod
    def getToolsWithSingleTool(tool: Callable) -> List[ToolFunction]:
        return [ToolFunction(tool)]

    def getToolsSchema(self) -> list:
        return [tool.get_openai_tool_schema() for tool in self.getTools()]

    def getToolsSchemaForCertainTools(self, toolNames: List[str]) -> list:
        return [
            tool.get_openai_tool_schema()
            for tool in self.getCertainTools(toolNames)
        ]

    def getToolsDict(self) -> dict:
        return {tool.get_function_name(): tool for tool in self.getTools()}

    def getSchemas(self, toolNames: Optional[List[str]] = None) -> str:
        tools = self.getCertainTools(toolNames)
        functionSchemas = [
            json.dumps(tool.get_openai_tool_schema()["function"], ensure_ascii=False)
            for tool in tools
        ]
        return "|".join(functionSchemas)

    # =========================
    # Compression (generic)
    # =========================

    # Default rules for compressing tool-call messages; subclasses can override
    DEFAULT_COMPRESS_RULES: Dict[str, Dict[str, List[str]]] = {}

    def get_compress_rules(self) -> Dict[str, Dict[str, List[str]]]:
        """Return default compression rules for this toolkit instance."""
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
        Compress tool-call messages using include/exclude rules per tool name.

        Args:
            message: Raw message text containing markers like '=>#toolName:{...}'.
            rules: Per-tool rules, e.g. {"_cog_think": {"include": ["action"]}}
            marker_prefix: Prefix that denotes a tool-call marker.

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

        def apply_rule(tool_name: str, data: dict) -> tuple[dict, bool]:
            """Return (possibly_transformed_data, applied_flag)."""
            rule = active_rules.get(tool_name) or active_rules.get("*")
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

        # Regex to find markers and capture the tool name
        pattern = re.compile(re.escape(marker_prefix) + r"([A-Za-z0-9_]+):")

        idx = 0
        out_parts: List[str] = []
        for match in pattern.finditer(message):
            start, end = match.start(), match.end()
            tool_name = match.group(1)
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
                    transformed, applied = apply_rule(tool_name, data)
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

    def getToolsDescs(self) -> dict[str, str]:
        return {
            tool.get_function_name(): tool.get_function_description()
            for tool in self.getTools()
        }

    def getFormattedToolsDescription(self, format_type: str = "medium") -> str:
        """
        Get formatted tools description for LLM prompts

        Args:
            format_type (str): Format type - "concise", "medium", or "detailed"

        Returns:
            str: Formatted tools description
        """
        tools = self.getTools()
        if not tools:
            return "No tools available"

        if format_type.lower() == "concise":
            return self._formatToolsConcise(tools)
        elif format_type.lower() == "medium":
            return self._formatToolsMedium(tools)
        elif format_type.lower() == "detailed":
            return self._formatToolsDetailed(tools)
        else:
            return self._formatToolsMedium(tools)  # Default to medium format

    def _formatToolsConcise(self, tools: List[ToolFunction]) -> str:
        """
        Format tools in concise style: toolName - brief description
        """
        formatted_tools = []
        for tool in tools:
            name = tool.get_function_name()
            desc = tool.get_function_description()
            # Extract first sentence as brief description
            brief_desc = desc.split(".")[0] if desc else "Tool function"
            formatted_tools.append(f"- {name}: {brief_desc}")

        return "\n".join(formatted_tools)

    def _formatToolsMedium(self, tools: List[ToolFunction]) -> str:
        """
        Format tools in medium style: toolName(key_params) - description + purpose
        """
        formatted_tools = []
        for tool in tools:
            name = tool.get_function_name()
            desc = tool.get_function_description()

            # Extract key parameters from schema
            key_params = self._extractKeyParameters(tool)
            param_str = f"({key_params})" if key_params else ""

            # Format: toolName(params) - description
            formatted_tools.append(f"- {name}{param_str}: {desc}")

        return "\n".join(formatted_tools)

    def _formatToolsDetailed(self, tools: List[ToolFunction]) -> str:
        """
        Format tools in detailed style: full schema with parameters and types
        """
        formatted_tools = []
        for tool in tools:
            name = tool.get_function_name()
            desc = tool.get_function_description()

            # Get parameter details from schema
            param_details = self._extractParameterDetails(tool)

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

    def _extractKeyParameters(self, tool: ToolFunction) -> str:
        """
        Extract key parameters from tool schema for medium format
        """
        try:
            schema = tool.get_openai_tool_schema()
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

    def _extractParameterDetails(self, tool: ToolFunction) -> List[str]:
        """
        Extract detailed parameter information for detailed format
        """
        try:
            schema = tool.get_openai_tool_schema()
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
        for resource/guidance type toolkits that need to expose
        available resources to the LLM upfront.

        By default, returns an empty string (no metadata injection).

        Returns:
            Markdown string to append to system prompt, or empty string
            if no metadata injection is needed.
        """
        return ""

    @staticmethod
    def collect_metadata_from_tools(toolkit: "Toolkit") -> str:
        """Collect metadata prompts from a toolkit via tool.owner_toolkit.

        This static method traverses all tools in the given toolkit and
        collects metadata prompts from their owner toolkits. Only toolkits
        that override get_metadata_prompt() (like ResourceToolkit) will
        return non-empty metadata.

        This is the central utility for metadata collection, used by
        ExploreStrategy and ExploreBlockV2 to inject metadata into system prompt.

        Args:
            toolkit: The toolkit containing tools to inspect

        Returns:
            Combined metadata prompts separated by double newlines,
            or empty string if none
        """
        if toolkit is None:
            return ""

        # Safely get tools list, handling various toolkit implementations
        try:
            tools = toolkit.getTools() if hasattr(toolkit, 'getTools') else []
            if not tools:
                return ""
        except Exception:
            return ""

        seen_toolkit_ids = set()
        prompts = []

        for tool in tools:
            owner = getattr(tool, 'owner_toolkit', None)
            if owner is None:
                continue

            owner_id = id(owner)
            if owner_id in seen_toolkit_ids:
                continue
            seen_toolkit_ids.add(owner_id)

            if hasattr(owner, 'get_metadata_prompt'):
                try:
                    prompt = owner.get_metadata_prompt()
                    if prompt:
                        prompts.append(prompt)
                except Exception:
                    pass

        return "\n\n".join(prompts)

    def isEmpty(self) -> bool:
        return len(self.getTools()) == 0

    def isQueryAsArg(self) -> bool:
        return self.queryAsArg

    def _logAndCreateRecord(
        self, toolName: str, kwargs: dict, tool: ToolFunction, result: Any
    ) -> ToolExecRecord:
        """Log execution result and create ToolExecRecord"""
        if result is None:
            raise ValueError(f"funcCall func[{toolName}] result[{result}]")

        logger.info(f"funcCall func[{toolName}] result[{str(result)[:MaxLenLog]}]")
        return ToolExecRecord((toolName, kwargs), tool, result)

    def exec(self, toolName: str, **kwargs) -> ToolExecRecord:
        tool = self.getTool(toolName)
        if tool is None:
            raise ValueError(f"tool[{toolName}] not found")

        result = self.run(tool, **kwargs)
        return self._logAndCreateRecord(toolName, kwargs, tool, result)

    async def aexec(self, toolName: str, **kwargs) -> ToolExecRecord:
        """
        Execute a tool by name (async version)

        Args:
            toolName: Name of the tool to execute
            **kwargs: Arguments to pass to the tool

        Returns:
            ToolExecRecord containing execution results
        """
        tool = self.getTool(toolName)
        if tool is None:
            raise ValueError(f"tool[{toolName}] not found")

        # Execute the function directly for better performance
        if not hasattr(tool, "func"):
            raise ValueError(
                f"Expected ToolFunction object with 'func' attribute, got {type(tool)}"
            )

        if inspect.iscoroutinefunction(tool.func):
            result = await tool.func(**kwargs)
        else:
            result = tool.func(**kwargs)

        return self._logAndCreateRecord(toolName, kwargs, tool, result)

    @staticmethod
    def run(func: ToolFunction, **kwargs):
        # Check if the function is async and handle accordingly
        if inspect.iscoroutinefunction(func.func):
            # Handle async function in sync context
            try:
                # Try to get the current event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an event loop, we need to handle this specially
                    # This is typically for MCP tools that need to run in event loop context

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
                                f"Async tool function timeout after {timeout}s"
                            )
                        time.sleep(0.01)  # Small sleep to avoid busy waiting

                    # Get the result
                    if future.cancelled():
                        raise asyncio.CancelledError(
                            "Async tool function was cancelled"
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
    async def arun(tool: ToolFunction, tool_params: Optional[dict] = None, **kwargs):
        """
        Execute a ToolFunction tool and yield results as an async generator

        Args:
            tool: ToolFunction object to execute
            **kwargs: Arguments to pass to the function

        Yields:
            Execution results from the function
        """
        if not hasattr(tool, "func"):
            raise ValueError(
                f"Expected ToolFunction object with 'func' attribute, got {type(tool)}"
            )

        # Helper to check interrupt from kwargs
        def check_interrupt():
            props = kwargs.get("props")
            if props and "gvp" in props:
                ctx = props["gvp"]
                if hasattr(ctx, "check_user_interrupt"):
                    ctx.check_user_interrupt()

        check_interrupt()

        merged_params = {**tool_params} if tool_params else {}
        merged_params.update(kwargs)

        if inspect.isasyncgenfunction(tool.func):
            # For async generator functions, yield each result
            async for result in tool.func(**merged_params):
                check_interrupt()
                yield result

        elif inspect.iscoroutinefunction(tool.func):
            # For regular async functions, await and yield single result
            result = await tool.func(**merged_params)
            check_interrupt()
            yield result
        else:
            # Sync tool functions typically access the Context object which is
            # NOT thread-safe, so we call them directly in the event-loop thread
            # instead of offloading to a thread-pool executor.
            result = tool.func(**merged_params)
            check_interrupt()
            yield result
