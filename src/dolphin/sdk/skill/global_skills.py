import os
import importlib.util
import importlib.metadata
import inspect
from typing import Dict, Optional
from rich.console import Console

from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.logging.logger import get_logger
from dolphin.core.skill.skillset import Skillset
from dolphin.lib.skillkits.agent_skillkit import AgentSkillKit
from dolphin.lib.skillkits.system_skillkit import (
    SystemFunctionsSkillKit,
)
from dolphin.core.agent.base_agent import BaseAgent

logger = get_logger("skill")


class GlobalSkills:
    """
    Global skills manager that handles both installed skills and agent skills
    """

    def __init__(self, globalConfig: GlobalConfig):
        """
        Initialize global skills manager

        Args:
            globalConfig (GlobalConfig): Global configuration object
        """
        self.globalConfig = globalConfig
        self.installedSkillset = Skillset()
        self.agentSkillset = Skillset()
        self.agentSkills: Dict[str, BaseAgent] = {}

        # Load installed skills from skill/installed directory
        self._loadInstalledSkills()

        # Load MCP skills if enabled
        if globalConfig.mcp_config and globalConfig.mcp_config.enabled:
            self._loadMCPSkills()

        self._syncAllSkills()

    def _loadInstalledSkills(self):
        """
        Load all skillkits using entry points first, fallback to file-based loading
        """
        # Try loading from entry points first (preferred method for pyinstaller compatibility)
        if self._loadSkillkitsFromEntryPoints():
            logger.debug("Successfully loaded skillkits from entry points")
        else:
            logger.debug(
                "Entry points loading failed, falling back to file-based loading"
            )
            # Fallback to original file-based loading
            self._loadSkillkitsFromFiles()

        # Handle system function loading, following skill_config configuration
        enabled_system_functions = self._get_enabled_system_functions()
        # Decide how to load system functions based on the value of enabled_system_functions
        system_functions = SystemFunctionsSkillKit(enabled_system_functions)
        for skill in system_functions.getSkills():
            self.installedSkillset.addSkill(skill)

    def _loadSkillkitsFromEntryPoints(self) -> bool:
        """
        Load skillkits from setuptools entry points

        Returns:
            bool: True if loading succeeded, False if failed
        """
        try:
            # Get all entry points for dolphin.skillkits
            entry_points = importlib.metadata.entry_points(group="dolphin.skillkits")
            
            if not entry_points:
                logger.debug("No dolphin.skillkits entry points found")
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
            console = Console()
            
            with console.status("[bold green]Loading skillkits from entry points...") as status:
                for entry_point in entry_points:
                    status.update(f"[bold blue]Loading skillkit:[/][white] {entry_point.name}[/]")
                    try:
                        # Check if this skill should be loaded based on config
                        if not self.globalConfig.skill_config.should_load_skill(
                            entry_point.name
                        ):
                            logger.debug(f"Skipping disabled skillkit: {entry_point.name}")
                            continue

                        # Load the skillkit class from entry point
                        skillkit_class = entry_point.load()

                        # Verify it's a Skillkit subclass
                        if not self._is_obj_hierarchy_from_class_name(
                            skillkit_class, "Skillkit"
                        ):
                            logger.warning(
                                f"Entry point {entry_point.name} is not a Skillkit subclass, skipping"
                            )
                            continue

                        # Create instance and configure
                        skillkit_instance = skillkit_class()

                        # Set VM if this is VMSkillkit and we have a VM configured
                        if hasattr(skillkit_instance, "setVM") and vm is not None:
                            skillkit_instance.setVM(vm)

                        # Set global context if the skillkit supports it
                        if hasattr(skillkit_instance, "setGlobalConfig"):
                            skillkit_instance.setGlobalConfig(self.globalConfig)

                        # Add skillkit to the installed skillset
                        # This tracks the skillkit for metadata aggregation
                        self.installedSkillset.addSkillkit(skillkit_instance)

                        loaded_count += 1
                        logger.debug(
                            f"Loaded skillkit from entry point: {entry_point.name}"
                        )

                    except Exception as e:
                        logger.error(
                            f"Failed to load skillkit from entry point {entry_point.name}: {str(e)}"
                        )
                        continue

            logger.debug(
                f"Successfully loaded {loaded_count} skillkits from entry points"
            )
            return loaded_count > 0

        except Exception as e:
            logger.error(f"Failed to load skillkits from entry points: {str(e)}")
            return False

    def _loadSkillkitsFromFiles(self):
        """
        Load all skillkits from skill/installed directory (fallback method)
        Reuses existing code from DolphinExecutor::set_installed_skills
        """
        # Get the path to skill/installed directory
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        installed_skills_dir = os.path.join(current_dir, "skill", "installed")

        if not os.path.exists(installed_skills_dir):
            logger.warning(
                f"Installed skills directory not found: {installed_skills_dir}"
            )
            return
        self._loadSkillkitsFromPath(installed_skills_dir, "installed")

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
            from dolphin.lib.skillkits.mcp_skillkit import MCPSkillkit

            # Create a single MCP skill suite instance
            skillkit = MCPSkillkit()
            skillkit.setGlobalConfig(self.globalConfig)

            # Get skills and add to installed skill set
            skills = skillkit.getSkills()
            for skill in skills:
                self.installedSkillset.addSkill(skill)

            logger.debug(f"Loaded MCP skillkit: {len(skills)} skills")

        except ImportError as e:
            logger.warning(f"Failed to import MCP components: {str(e)}")
        except Exception as e:
            logger.warning(f"Error loading MCP skills: {str(e)}")

    def _loadCustomSkillkitsFromPath(self, skillkitFolderPath: str):
        """
        Load all skillkits from custom skillkit folder

        Args:
            skillkitFolderPath (str): Path to the custom skillkit folder
        """
        # Normalize the path to handle both relative and absolute paths
        if not os.path.isabs(skillkitFolderPath):
            # Convert relative path to absolute path based on current working directory
            skillkitFolderPath = os.path.abspath(skillkitFolderPath)

        if not os.path.exists(skillkitFolderPath):
            logger.warning(f"Custom skillkit folder not found: {skillkitFolderPath}")
            return

        logger.debug(f"Loading custom skillkits from: {skillkitFolderPath}")
        self._loadSkillkitsFromPath(skillkitFolderPath, "custom")

    def _loadSkillkitsFromPath(self, folderPath: str, skillkitType: str = "installed"):
        """
        Load skillkits from the specified folder path (only top-level directory)

        Args:
            folderPath (str): Path to scan for skillkits
            skillkitType (str): Type of skillkits being loaded ("installed" or "custom")
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

        # Define files to skip (not skillkits but utility modules)
        SKIP_MODULES = {
            "mcp_adapter",  # MCP adapter utility, not a skillkit
            # Add other utility modules here as needed
        }

        # Only scan top-level directory for both installed and custom skillkits
        if not os.path.exists(folderPath):
            logger.warning(f"Skillkit folder does not exist: {folderPath}")
            return

        for filename in os.listdir(folderPath):
            # Only process .py files in the top-level directory, skip __init__.py and __pycache__
            if filename.endswith(".py") and not filename.startswith("__"):
                filePath = os.path.join(folderPath, filename)

                # Skip directories
                if os.path.isdir(filePath):
                    continue

                moduleName = filename[:-3]  # Remove .py extension

                # Skip utility modules that are not skillkits
                if moduleName in SKIP_MODULES:
                    continue

                if not self.globalConfig.skill_config.should_load_skill(moduleName):
                    continue

                try:
                    self._loadSkillkitFromFile(filePath, moduleName, vm, skillkitType)
                except Exception as e:
                    # Log error but continue with other files
                    logger.error(
                        f"Failed to load {skillkitType} skillkit from {filename}: {str(e)}"
                    )
                    continue

    def _loadSkillkitFromFile(
        self, filePath: str, moduleName: str, vm, skillkitType: str
    ):
        """
        Load skillkit from a single file

        Args:
            filePath (str): Path to the Python file
            moduleName (str): Module name for import
            vm: VM instance (if available)
            skillkitType (str): Type of skillkit being loaded
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

            # Find all Skillkit classes in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a Skillkit subclass but not Skillkit itself
                if self._is_obj_hierarchy_from_class_name(obj, "Skillkit"):
                    # Create an instance of the skillkit
                    skillkit_instance = obj()

                    # Set VM if this is VMSkillkit and we have a VM configured
                    if hasattr(skillkit_instance, "setVM") and vm is not None:
                        skillkit_instance.setVM(vm)

                    # Set global context if the skillkit supports it
                    if hasattr(skillkit_instance, "setGlobalConfig"):
                        skillkit_instance.setGlobalConfig(self.globalConfig)

                    # Add skillkit to the installed skillset
                    # This tracks the skillkit for metadata aggregation
                    self.installedSkillset.addSkillkit(skillkit_instance)

                    logger.debug(
                        f"Loaded {skillkitType} skillkit: {moduleName} from {filePath}"
                    )

        except Exception as e:
            logger.error(
                f"Failed to load {skillkitType} skillkit from {filePath}: {str(e)}"
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

    def registerAgentSkill(self, agentName: str, agent: BaseAgent):
        """
        Register an agent as a skill

        Args:
            agentName (str): Name of the agent
            agent (BaseAgent): BaseAgent instance to register
        """
        # Store agent reference
        self.agentSkills[agentName] = agent

        # Create AgentSkillKit to wrap the agent
        agentSkillKit = AgentSkillKit(agent, agentName)

        # Add agent skills to the agent skillset
        for skill in agentSkillKit.getSkills():
            self.agentSkillset.addSkill(skill)

        self._syncAllSkills()

        logger.debug(f"Registered agent skill: {agentName}")

    def unregisterAgentSkill(self, agentName: str):
        """
        Unregister an agent skill

        Args:
            agentName (str): Name of the agent to unregister
        """
        if agentName in self.agentSkills:
            # Remove from agent skills
            del self.agentSkills[agentName]

            # Remove from skillset - this is tricky as we need to identify which skills belong to this agent
            # We'll rebuild the agent skillset
            self._rebuildAgentSkillset()

            logger.debug(f"Unregistered agent skill: {agentName}")
        self._syncAllSkills()

    def _rebuildAgentSkillset(self):
        """
        Rebuild the agent skillset from current agent skills
        """
        self.agentSkillset = Skillset()
        for agentName, agent in self.agentSkills.items():
            agentSkillKit = AgentSkillKit(agent, agentName)
            for skill in agentSkillKit.getSkills():
                self.agentSkillset.addSkill(skill)

    def clearAgentSkills(self):
        """
        Clear all agent skills
        """
        self.agentSkills.clear()
        self.agentSkillset = Skillset()
        self._syncAllSkills()

    def getInstalledSkills(self) -> Skillset:
        """
        Get the installed skills skillset

        Returns:
            Skillset containing installed skills
        """
        return self.installedSkillset

    def getAgentSkills(self) -> Skillset:
        """
        Get the agent skills skillset

        Returns:
            Skillset containing agent skills
        """
        return self.agentSkillset

    def _syncAllSkills(self):
        """
        Sync all skills (installed + agent skills) as a combined skillset.

        Note: Metadata prompt is not copied here. It is dynamically collected
        via skill.owner_skillkit in ExploreStrategy._collect_metadata_prompt().
        """
        self.allSkills = Skillset()

        # Add installed skills (owner_skillkit is already bound)
        for skill in self.installedSkillset.getSkills():
            self.allSkills.addSkill(skill)

        # Add agent skills
        for skill in self.agentSkillset.getSkills():
            self.allSkills.addSkill(skill)

    def getAllSkills(self) -> Skillset:
        """
        Get all skills (installed + agent skills) as a combined skillset

        Returns:
            Skillset containing all skills
        """
        return self.allSkills

    def getSkillNames(self) -> list:
        """
        Get all skill names

        Returns:
            List of all skill names
        """
        return self.getAllSkills().getSkillNames()

    def hasSkill(self, skillName: str) -> bool:
        """
        Check if a skill exists

        Args:
            skillName (str): Name of the skill to check

        Returns:
            True if skill exists, False otherwise
        """
        return self.getAllSkills().hasSkill(skillName)

    def getSkill(self, skillName: str):
        """
        Get a skill by name

        Args:
            skillName (str): Name of the skill to get

        Returns:
            SkillFunction skill or None if not found
        """
        return self.getAllSkills().getSkill(skillName)

    def getAgent(self, agentName: str) -> Optional[BaseAgent]:
        """
        Get an agent by name

        Args:
            agentName (str): Name of the agent

        Returns:
            BaseAgent instance or None if not found
        """
        return self.agentSkills.get(agentName)

    def getAgentNames(self) -> list:
        """
        Get list of all registered agent names

        Returns:
            List of agent names
        """
        return list(self.agentSkills.keys())

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
        String representation of global skills

        Returns:
            Description string
        """
        return f"GlobalSkills(installed={len(self.installedSkillset.getSkills())}, agents={len(self.agentSkills)})"
