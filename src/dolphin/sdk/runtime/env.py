import asyncio
import logging
import os
import glob
import importlib.util
import inspect
import traceback
from typing import Dict, Optional, AsyncGenerator, Any

from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.logging.logger import console
from dolphin.sdk.tool.global_toolkits import GlobalToolkits
from dolphin.core.common.object_type import ObjectTypeFactory


class Env:
    """
    Environment class for managing multiple DPH agents
    """

    def __init__(
        self,
        globalConfig: GlobalConfig,
        agentFolderPath: str,
        toolkitFolderPath: str | None = None,
        verbose: bool = False,
        is_cli: bool = False,
        log_level: int = logging.INFO,
        output_variables: list[str] = [],
        skillkitFolderPath: str | None = None,
    ):
        """
        Initialize environment with global config and folder path

        Args:
            globalConfig (GlobalConfig): Global configuration object
            agentFolderPath (str): Directory path to scan for DPH files
            toolkitFolderPath (str): Directory path to scan for custom toolkits

        Raises:
            ValueError: If folder path doesn't exist
        """
        # Backward-compatibility: skillkitFolderPath was renamed to toolkitFolderPath
        if skillkitFolderPath is not None:
            import warnings
            warnings.warn(
                "Env parameter 'skillkitFolderPath' is deprecated, use 'toolkitFolderPath' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            if toolkitFolderPath is None:
                toolkitFolderPath = skillkitFolderPath
        self.globalConfig = globalConfig
        self.agentFolderPath = agentFolderPath
        self.toolkitFolderPath = toolkitFolderPath
        self.verbose = verbose
        self.is_cli = is_cli
        self.log_level = log_level
        self.agents: Dict[str, DolphinAgent] = {}
        self.output_variables = output_variables

        # Validate folder existence
        if not os.path.exists(agentFolderPath):
            raise ValueError(f"Agent folder path not found: {agentFolderPath}")

        # Initialize global toolkits manager
        self.globalToolkits = GlobalToolkits(globalConfig)

        # Initialize global types manager
        self.global_types = ObjectTypeFactory()

        # Load type definitions from .type files
        self._loadTypeFiles()

        # Load custom skillkits if specified
        if toolkitFolderPath is not None:
            self._loadCustomToolkits()

        # Scan and load agents
        self._scanAndLoadAgents()

        # Register agents as tools
        self._registerAgentsAsTools()

    def _loadTypeFiles(self):
        """
        Scan for .type files in agent folder and load them into global_types
        """
        # Get all .type files recursively
        searchPattern = os.path.join(self.agentFolderPath, "**", "*.type")
        typeFiles = glob.glob(searchPattern, recursive=True)

        for filePath in typeFiles:
            try:
                self.global_types.load(filePath)
                if self.verbose:
                    console(f"Loaded type definition: {filePath}")
            except Exception as e:
                console(f"Failed to load type file {filePath}: {str(e)}")
                continue

    def _loadCustomToolkits(self):
        """
        Load all toolkits from custom toolkit folder
        """
        if self.toolkitFolderPath is not None and not os.path.exists(
            self.toolkitFolderPath
        ):
            console(f"Custom toolkit folder not found: {self.toolkitFolderPath}")
            return

        # Initialize VM if needed
        vm = None
        if (
            hasattr(self.globalConfig, "vm_config")
            and self.globalConfig.vm_config is not None
        ):
            try:
                from dolphin.lib.vm.vm import VMFactory

                vm = VMFactory.createVM(self.globalConfig.vm_config)
            except Exception as e:
                console(f"Failed to create VM: {str(e)}")

        # Scan for Python files recursively
        searchPattern = os.path.join(self.toolkitFolderPath, "**", "*.py")
        pythonFiles = glob.glob(searchPattern, recursive=True)

        for filePath in pythonFiles:
            # Skip __init__.py and __pycache__ files
            if os.path.basename(filePath).startswith("__"):
                continue

            try:
                # Get module name from file path
                relativePath = os.path.relpath(filePath, self.toolkitFolderPath)
                moduleName = relativePath.replace(os.sep, ".").replace(".py", "")

                # Load the module dynamically
                spec = importlib.util.spec_from_file_location(moduleName, filePath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find all Toolkit classes in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Check if it's a Toolkit subclass but not Toolkit itself
                    if (
                        hasattr(obj, "__bases__")
                        and any(base.__name__ == "Toolkit" for base in obj.__bases__)
                        and obj.__name__ != "Toolkit"
                    ):
                        # Create an instance of the toolkit
                        toolkit_instance = obj()

                        # Set VM if this is VMToolkit and we have a VM configured
                        if hasattr(toolkit_instance, "setVM") and vm is not None:
                            toolkit_instance.setVM(vm)

                        # Add all tools from this toolkit to the installed toolset
                        for skill in toolkit_instance.getTools():
                            self.globalToolkits.installedToolSet.addTool(skill)

                        if self.verbose:
                            console(
                                f"Loaded custom toolkit: {obj.__name__} from {filePath}"
                            )

            except Exception as e:
                # Log error but continue with other files
                console(f"Failed to load custom toolkit from {filePath}: {str(e)}")
                traceback.print_exc()
                continue

    def _scanAndLoadAgents(self):
        """
        Scan folder path (including subdirectories) for DPH files and create Agent instances
        """
        # Get all DPH files recursively
        dolphinFiles = self._scanDolphinFiles(self.agentFolderPath)

        for filePath in dolphinFiles:
            try:
                # Pass the shared GlobalToolkits instance and global_types to DolphinAgent
                agent = DolphinAgent(
                    file_path=filePath,
                    global_config=self.globalConfig,
                    global_toolkits=self.globalToolkits,
                    global_types=self.global_types,
                    verbose=self.verbose,
                    is_cli=self.is_cli,
                    log_level=self.log_level,
                    output_variables=self.output_variables,
                )
                agentName = agent.get_name()

                # Handle duplicate names by appending directory info
                originalName = agentName
                counter = 1
                while agentName in self.agents:
                    agentName = f"{originalName}_{counter}"
                    counter += 1

                self.agents[agentName] = agent
                if self.verbose:
                    console(
                        f"Loaded agent: {agentName} from {filePath}", verbose=self.verbose
                    )

            except Exception as e:
                console(f"Failed to load agent from {filePath}: {str(e)}")
                continue

    def _scanDolphinFiles(self, folderPath: str) -> list:
        """
        Scan folder and subdirectories for DPH files

        Args:
            folderPath (str): Directory path to scan

        Returns:
            List of DPH file paths
        """
        dolphinFiles = []

        # Use glob to find all .dph files recursively
        searchPattern = os.path.join(folderPath, "**", "*.dph")
        dolphinFiles.extend(glob.glob(searchPattern, recursive=True))

        return dolphinFiles

    def _registerAgentsAsTools(self):
        """
        Register all loaded agents as tools in the global toolkits manager
        """
        for agentName, agent in self.agents.items():
            self.globalToolkits.registerAgentTool(agentName, agent)

    def getAgent(self, agentName: str) -> Optional[DolphinAgent]:
        """
        Get agent by name

        Args:
            agentName (str): Name of the agent

        Returns:
            DolphinAgent instance or None if not found
        """
        return self.agents.get(agentName)

    def getAgents(self) -> Dict[str, DolphinAgent]:
        """
        Get all agents

        Returns:
            Dictionary of agent name to DolphinAgent instance
        """
        return self.agents.copy()

    def getAgentNames(self) -> list:
        """
        Get list of all agent names

        Returns:
            List of agent names
        """
        return list(self.agents.keys())

    def _setupAgentContext(self, agent):
        """
        Setup agent context with all available agents and tools

        Args:
            agent: Agent instance to setup
        """
        # Set global tools (including agent tools) into the agent's executor context.
        if hasattr(agent, "executor") and hasattr(agent.executor, "context"):
            allTools = self.globalToolkits.getAllTools()
            agent.set_tools(allTools)

    async def arun(self, agentName: str, **kwargs) -> AsyncGenerator[Any, None]:
        """
        Asynchronously run specified agent

        Args:
            agentName (str): Name of the agent to run
            **kwargs: Additional arguments to pass to agent

        Yields:
            Execution results from each step

        Raises:
            ValueError: If agent not found
        """
        agent = self.getAgent(agentName)
        if agent is None:
            raise ValueError(f"Agent not found: {agentName}")

        # Ensure that the agent's executor context contains all agents
        self._setupAgentContext(agent)

        async for result in agent.arun(**kwargs):
            yield result

    def getGlobalToolkits(self) -> GlobalToolkits:
        """
        Get the global toolkits manager

        Returns:
            GlobalToolkits instance
        """
        return self.globalToolkits

    def getGlobalSkills(self) -> GlobalToolkits:
        """Deprecated: use getGlobalToolkits() instead."""
        import warnings

        warnings.warn(
            "Env.getGlobalSkills() is deprecated, use Env.getGlobalToolkits() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.getGlobalToolkits()

    @property
    def globalSkills(self) -> GlobalToolkits:
        """Deprecated: use :attr:`globalToolkits` instead."""
        import warnings
        warnings.warn(
            "Env.globalSkills is deprecated, use Env.globalToolkits instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.globalToolkits

    def getGlobalTypes(self) -> ObjectTypeFactory:
        """
        Get the global types manager

        Returns:
            ObjectTypeFactory instance
        """
        return self.global_types

    def addAgent(self, agentName: str, agent: DolphinAgent):
        """
        Add a new agent to the environment

        Args:
            agentName (str): Name for the agent
            agent (DolphinAgent): DolphinAgent instance
        """
        self.agents[agentName] = agent
        self.globalToolkits.registerAgentTool(agentName, agent)

    async def ashutdown(self):
        """
        Gracefully shutdown the environment and its components asynchronously.
        """
        # Shutdown all agents if they have shutdown methods
        for agent in self.agents.values():
            await agent.terminate()

        # Clear agents dictionary
        self.agents.clear()

    def shutdown(self):
        """
        Gracefully shutdown the environment and its components.
        """
        # Shutdown all agents if they have shutdown methods
        for agent in self.agents.values():
            try:
                # Try to get the current event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If the event loop is running, create a task
                    loop.create_task(agent.terminate())
                else:
                    # Otherwise run until completion
                    loop.run_until_complete(agent.terminate())
            except RuntimeError:
                # If no event loop is running, create a new one.
                asyncio.run(agent.terminate())

        # Clear agents dictionary
        self.agents.clear()

    def __str__(self) -> str:
        """
        String representation of the environment

        Returns:
            Environment description string
        """
        return f"Env(agentFolder={self.agentFolderPath}, toolkitFolder={self.toolkitFolderPath}, agents={len(self.agents)})"
