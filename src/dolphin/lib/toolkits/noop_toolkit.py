from typing import List
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.toolkit import Toolkit


class NoopToolkit(Toolkit):
    """
    just for test
    """

    def __init__(self):
        super().__init__()
        self.globalContext = None

    def getName(self) -> str:
        return " noop_toolkit"

    def noop_calling(self, **kwargs) -> str:
        """Do nothing, for testing

        Args:
            None

        Returns:
            str: Do nothing, for testing
        """
        print("do nothing")
        return "do nothing"

    def _createTools(self) -> List[ToolFunction]:
        return [ToolFunction(self.noop_calling)]
