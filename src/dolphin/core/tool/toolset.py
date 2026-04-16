from __future__ import annotations
from typing import Dict, List, Optional

from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.tool_matcher import ToolMatcher

from .toolkit import Toolkit


class ToolSet(Toolkit):
    """A container that aggregates tools from multiple toolkits.

    Unlike regular Toolkits that create tools via _createTools(),
    ToolSet dynamically collects tools from other toolkits.
    It overrides getTools() to return its managed collection directly,
    bypassing the base class caching mechanism.

    Note: Metadata prompt functionality is NOT handled here. It is collected
    dynamically via tool.owner_toolkit in ExploreStrategy._collect_metadata_prompt().
    """

    def __init__(self):
        super().__init__()
        self.tools: Dict[str, ToolFunction] = {}

    def merge(self, otherToolSet: ToolSet):
        self.tools.update(otherToolSet.tools)

    def addToolkit(self, toolkit: Toolkit):
        """Add all tools from a toolkit to this toolset.

        Tools are retrieved via toolkit.getTools(), which automatically
        binds owner_toolkit in the base Toolkit class. This binding is
        used by ExploreStrategy to collect metadata prompts dynamically.
        """
        for tool in toolkit.getTools():
            self.addTool(tool)

    def addTool(self, tool: ToolFunction):
        if tool.get_function_name() not in self.getToolNames():
            self.tools[tool.get_function_name()] = tool

    def getToolNames(self):
        return self.tools.keys()

    def getTools(self) -> List[ToolFunction]:
        """Return the aggregated tools directly.

        This overrides the base class implementation to return the
        dynamically managed tools collection without caching.
        Tools already have owner_toolkit bound from their source toolkits.
        """
        return list(self.tools.values())

    @staticmethod
    def createToolSet(
        globalToolSet: ToolSet, toolNames: Optional[List[str]] = None
    ):
        newToolSet = ToolSet()
        if toolNames is None:
            return globalToolSet

        # Get tools using wildcard matching with ToolMatcher
        matched_tools = ToolMatcher.get_matching_tools(
            globalToolSet.getTools(), toolNames
        )
        for tool in matched_tools:
            newToolSet.addTool(tool)
        return newToolSet

    def isEmpty(self) -> bool:
        return len(self.tools) == 0
