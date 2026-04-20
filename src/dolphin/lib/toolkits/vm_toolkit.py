from typing import List

from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.toolkit import Toolkit
from dolphin.lib.vm.vm import VM
from dolphin.lib.vm.python_session_manager import PythonSessionManager


class VMToolkit(Toolkit):
    def __init__(self):
        super().__init__()
        self.vm: VM = None
        self.session_manager = PythonSessionManager()

    def getName(self) -> str:
        return "vm_toolkit"

    def setVM(self, vm: VM):
        self.vm = vm

    def _bash(self, cmd: str, **kwargs) -> str:
        """Execute a bash command in the virtual machine and return the execution result.

        Args:
            cmd (str): The bash command to execute

        Returns:
            str: The execution result
        """
        if self.vm is None:
            raise RuntimeError(
                "VM is not configured. Please set VM before executing bash commands."
            )
        return self.vm.execBash(cmd)

    def _python(self, cmd: str, **kwargs) -> str:
        """Execute a Python command in the virtual machine and return the execution result.
        Support session state persistence, running continuously like Jupyter Notebook.

        Args:
            cmd (str): The Python command to execute; result variables need to be printed
            **kwargs: Additional parameters, including gvp from context

        Returns:
            str: Execution result
        """
        if self.vm is None:
            raise RuntimeError(
                "VM is not configured. Please set VM before executing Python commands."
            )

        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        if session_id:
            kwargs["session_id"] = session_id
            kwargs["session_manager"] = self.session_manager

        return self.vm.execPython(cmd, **kwargs)

    def _createTools(self) -> List[ToolFunction]:
        return [
            ToolFunction(self._bash, block_as_parameter=("bash", "cmd")),
            ToolFunction(self._python, block_as_parameter=("python", "cmd")),
        ]
