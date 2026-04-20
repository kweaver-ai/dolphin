"""Tool Name Matching Utility Class

Provides unified tool name matching logic, supporting wildcard matching and exact matching
"""

import fnmatch
from typing import Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.core.tool.tool_function import ToolFunction


class ToolMatcher:
    """Tool Name Matching Utility Class

        Supports the following matching patterns:
        - Exact match: "playwright_browser_navigate"
        - Wildcard match: "playwright*", "*_browser_*", "playwright_browser_*"
        - List match: ["playwright*", "_python"]
    """

    @staticmethod
    def match_tool_name(tool_name: str, pattern: str) -> bool:
        """Determine whether the tool name matches the specified pattern

        Args:
            tool_name (str): The tool name
            pattern (str): The matching pattern, supports wildcards

        Returns:
            bool: Whether it matches
        """
        return fnmatch.fnmatch(tool_name, pattern)

    @staticmethod
    def match_tool_names(tool_name: str, patterns: List[str]) -> bool:
        """Determine whether the tool name matches any one in the specified pattern list.

        Args:
            tool_name (str): The tool name
            patterns (List[str]): The list of matching patterns

        Returns:
            bool: Whether it matches any one pattern
        """
        return any(
            ToolMatcher.match_tool_name(tool_name, pattern) for pattern in patterns
        )

    @staticmethod
    def filter_tools_by_pattern(
        tools: List["ToolFunction"], pattern: str
    ) -> List["ToolFunction"]:
        """Filter a list of tools based on a single pattern

        Args:
            tools (List[ToolFunction]): List of tools
            pattern (str): Matching pattern

        Returns:
            List[ToolFunction]: Filtered list of tools
        """
        return [
            tool
            for tool in tools
            if ToolMatcher.match_tool_name(tool.get_function_name(), pattern)
        ]

    @staticmethod
    def filter_tools_by_patterns(
        tools: List["ToolFunction"], patterns: List[str]
    ) -> List["ToolFunction"]:
        """Filter the tool list based on multiple patterns

        Args:
            tools (List[ToolFunction]): List of tools
            patterns (List[str]): List of matching patterns

        Returns:
            List[ToolFunction]: Filtered list of tools
        """
        matched_tools = []
        for tool in tools:
            tool_name = tool.get_function_name()
            if ToolMatcher.match_tool_names(tool_name, patterns):
                matched_tools.append(tool)
        return matched_tools

    @staticmethod
    def find_first_matching_tool(
        tools: List["ToolFunction"], pattern: str
    ) -> Optional["ToolFunction"]:
        """Find the first tool that matches the specified pattern

        Args:
            tools (List[ToolFunction]): List of tools
            pattern (str): Matching pattern

        Returns:
            Optional[ToolFunction]: The first matching tool, or None if not found
        """
        for tool in tools:
            if ToolMatcher.match_tool_name(tool.get_function_name(), pattern):
                return tool
        return None

    @staticmethod
    def get_matching_tools(
        tools: List["ToolFunction"], tool_names: Optional[List[str]] = None
    ) -> List["ToolFunction"]:
        """Get tools matching the specified list of names

        Args:
            tools (List[ToolFunction]): List of tools
            tool_names (Optional[List[str]]): List of tool names, supports wildcards; None means return all tools

        Returns:
            List[ToolFunction]: List of matching tools
        """
        if tool_names is None:
            return tools

        return ToolMatcher.filter_tools_by_patterns(tools, tool_names)

    @staticmethod
    def get_matching_tools_by_names(
        tools: List["ToolFunction"], tool_names: List[str]
    ) -> List["ToolFunction"]:
        return [tool for tool in tools if tool.get_function_name() in tool_names]

    @staticmethod
    def get_tool_by_name(
        tools: List["ToolFunction"], tool_name: str
    ) -> Optional["ToolFunction"]:
        """Get a tool by its name, supporting wildcard matching.

        Args:
            tools (List[ToolFunction]): List of tools
            tool_name (str): Name of the tool, supports wildcards

        Returns:
            Optional[ToolFunction]: The matched tool, returns None if not found
        """
        return ToolMatcher.find_first_matching_tool(tools, tool_name)

    @staticmethod
    def get_owner_toolkits(tools: Iterable["ToolFunction"]) -> Set[str]:
        """Collect all known owner toolkit names from tools via owner_name property."""
        owners: Set[str] = set()
        for tool in tools:
            if hasattr(tool, "owner_name") and tool.owner_name:
                owners.add(tool.owner_name)
        return owners

    @staticmethod
    def split_namespaced_pattern(
        pattern: str, owner_names: Set[str]
    ) -> Tuple[Optional[str], str, bool]:
        """Split a pattern into optional <toolkit> namespace and the remaining tool-name pattern.

        Supported forms:
        - "<toolkit>": shorthand for "<toolkit>.*"
        - "<toolkit>.<pattern>": namespaced matching (tool owner must equal <toolkit>)
        - "<pattern>": non-namespaced matching (matches tool name directly)

        Notes:
        - If owner_names is empty, always treat as non-namespaced.
        - Uses longest owner prefix match to support owner names containing dots.
        """
        if not owner_names:
            return None, pattern, False

        if pattern in owner_names:
            return pattern, "*", True

        for owner in sorted(owner_names, key=len, reverse=True):
            prefix = owner + "."
            if pattern.startswith(prefix):
                suffix = pattern[len(prefix) :] or "*"
                return owner, suffix, True

        return None, pattern, False

    @staticmethod
    def match_tool(
        tool: "ToolFunction", pattern: str, owner_names: Optional[Set[str]] = None
    ) -> bool:
        """Match a tool against a (possibly namespaced) pattern."""
        owner_names = owner_names or set()
        owner, suffix, is_namespaced = ToolMatcher.split_namespaced_pattern(
            pattern, owner_names
        )
        if not is_namespaced:
            return ToolMatcher.match_tool_name(tool.get_function_name(), pattern)

        tool_owner = getattr(tool, "owner_name", None)
        return tool_owner == owner and ToolMatcher.match_tool_name(
            tool.get_function_name(), suffix
        )

    @staticmethod
    def match_tools_batch(
        tools: List["ToolFunction"],
        patterns: List[str],
        owner_names: Optional[Set[str]] = None,
    ) -> Tuple[List["ToolFunction"], bool]:
        """Batch match tools against multiple patterns.

        This method is optimized to:
        - Pre-parse all patterns once (avoid repeated split_namespaced_pattern calls)
        - Deduplicate matched tools (each tool appears at most once)
        - Track whether any namespaced pattern was used

        Args:
            tools: List of tools to match against
            patterns: List of patterns (plain or namespaced)
            owner_names: Set of known toolkit owner names

        Returns:
            Tuple of (matched_tools, any_namespaced_pattern)
        """
        owner_names = owner_names or set()

        # Pre-sort owner_names once for consistent longest-prefix matching
        sorted_owners = sorted(owner_names, key=len, reverse=True) if owner_names else []

        # Pre-parse all patterns
        parsed_patterns: List[Tuple[Optional[str], str, bool]] = []
        any_namespaced = False
        for pattern in patterns:
            owner, suffix, is_ns = ToolMatcher._split_namespaced_pattern_with_sorted_owners(
                pattern, owner_names, sorted_owners
            )
            parsed_patterns.append((owner, suffix, is_ns))
            any_namespaced = any_namespaced or is_ns

        # Match tools with deduplication
        matched: List["ToolFunction"] = []
        seen_ids: Set[int] = set()

        for tool in tools:
            tool_id = id(tool)
            if tool_id in seen_ids:
                continue

            tool_name = tool.get_function_name()
            tool_owner = getattr(tool, "owner_name", None)

            for owner, suffix, is_ns in parsed_patterns:
                if is_ns:
                    # Namespaced pattern: match owner and tool name
                    if tool_owner == owner and fnmatch.fnmatch(tool_name, suffix):
                        matched.append(tool)
                        seen_ids.add(tool_id)
                        break
                else:
                    # Plain pattern: match tool name only
                    if fnmatch.fnmatch(tool_name, suffix):
                        matched.append(tool)
                        seen_ids.add(tool_id)
                        break

        return matched, any_namespaced

    @staticmethod
    def _split_namespaced_pattern_with_sorted_owners(
        pattern: str, owner_names: Set[str], sorted_owners: List[str]
    ) -> Tuple[Optional[str], str, bool]:
        """Split pattern with pre-sorted owners (avoids repeated sorting)."""
        if not owner_names:
            return None, pattern, False

        if pattern in owner_names:
            return pattern, "*", True

        for owner in sorted_owners:
            prefix = owner + "."
            if pattern.startswith(prefix):
                suffix = pattern[len(prefix):] or "*"
                return owner, suffix, True

        return None, pattern, False
