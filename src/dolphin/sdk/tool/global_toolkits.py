import os
import importlib.util
import importlib.metadata
import inspect
from typing import Dict, Optional

from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.logging.logger import get_logger
from dolphin.core.tool.toolset import ToolSet
from dolphin.lib.toolkits.agent_toolkit import AgentToolkit
from dolphin.lib.toolkits.system_toolkit import (
    SystemFunctionsToolkit,
)
from dolphin.core.agent.base_agent import BaseAgent
from dolphin.core.utils.rich_status import safe_rich_status

logger = get_logger("tool")


class GlobalToolkits:
    """
    Global tools manager that handles both installed tools and agent tools
    """

    def __init__(self, globalConfig: GlobalConfig):
        """
        Initialize global tools manager

        Args:
            globalConfig (GlobalConfig): Global configuration object
        """
        self.globalConfig = globalConfig
        self.installedToolSet = ToolSet()
        self.agentToolSet = ToolSet()
        self.agentTools: Dict[str, BaseAgent] = {}

        # Load installed tools from tool/installed directory
        self._loadInstalledSkills()

        # Load MCP skills if enabled
        if globalConfig.mcp_config and globalConfig.mcp_config.enabled:
            self._loadMCPSkills()

        self._syncAllTools()

    def _loadInstalledSkills(self):
        """
        Load all toolkits using entry points first, fallback to file-based loading
        """
        # Try loading from entry points first (preferred method for pyinstaller compatibility)
        if self._loadToolkitsFromEntryPoints():
            logger.debug("Successfully loaded toolkits from entry points")
        else:
            logger.debug(
                "Entry points loading failed, falling back to file-based loading"
            )
            # Fallback to original file-based loading
            self._loadToolkitsFromFiles()

        # Handle system function loading, following skill_config configuration
        enabled_system_functions = self._get_enabled_system_functions()
        # Decide how to load system functions based on the value of enabled_system_functions
        system_functions = SystemFunctionsToolkit(enabled_system_functions)
        for tool in system_functions.getTools():
            self.installedToolSet.addTool(tool)

    def _loadToolkitsFromEntryPoints(self) -> bool:
        """
        Load toolkits from setuptools entry points

        Returns:
            bool: True if loading succeeded, False if failed
        """
        try:
            # Get all entry points for dolphin.toolkits
            entry_points = importlib.metadata.entry_points(group="dolphin.toolkits")

            if not entry_points:
                logger.debug("No dolphin.toolkits entry points found")
                return False

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
                    logger.warning(f"Failed to create VM: {str(e)}")

            loaded_count = 0
            with safe_rich_status(
                "[bold green]Loading toolkits from entry points..."
            ) as status:
                for entry_point in entry_points:
                    status.update(f"[bold blue]Loading toolkit:[/][white] {entry_point.name}[/]")
                    try:
                        # Check if this skill should be loaded based on config
                        if not self.globalConfig.skill_config.should_load_skill(entry_point.name):
                            logger.debug(f"Skipping disabled toolkit: {entry_point.name}")
                            continue

                        # Load the toolkit class from entry point
                        toolkit_class = entry_point.load()

                        # Verify it's a Toolkit subclass
                        if not self._is_obj_hierarchy_from_class_name(
                            toolkit_class, "Toolkit"
                        ):
                            logger.warning(
                                f"Entry point {entry_point.name} is not a Toolkit subclass, skipping"
                            )
                            continue

                        # Create instance and configure
                        toolkit_instance = toolkit_class()

                        # Set VM if this is VMToolkit and we have a VM configured
                        if hasattr(toolkit_instance, "setVM") and vm is not None:
                            toolkit_instance.setVM(vm)

                        # Set global context if the toolkit supports it
                        if hasattr(toolkit_instance, "setGlobalConfig"):
                            toolkit_instance.setGlobalConfig(self.globalConfig)

                        # Add toolkit to the installed toolset
                        # This tracks the toolkit for metadata aggregation
                        self.installedToolSet.addToolkit(toolkit_instance)

                        loaded_count += 1
                        logger.debug(
                            f"Loaded toolkit from entry point: {entry_point.name}"
                        )

                    except Exception as e:
                        import traceback
                        logger.error(
                            f"Failed to load toolkit from entry point {entry_point.name}: {str(e)}"
                        )
                        logger.error(traceback.format_exc())
                        continue

            logger.debug(
                f"Successfully loaded {loaded_count} toolkits from entry points"
            )
            return loaded_count > 0

        except Exception as e:
            logger.error(f"Failed to load toolkits from entry points: {str(e)}")
            return False

    def _loadToolkitsFromFiles(self):
        """
        Load all toolkits from tool/installed directory (fallback method)
        Reuses existing code from DolphinExecutor::set_installed_skills
        """
        # Load built-in toolkits (fallback for development mode when entry points are not available)
        self._loadBuiltinToolkits()

        # Get the path to tool/installed directory
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        installed_skills_dir = os.path.join(current_dir, "tool", "installed")

        if not os.path.exists(installed_skills_dir):
            logger.warning(
                f"Installed skills directory not found: {installed_skills_dir}"
            )
            return
        self._loadToolkitsFromPath(installed_skills_dir, "installed")

    def _loadBuiltinToolkits(self):
        """
        Load built-in toolkits from dolphin.lib.toolkits.
        This serves as a fallback for development mode or non-installed environments.
        """
        builtin_toolkits = {
            "plan_toolkit": "dolphin.lib.toolkits.plan_toolkit.PlanToolkit",
            "cognitive": "dolphin.lib.toolkits.cognitive_toolkit.CognitiveToolkit",
            "env_toolkit": "dolphin.lib.toolkits.env_toolkit.EnvToolkit",
        }

        for toolkit_name, class_path in builtin_toolkits.items():
            # Check if this toolkit should be loaded
            if not self.globalConfig.skill_config.should_load_skill(toolkit_name):
                logger.debug(f"Skipping disabled toolkit: {toolkit_name}")
                continue

            try:
                # Import the toolkit class
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                toolkit_class = getattr(module, class_name)

                # Create instance
                toolkit_instance = toolkit_class()

                # Set global config if supported
                if hasattr(toolkit_instance, "setGlobalConfig"):
                    toolkit_instance.setGlobalConfig(self.globalConfig)

                # Add to installed toolset
                self.installedToolSet.addToolkit(toolkit_instance)

                logger.debug(f"Loaded built-in toolkit: {toolkit_name}")
            except Exception as e:
                logger.error(f"Failed to load built-in toolkit {toolkit_name}: {str(e)}")

    def _get_enabled_system_functions(self) -> Optional[list[str]]:
        """Extract system function configurations from skill_config.enabled_skills"""
        enabled_skills = self.globalConfig.skill_config.enabled_skills

        # If enabled_skills is None, it means all skills (including system functions) will be loaded.
        if enabled_skills is None:
            return None

        # Extract configurations in the format of system_functions.*
        system_functions = []
        for skill in enabled_skills:
            if skill.startswith("system_functions."):
                function_name = skill.replace("system_functions.", "")
                system_functions.append(function_name)
        # If system_functions are explicitly configured but the list is empty, return an empty list (no system functions will be loaded)
        has_system_config = any(
            skill.startswith("system_functions") for skill in enabled_skills
        )
        if has_system_config and not system_functions:
            return []

        # If no system_functions are configured, return [] (for backward compatibility)
        if not system_functions:
            return []

        return system_functions

    def _loadMCPSkills(self):
        """Load MCP skill suite"""
        # Check whether MCP skills should be loaded
        if not self.globalConfig.skill_config.should_load_skill("mcp"):
            logger.debug("MCP skills are disabled by configuration")
            return

        try:
            from dolphin.lib.toolkits.mcp_toolkit import MCPToolkit

            # Create a single MCP skill suite instance
            toolkit = MCPToolkit()
            toolkit.setGlobalConfig(self.globalConfig)

            # Get skills and add to installed tool set
            tools = toolkit.getTools()
            for tool in tools:
                self.installedToolSet.addTool(tool)

            logger.debug(f"Loaded MCP toolkit: {len(tools)} tools")

        except ImportError as e:
            logger.warning(f"Failed to import MCP components: {str(e)}")
        except Exception as e:
            logger.warning(f"Error loading MCP skills: {str(e)}")

    def _loadCustomToolkitsFromPath(self, toolkitFolderPath: str):
        """
        Load all toolkits from custom toolkit folder

        Args:
            toolkitFolderPath (str): Path to the custom toolkit folder
        """
        # Normalize the path to handle both relative and absolute paths
        if not os.path.isabs(toolkitFolderPath):
            # Convert relative path to absolute path based on current working directory
            toolkitFolderPath = os.path.abspath(toolkitFolderPath)

        if not os.path.exists(toolkitFolderPath):
            logger.warning(f"Custom toolkit folder not found: {toolkitFolderPath}")
            return

        logger.debug(f"Loading custom toolkits from: {toolkitFolderPath}")
        self._loadToolkitsFromPath(toolkitFolderPath, "custom")

    def _loadToolkitsFromPath(self, folderPath: str, toolkitType: str = "installed"):
        """
        Load toolkits from the specified folder path (only top-level directory)

        Args:
            folderPath (str): Path to scan for toolkits
            toolkitType (str): Type of toolkits being loaded ("installed" or "custom")
        """
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
                logger.warning(f"Failed to create VM: {str(e)}")

        # Define files to skip (not toolkits but utility modules)
        SKIP_MODULES = {
            "mcp_adapter",  # MCP adapter utility, not a toolkit
            # Add other utility modules here as needed
        }

        # Only scan top-level directory for both installed and custom toolkits
        if not os.path.exists(folderPath):
            logger.warning(f"Toolkit folder does not exist: {folderPath}")
            return

        for filename in os.listdir(folderPath):
            # Only process .py files in the top-level directory, skip __init__.py and __pycache__
            if filename.endswith(".py") and not filename.startswith("__"):
                filePath = os.path.join(folderPath, filename)

                # Skip directories
                if os.path.isdir(filePath):
                    continue

                moduleName = filename[:-3]  # Remove .py extension

                # Skip utility modules that are not toolkits
                if moduleName in SKIP_MODULES:
                    continue

                if not self.globalConfig.skill_config.should_load_skill(moduleName):
                    continue

                try:
                    self._loadToolkitFromFile(filePath, moduleName, vm, toolkitType)
                except Exception as e:
                    # Log error but continue with other files
                    logger.error(
                        f"Failed to load {toolkitType} toolkit from {filename}: {str(e)}"
                    )
                    continue

    def _loadToolkitFromFile(
        self, filePath: str, moduleName: str, vm, toolkitType: str
    ):
        """
        Load toolkit from a single file

        Args:
            filePath (str): Path to the Python file
            moduleName (str): Module name for import
            vm: VM instance (if available)
            toolkitType (str): Type of toolkit being loaded
        """
        import sys
        import os

        # Get the directory containing the file and its parent
        dirPath = os.path.dirname(filePath)
        parentDirPath = os.path.dirname(dirPath)
        originalSysPath = sys.path.copy()

        try:
            # Add both the file's directory and its parent to sys.path
            paths_to_add = [dirPath, parentDirPath]
            for path in paths_to_add:
                if path not in sys.path:
                    sys.path.insert(0, path)

            # Ensure package structure is properly initialized
            packageName = os.path.basename(dirPath)

            # Create package module if it doesn't exist
            if packageName not in sys.modules:
                package_init_file = os.path.join(dirPath, "__init__.py")
                if os.path.exists(package_init_file):
                    # Load the package __init__.py
                    package_spec = importlib.util.spec_from_file_location(
                        packageName, package_init_file
                    )
                    package_module = importlib.util.module_from_spec(package_spec)
                    package_module.__path__ = [dirPath]
                    sys.modules[packageName] = package_module
                    try:
                        package_spec.loader.exec_module(package_module)
                    except Exception as e:
                        logger.warning(
                            f"Warning: Failed to execute package __init__.py: {e}"
                        )
                else:
                    # Create a minimal package module
                    package_module = type(sys)("package")
                    package_module.__path__ = [dirPath]
                    package_module.__package__ = packageName
                    sys.modules[packageName] = package_module

            # Try different import strategies
            module = None
            import_errors = []

            # Strategy 1: Direct file import with package context
            try:
                spec = importlib.util.spec_from_file_location(moduleName, filePath)
                module = importlib.util.module_from_spec(spec)

                # Set package information for relative imports
                module.__package__ = packageName
                module.__file__ = filePath

                # Add to sys.modules temporarily to support relative imports
                sys.modules[moduleName] = module
                if packageName != moduleName:
                    sys.modules[packageName + "." + moduleName] = module

                spec.loader.exec_module(module)

            except Exception as e:
                import_errors.append(f"Strategy 1 failed: {e}")

                # Strategy 2: Try importing as part of package
                try:
                    fullModuleName = f"{packageName}.{moduleName}"

                    spec = importlib.util.spec_from_file_location(
                        fullModuleName, filePath
                    )
                    module = importlib.util.module_from_spec(spec)
                    module.__package__ = packageName

                    sys.modules[fullModuleName] = module
                    spec.loader.exec_module(module)

                except Exception as e2:
                    import_errors.append(f"Strategy 2 failed: {e2}")

                    # Strategy 3: Load target module only without dependencies
                    try:
                        # Just try to load our target module directly with absolute import
                        fullModuleName = f"{packageName}.{moduleName}"

                        # Create module spec
                        spec = importlib.util.spec_from_file_location(
                            fullModuleName, filePath
                        )
                        module = importlib.util.module_from_spec(spec)
                        module.__package__ = packageName

                        # Add to sys.modules
                        sys.modules[fullModuleName] = module

                        # Try to execute, if it fails due to missing dependencies,
                        # modify the imports in the module temporarily
                        original_import = __builtins__["__import__"]

                        def custom_import(
                            name, globals=None, locals=None, fromlist=(), level=0
                        ):
                            # Handle relative imports within the same package
                            if (
                                level > 0
                                and globals
                                and globals.get("__package__") == packageName
                            ):
                                if level == 1:  # from .module import something
                                    base_module = packageName
                                    if name:
                                        full_name = f"{base_module}.{name}"
                                    else:
                                        full_name = base_module
                                else:
                                    full_name = name

                                # Try to load the referenced module if it's in the same directory
                                if "." in full_name:
                                    module_name = full_name.split(".")[-1]
                                    module_file = os.path.join(
                                        dirPath, f"{module_name}.py"
                                    )
                                    if (
                                        os.path.exists(module_file)
                                        and full_name not in sys.modules
                                    ):
                                        try:
                                            ref_spec = (
                                                importlib.util.spec_from_file_location(
                                                    full_name, module_file
                                                )
                                            )
                                            ref_module = (
                                                importlib.util.module_from_spec(
                                                    ref_spec
                                                )
                                            )
                                            ref_module.__package__ = packageName
                                            sys.modules[full_name] = ref_module
                                            ref_spec.loader.exec_module(ref_module)
                                        except:
                                            pass

                                return original_import(
                                    full_name, globals, locals, fromlist, 0
                                )
                            else:
                                return original_import(
                                    name, globals, locals, fromlist, level
                                )

                        # Temporarily replace __import__
                        __builtins__["__import__"] = custom_import

                        try:
                            spec.loader.exec_module(module)
                        finally:
                            # Restore original __import__
                            __builtins__["__import__"] = original_import

                    except Exception as e3:
                        import_errors.append(f"Strategy 3 failed: {e3}")
                        raise Exception(
                            f"All import strategies failed: {import_errors}"
                        )

            if module is None:
                raise Exception(f"Failed to load module: {import_errors}")

            # Find all Toolkit classes in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a Toolkit subclass but not Toolkit itself
                if self._is_obj_hierarchy_from_class_name(obj, "Toolkit"):
                    # Create an instance of the toolkit
                    toolkit_instance = obj()

                    # Set VM if this is VMToolkit and we have a VM configured
                    if hasattr(toolkit_instance, "setVM") and vm is not None:
                        toolkit_instance.setVM(vm)

                    # Set global context if the toolkit supports it
                    if hasattr(toolkit_instance, "setGlobalConfig"):
                        toolkit_instance.setGlobalConfig(self.globalConfig)

                    # Add toolkit to the installed toolset
                    # This tracks the toolkit for metadata aggregation
                    self.installedToolSet.addToolkit(toolkit_instance)

                    logger.debug(
                        f"Loaded {toolkitType} toolkit: {moduleName} from {filePath}"
                    )

        except Exception as e:
            logger.error(
                f"Failed to load {toolkitType} toolkit from {filePath}: {str(e)}"
            )
        finally:
            # Clean up sys.modules to avoid conflicts, but keep package modules
            modules_to_remove = []
            for mod_name in sys.modules:
                if mod_name == moduleName or (
                    mod_name.endswith("." + moduleName) and mod_name != packageName
                ):
                    modules_to_remove.append(mod_name)

            for mod_name in modules_to_remove:
                try:
                    del sys.modules[mod_name]
                except KeyError:
                    pass

            # Restore original sys.path
            sys.path = originalSysPath

    def registerAgentTool(self, agentName: str, agent: BaseAgent):
        """
        Register an agent as a tool

        Args:
            agentName (str): Name of the agent
            agent (BaseAgent): BaseAgent instance to register
        """
        # Store agent reference
        self.agentTools[agentName] = agent

        # Create AgentToolkit to wrap the agent
        agentToolkit = AgentToolkit(agent, agentName)

        # Add agent tools to the agent toolset
        for tool in agentToolkit.getTools():
            self.agentToolSet.addTool(tool)

        self._syncAllTools()

        logger.debug(f"Registered agent tool: {agentName}")

    def unregisterAgentTool(self, agentName: str):
        """
        Unregister an agent tool

        Args:
            agentName (str): Name of the agent to unregister
        """
        if agentName in self.agentTools:
            # Remove from agent tools
            del self.agentTools[agentName]

            # Remove from toolset - this is tricky as we need to identify which tools belong to this agent
            # We'll rebuild the agent toolset
            self._rebuildAgentToolSet()

            logger.debug(f"Unregistered agent tool: {agentName}")
        self._syncAllTools()

    def _rebuildAgentToolSet(self):
        """
        Rebuild the agent toolset from current agent tools
        """
        self.agentToolSet = ToolSet()
        for agentName, agent in self.agentTools.items():
            agentToolkit = AgentToolkit(agent, agentName)
            for tool in agentToolkit.getTools():
                self.agentToolSet.addTool(tool)

    def clearAgentTools(self):
        """
        Clear all agent tools
        """
        self.agentTools.clear()
        self.agentToolSet = ToolSet()
        self._syncAllTools()

    def getInstalledTools(self) -> ToolSet:
        """
        Get the installed tools toolset

        Returns:
            ToolSet containing installed tools
        """
        return self.installedToolSet

    def getAgentTools(self) -> ToolSet:
        """
        Get the agent tools toolset

        Returns:
            ToolSet containing agent tools
        """
        return self.agentToolSet

    def _syncAllTools(self):
        """
        Sync all tools (installed + agent tools) as a combined toolset.

        Note: Metadata prompt is not copied here. It is dynamically collected
        via tool.owner_toolkit in ExploreStrategy._collect_metadata_prompt().
        """
        self.allTools = ToolSet()

        # Add installed tools (owner_toolkit is already bound)
        for tool in self.installedToolSet.getTools():
            self.allTools.addTool(tool)

        # Add agent tools
        for tool in self.agentToolSet.getTools():
            self.allTools.addTool(tool)

    def getAllTools(self) -> ToolSet:
        """
        Get all tools (installed + agent tools) as a combined toolset

        Returns:
            ToolSet containing all tools
        """
        return self.allTools

    def getToolNames(self) -> list:
        """
        Get all tool names

        Returns:
            List of all tool names
        """
        return self.getAllTools().getToolNames()

    def hasTool(self, toolName: str) -> bool:
        """
        Check if a tool exists

        Args:
            toolName (str): Name of the tool to check

        Returns:
            True if tool exists, False otherwise
        """
        return self.getAllTools().hasTool(toolName)

    def getTool(self, toolName: str):
        """
        Get a tool by name

        Args:
            toolName (str): Name of the tool to get

        Returns:
            ToolFunction tool or None if not found
        """
        return self.getAllTools().getTool(toolName)

    def getAgent(self, agentName: str) -> Optional[BaseAgent]:
        """
        Get an agent by name

        Args:
            agentName (str): Name of the agent

        Returns:
            BaseAgent instance or None if not found
        """
        return self.agentTools.get(agentName)

    def getAgentNames(self) -> list:
        """
        Get list of all registered agent names

        Returns:
            List of agent names
        """
        return list(self.agentTools.keys())

    def _is_obj_hierarchy_from_class_name(self, obj: object, className: str) -> bool:
        """
        Check if an object is a hierarchy of a given class name
        """
        if hasattr(obj, "__bases__"):
            for base in obj.__bases__:
                if base.__name__ == className:
                    return True
                if self._is_obj_hierarchy_from_class_name(base, className):
                    return True
        return False

    def __str__(self) -> str:
        """
        String representation of global tools

        Returns:
            Description string
        """
        return f"GlobalToolkits(installed={len(self.installedToolSet.getTools())}, agents={len(self.agentTools)})"
