import os

import time
import glob
from typing import Optional, TYPE_CHECKING
from dolphin.core import flags
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.context.context import Context
from dolphin.core.common.constants import (
    KEY_MAX_ANSWER_CONTENT_LENGTH,
    KEY_SESSION_ID,
    KEY_USER_ID,
)
from dolphin.core.context_engineer.core.context_manager import (
    ContextManager,
)
from dolphin.core.executor.executor import Executor
from dolphin.core.common.object_type import ObjectTypeFactory
from dolphin.core.context.var_output import VarOutput
from dolphin.core.logging.logger import get_logger
from dolphin.core.common.enums import MessageRole

# Import sdk/lib modules under TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from dolphin.lib.memory.manager import MemoryManager
    from dolphin.sdk.skill.global_skills import GlobalSkills
    from dolphin.sdk.skill.traditional_toolkit import TriditionalToolkit
    from dolphin.lib.vm.vm import VM, VMFactory

logger = get_logger()


class DolphinExecutor:
    def __init__(
        self,
        global_config: GlobalConfig | None = None,
        global_configpath="./config/global.yaml",
        global_skills=None,
        global_types=None,
        type_folders=None,
        context_manager: Optional[ContextManager] = None,
        verbose: bool = False,
        is_cli: bool = False,
    ):
        # Lazy imports to avoid circular dependencies
        from dolphin.sdk.skill.global_skills import GlobalSkills
        from dolphin.lib.memory.manager import MemoryManager
        from dolphin.lib.vm.vm import VM, VMFactory
        
        # Initialize configuration with fallback logic
        if global_config is not None:
            self.config = global_config
        elif os.path.exists(global_configpath):
            self.config = GlobalConfig.from_yaml(global_configpath)
        else:
            self.config = GlobalConfig()
        self.global_skills = (
            global_skills if global_skills is not None else GlobalSkills(self.config)
        )
        self.global_types = (
            global_types if global_types is not None else ObjectTypeFactory()
        )

        # Auto-load type definitions if not provided and type_folders is not specified
        if global_types is None and type_folders is None:
            self._loadDefaultTypeFiles()
        elif type_folders is not None:
            self._loadTypeFilesFromFolders(type_folders)

        self.memory_manager = MemoryManager(global_config=self.config)
        self.context_manager = context_manager
        if self.context_manager is None:
            if self.config.context_engineer_config is not None and \
                    self.config.context_engineer_config.context_config is not None:
                self.context_manager = ContextManager(context_config=self.config.context_engineer_config.context_config)
            else:
                self.context_manager = ContextManager()
 
        self.context = Context(
            config=self.config,
            global_skills=self.global_skills,
            memory_manager=self.memory_manager,
            global_types=self.global_types,
            context_manager=self.context_manager,
            verbose=verbose,
            is_cli=is_cli,
        )

        self.vm: VM = None
        if self.config.vm_config is not None:
            self.vm = VMFactory.createVM(self.config.vm_config)

        # Coroutine execution components
        self.state_registry = None
        self.snapshot_store = None
        self._init_coroutine_components()
        # Debug controller reference (for CLI post-mortem access)
        self._debug_controller = None

    def _init_coroutine_components(self):
        """Initialize coroutine execution component"""
        from dolphin.core.coroutine import (
            ExecutionStateRegistry,
        )
        from dolphin.core.coroutine.context_snapshot_store import (
            MemoryContextSnapshotStore,
        )

        self.state_registry = ExecutionStateRegistry()
        self.snapshot_store = MemoryContextSnapshotStore()

    def _loadDefaultTypeFiles(self):
        """
        Auto-load type definitions from common directories
        """
        # Common directories to search for .type files
        default_type_paths = [
            "./examples/types",  # Project examples types
            "./types",  # Root types directory
            "./src/types",  # Source types directory
        ]

        for type_path in default_type_paths:
            if os.path.exists(type_path):
                self._loadTypeFilesFromFolder(type_path)

    def _loadTypeFilesFromFolders(self, type_folders):
        """
        Load type definitions from specified folders

        Args:
            type_folders: List of folder paths or single folder path
        """
        if isinstance(type_folders, str):
            type_folders = [type_folders]

        for folder in type_folders:
            if os.path.exists(folder):
                self._loadTypeFilesFromFolder(folder)
            else:
                logger.warning(f"Type folder not found: {folder}")

    def _loadTypeFilesFromFolder(self, folder_path):
        """
        Scan for .type files in the specified folder and load them into global_types

        Args:
            folder_path: Path to the folder containing .type files
        """
        # Get all .type files recursively
        search_pattern = os.path.join(folder_path, "**", "*.type")
        type_files = glob.glob(search_pattern, recursive=True)

        for file_path in type_files:
            try:
                self.global_types.load(file_path)
                logger.debug(f"Loaded type definition: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to load type file {file_path}: {e}")
                continue

    def load_type(self, type_json: dict):
        """
        Load a type definition from JSON data into global_types

        Args:
            type_json (dict): JSON type definition
        """
        self.global_types.load_from_json(type_json)

    def load_type_from_file(self, file_path: str):
        """
        Load a type definition from a .type file

        Args:
            file_path (str): Path to the .type file
        """
        self.global_types.load(file_path)

    async def executor_init(self, infos):
        for key, value in infos.items():
            if key == "config":
                self.config_initialize(value)
            if key == "variables":
                await self.context_initialize(param_dict=value)
            elif key == "tools":
                await self.context_initialize(tool_dict=value)
            elif key == "skillkit":
                await self.context_initialize(skillkit=value)
            elif key == "skillkit_hook":
                await self.context_initialize(skillkit_hook=value)
            else:
                pass

    def config_initialize(self, configs):
        # Lazy imports to avoid circular dependencies
        from dolphin.lib.memory.manager import MemoryManager
        from dolphin.lib.vm.vm import VM, VMFactory
        
        self.config = GlobalConfig.from_dict(configs)
        self.memory_manager = MemoryManager(global_config=self.config)
        # Recreate Context while keeping the original verbose and is_cli settings
        current_verbose = (
            getattr(self.context, "verbose", False)
            if hasattr(self, "context")
            else False
        )
        current_is_cli = (
            getattr(self.context, "is_cli", False)
            if hasattr(self, "context")
            else False
        )
        self.context = Context(
            config=self.config,
            global_skills=self.global_skills,
            memory_manager=self.memory_manager,
            global_types=self.global_types,
            verbose=current_verbose,
            is_cli=current_is_cli,
        )  # Initialize context here with preserved verbose/is_cli settings

        self.vm: VM = None
        if self.config.vm_config is not None:
            self.vm = VMFactory.createVM(self.config.vm_config)

    async def context_initialize(
        self,
        param_dict=None,
        tool_dict=None,
        skillkit=None,
        skillkit_hook=None,
    ):
        if param_dict is not None:
            for name, value in param_dict.items():
                if VarOutput.is_serialized_dict(value):
                    value = VarOutput.from_dict(value)
                self.context.set_variable(name=name, value=value)

        if tool_dict is not None:
            from dolphin.sdk.skill.traditional_toolkit import TriditionalToolkit
            triditional_toolkit = TriditionalToolkit.buildFromTooldict(tool_dict)
            self.context.set_skills(triditional_toolkit)
        elif skillkit is not None:
            self.context.set_skills(skillkit)
        elif skillkit_hook is not None:
            self.context.set_skillkit_hook(skillkit_hook)

    def set_context(self, context: Context):
        self.context = context

    async def continue_exploration(self, **kwargs):
        """Continue exploring based on the existing context (multi-turn dialogue scenario)

                This method reuses the message history, variable pool, and other states from the current context,
                and executes a new explore session to process the user's subsequent input.

        Args:
            model: Model name; if empty, the model used in the previous session from context will be used
            use_history: Whether to use historical messages, default is True
            mode: Exploration mode ("prompt" or "tool_call"); if empty, the mode used in the previous session from context will be used
            skills: List of skills; if empty, the skill configuration used in the previous session from context will be used
            tools: Alias for skills
            content: User input content (optional)
            output_var: Name of the output variable, default is "result"
            **kwargs: Additional parameters

        Note:
            The mode and skills parameters will automatically inherit the configuration from the previous round in context.
            To override, explicitly pass them via kwargs.

        Yields:
            Execution results
        """
        if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
            raise NotImplementedError(
                "continue_exploration 暂不支持 EXPLORE_BLOCK_V2 模式，"
                "请使用 flags.set_flag(flags.EXPLORE_BLOCK_V2, False) 禁用后再调用"
            )

        # Initialize context.all_skills from global_skills if not already set
        # This ensures tools are available for the exploration session
        self._prepare_for_run(**kwargs)

        # Ensure interrupt state is cleared for the new exploration round
        if hasattr(self.context, "clear_interrupt"):
            self.context.clear_interrupt()

        from dolphin.core.code_block.explore_block import ExploreBlock
        from dolphin.core.trajectory.recorder import Recorder
        from dolphin.core.runtime.runtime_instance import ProgressInstance

        # Create exploration block (default prompt mode)
        explore_block = ExploreBlock(
            context=self.context,
            debug_infos=None,
            tools_format=kwargs.get("tools_format", "medium"),
        )

        # Manually register block and progress to runtime_graph
        if self.context.runtime_graph:
            self.context.runtime_graph.set_block(explore_block)

        progress = ProgressInstance(self.context)
        if self.context.runtime_graph:
            self.context.runtime_graph.set_progress(progress)

        explore_block.recorder = Recorder(
            self.context,
            progress=progress,
        )

        # Extract parameters from kwargs and remove them to avoid "multiple values" error
        # when passing both explicitly and via **kwargs
        model_name = kwargs.pop("model", None) or self.context.get_last_model_name() or ""
        use_history = kwargs.pop("use_history", True)

        # Sync the model name to ExploreBlock
        if model_name:
            explore_block.model = model_name

        # Use the continue_exploration method of ExploreBlock
        async for result in explore_block.continue_exploration(
            model=model_name,
            use_history=use_history,
            **kwargs,
        ):
            yield result

    async def run(self, content, output_variables: Optional[list] = None, **kwargs):
        start_time = time.perf_counter()

        # Pass the debug mode parameter to Executor
        debug_mode = kwargs.get("debug_mode", False)
        break_on_start = kwargs.get("break_on_start", False)
        break_at = kwargs.get("break_at", None)
        self.executor = Executor(
            context=self.context,
            debug_mode=debug_mode,
            break_on_start=break_on_start,
            break_at=break_at,
        )
        # expose debug controller for post-mortem if present
        try:
            self._debug_controller = getattr(self.executor, "debug_controller", None)
        except Exception:
            self._debug_controller = None
 
        async for result in self.executor.run(
            content, output_variables=output_variables, **kwargs
        ):
            yield result
        end_time = time.perf_counter()
        self.context.debug(f"Time taken: {end_time - start_time} seconds")

    async def run_and_get_result(
        self, content, output_variables: Optional[list] = None, **kwargs
    ):
        start_time = time.perf_counter()

        start_time = time.perf_counter()
        # Pass the debug mode parameter to Executor
        debug_mode = kwargs.get("debug_mode", False)
        break_on_start = kwargs.get("break_on_start", False)
        break_at = kwargs.get("break_at", None)
        self.executor = Executor(
            context=self.context,
            debug_mode=debug_mode,
            break_on_start=break_on_start,
            break_at=break_at,
        )
        # expose debug controller for post-mortem if present
        try:
            self._debug_controller = getattr(self.executor, "debug_controller", None)
        except Exception:
            self._debug_controller = None
 
        async for result in self.executor.run_and_get_result(
            content, output_variables=output_variables, **kwargs
        ):
            yield result
        end_time = time.perf_counter()
        self.context.debug(f"Time taken: {end_time - start_time} seconds")

    def _prepare_for_run(self, **kwargs):
        # Only set skills if not already set (to preserve agent skills set by Environment)
        if self.context.is_skillkit_empty():
            # Try to get all skills including custom skills from global skills
            # If global_skills has getAllSkills method, use it; otherwise fall back to installed skills
            if hasattr(self.global_skills, "getAllSkills") and callable(
                getattr(self.global_skills, "getAllSkills")
            ):
                all_skills = self.global_skills.getAllSkills()
                self.context.set_skills(all_skills)
            else:
                installed_skills = self.global_skills.getInstalledSkills()
                self.context.set_skills(installed_skills)

        if KEY_USER_ID in kwargs:
            self.context.set_variable(name=KEY_USER_ID, value=kwargs.get(KEY_USER_ID))

        if KEY_SESSION_ID in kwargs:
            self.context.set_variable(
                name=KEY_SESSION_ID, value=kwargs.get(KEY_SESSION_ID)
            )

        if KEY_MAX_ANSWER_CONTENT_LENGTH in kwargs:
            self.context.set_variable(
                name=KEY_MAX_ANSWER_CONTENT_LENGTH,
                value=kwargs.get(KEY_MAX_ANSWER_CONTENT_LENGTH),
            )

    def shutdown(self):
        """
        Gracefully shutdown the DolphinExecutor and its components.
        """
        pass

    def get_execution_trace(self, title=None):
        """Generate and return execution trace information for the current execution context.

        Args:
            title (str, optional): Trace title. If not provided, use the default title.

        Returns:
            str: Execution trace information (text/JSON string) containing call_chain and LLM details.
        """
        trace_data = self.context.get_execution_trace(title)

        # If the lower layer has already returned a string, pass it through directly.
        if isinstance(trace_data, str):
            return trace_data

        # Default conversion to JSON text, ensuring that the upper layer writing files is str
        try:
            import json

            return json.dumps(trace_data, ensure_ascii=False, indent=2)
        except Exception:
            # Fallback: use repr when not serializable to avoid throwing errors again
            return repr(trace_data)

    @property
    def debug_controller(self):
        """Expose a debug controller instance for post-mortem.

        Priority:
        - Controller captured from the last execution step/run (coroutine path)
        - Controller from the currently bound low-level Executor (run path)
        """
        if self._debug_controller is not None:
            return self._debug_controller
        try:
            return getattr(self.executor, "debug_controller", None)
        except Exception:
            return None

    # Backward compatibility: retain old method names
    def get_profile(self, title=None):
        """[Deprecated] Please use get_execution_trace() instead"""
        import warnings
        warnings.warn("get_profile() 已废弃，请使用 get_execution_trace()", DeprecationWarning, stacklevel=2)
        return self.get_execution_trace(title)

    # === Exception handling helper ===
    def _handle_execution_exception(
        self,
        e: Exception,
        frame,
        block_pointer: int,
    ):
        """Unified handler for execution exceptions (UserInterrupt, ToolInterrupt, others).

        Args:
            e: The exception to handle
            frame: Current execution frame
            block_pointer: Current block pointer position

        Returns:
            StepResult if interrupt was handled, None if exception should be re-raised
        """
        import traceback
        from dolphin.core.utils.tools import ToolInterrupt
        from dolphin.core.common.exceptions import UserInterrupt
        from dolphin.core.coroutine.execution_frame import FrameStatus, WaitReason
        from dolphin.core.coroutine.step_result import StepResult
        from dolphin.core.coroutine import ResumeHandle

        # Handle user interruption (user actively interrupted execution)
        if isinstance(e, UserInterrupt):
            frame.status = FrameStatus.WAITING_FOR_INTERVENTION
            frame.wait_reason = WaitReason.USER_INTERRUPT
            # *** FIX: Update block_pointer to current block before saving snapshot ***
            # This ensures resume will continue from the interrupted block, not restart from beginning
            frame.block_pointer = block_pointer
            self.state_registry.update_frame(frame)  # Save updated pointer
            intervention_snapshot_id = self._save_frame_snapshot(frame)
            frame.error = {
                "error_type": "UserInterrupt",
                "message": str(e),
                "at_block": block_pointer,
                "intervention_snapshot_id": intervention_snapshot_id,
            }
            return StepResult.user_interrupted(
                resume_handle=ResumeHandle.create_user_interrupt_handle(
                    frame_id=frame.frame_id,
                    snapshot_id=intervention_snapshot_id,
                    current_block=block_pointer,
                ),
                result={"partial_output": self.context.get_user_variables()},
            )

        # Handle tool interruption (tool requested user input)
        if isinstance(e, ToolInterrupt):
            frame.status = FrameStatus.WAITING_FOR_INTERVENTION
            frame.wait_reason = WaitReason.TOOL_REQUEST
            # *** FIX: Update block_pointer to current block before saving snapshot ***
            # This ensures resume will continue from the interrupted block, not restart from beginning
            frame.block_pointer = block_pointer
            self.state_registry.update_frame(frame)  # Save updated pointer
            intervention_snapshot_id = self._save_frame_snapshot(frame)
            frame.error = {
                "error_type": "ToolInterrupt",
                "message": str(e),
                "tool_name": getattr(e, "tool_name", ""),
                "tool_args": getattr(e, "tool_args", []),
                "tool_config": getattr(e, "tool_config", {}),
                "at_block": block_pointer,
                "intervention_snapshot_id": intervention_snapshot_id,
            }
            return StepResult.interrupted(
                resume_handle=ResumeHandle.create_handle(
                    frame_id=frame.frame_id,
                    snapshot_id=intervention_snapshot_id,
                )
            )

        # Other errors: mark failed and return None to signal re-raise
        frame.status = FrameStatus.FAILED
        error_snapshot_id = self._save_frame_snapshot(frame)
        frame.error = {
            "error_type": type(e).__name__,
            "message": str(e),
            "stack": traceback.format_exc(),
            "at_block": block_pointer,
            "error_snapshot_id": error_snapshot_id,
        }
        return None  # Caller should re-raise the exception

    # === Added coroutine methods ===
    async def start_coroutine(self, content, **kwargs):
        """Starts a resumable execution"""
        from dolphin.core.coroutine import ExecutionFrame

        self._prepare_for_run(**kwargs)

        # 1. Create an execution frame and save the original content
        frame = ExecutionFrame.create_root_frame()
        frame.original_content = content

        # Save debug-related parameters to the execution frame (as part of the execution context)
        frame.debug_mode = kwargs.get("debug_mode", False)
        frame.break_on_start = kwargs.get("break_on_start", False)
        frame.break_at = kwargs.get("break_at", None)
 
        # 2. Initialize context and create snapshot
        snapshot = self._create_snapshot(frame.frame_id)
        frame.context_snapshot_id = snapshot.snapshot_id

        # 3. Register to the state manager
        self.state_registry.register_frame(frame)
        self.snapshot_store.save_snapshot(snapshot)

        # 4. Record the currently active coroutine
        self._current_frame_id = frame.frame_id

        return frame

    async def step_coroutine(self, frame_id: str):
        """Execute one step and return a unified StepResult.

        Returns:
            StepResult: Unified execution result, containing status and optional result data/restore handle.
                - StepResult.running(): Still executing.
                - StepResult.completed(result): Execution completed, contains final result.
                - StepResult.interrupted(handle): Tool interrupted, contains restore handle.
        """
        import traceback
        from dolphin.core.coroutine.execution_frame import FrameStatus
        from dolphin.core.coroutine.step_result import StepResult

        # 1. Get frame and restore context
        frame = self.state_registry.get_frame(frame_id)
        if not frame:
            raise ValueError(f"Frame not found: {frame_id}")

        snapshot = self.snapshot_store.load_snapshot(frame.context_snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {frame.context_snapshot_id}")

        self._restore_context(snapshot)

        try:
            # 2. Get the parsed blocks (cached in the frame or re-parsed)
            blocks = self._get_or_parse_blocks(frame)

            # 3. Execute single step (read debug configuration from frame)
            executor = Executor(
                context=self.context,
                step_mode=True,
                debug_mode=frame.debug_mode,
                break_on_start=frame.break_on_start,
                break_at=frame.break_at,
            )
            # capture debug controller for post-mortem access
            try:
                self._debug_controller = getattr(executor, "debug_controller", None)
            except Exception:
                self._debug_controller = None
 
            step_info = None

            async for result in executor.run_step(blocks, frame.block_pointer):
                if isinstance(result, tuple) and len(result) == 2:
                    # This is the step completion information
                    step_info = result

            new_pointer, is_complete = (
                step_info if step_info else (frame.block_pointer, True)
            )

            # 4. Update Status
            frame.block_pointer = new_pointer

            if is_complete:
                frame.status = FrameStatus.COMPLETED

            # 5. Save State
            self._save_frame_snapshot(frame)

            # 6. Return the completion status and result variables
            if is_complete:
                # Return user-defined variables as results (excluding internal variables)
                return StepResult.completed(result=self.context.get_user_variables())
            else:
                return StepResult.running()

        except Exception as e:
            result = self._handle_execution_exception(e, frame, frame.block_pointer)
            if result is not None:
                return result
            raise e

    async def run_coroutine(self, frame_id: str, progress_callback=None):
        """Execute continuously until interrupted or completed

        Returns:
            StepResult: Unified execution result
                - StepResult.completed(result): Execution completed, containing final result
                - StepResult.interrupted(handle): Tool interrupted, containing recovery handle

                Semantics:
                - Execute subsequent blocks sequentially starting from the current frame's block_pointer
                - If ToolInterrupt is triggered during execution, save an interrupt snapshot and return interrupt status
                - If all blocks are executed, save a completion snapshot and return completion status

        Note:
                - Unlike step_coroutine, this method does not save snapshots at the end of each block; it saves only once at "interrupt/completion"
        """
        import traceback
        from dolphin.core.coroutine.execution_frame import FrameStatus
        from dolphin.core.coroutine.step_result import StepResult

        # 1. Get frame and restore context
        frame = self.state_registry.get_frame(frame_id)
        if not frame:
            raise ValueError(f"Frame not found: {frame_id}")

        snapshot = self.snapshot_store.load_snapshot(frame.context_snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {frame.context_snapshot_id}")

        self._restore_context(snapshot)

        try:
            # 2. Get the parsed blocks (cached in the frame or re-parsed)
            blocks = self._get_or_parse_blocks(frame)

            # 3. Execute continuously until interrupted or completed (read debug configuration from frame)
            executor = Executor(
                context=self.context,
                step_mode=False,
                debug_mode=frame.debug_mode,
                break_on_start=frame.break_on_start,
                break_at=frame.break_at,
            )
            # capture debug controller for post-mortem access
            try:
                self._debug_controller = getattr(executor, "debug_controller", None)
            except Exception:
                self._debug_controller = None

            pointer = frame.block_pointer
            while pointer < len(blocks):
                current_block = blocks[pointer]
                try:
                    # Pass through and consume the progress items (dict/[]/strings, etc.) generated by block
                    # If progress_callback is provided, it will be called once for each progress item generated.
                    async for resp in executor.blocks_act([current_block]):
                        if progress_callback is not None:
                            try:
                                progress_callback(resp)
                            except Exception:
                                # Callbacks should not affect the main execution flow
                                pass
                except Exception as e:
                    result = self._handle_execution_exception(e, frame, pointer)
                    if result is not None:
                        return result
                    raise e

                # The current block has completed normally, advance the pointer
                pointer += 1

            # 4. Completed: Update pointers and state, save snapshot only here
            frame.block_pointer = pointer
            frame.status = FrameStatus.COMPLETED
            self._save_frame_snapshot(frame)

            # Returns the completion status
            return StepResult.completed(result=self.context.get_user_variables())

        except Exception as e:
            # Fallback exception handling (theoretically handled in inner loop)
            result = self._handle_execution_exception(e, frame, frame.block_pointer)
            if result is not None:
                return result
            raise e

    async def pause_coroutine(self, frame_id: str):
        """Pause execution"""
        from dolphin.core.coroutine import ResumeHandle
        from dolphin.core.coroutine.execution_frame import FrameStatus

        frame = self.state_registry.get_frame(frame_id)
        if not frame:
            raise ValueError(f"Frame not found: {frame_id}")

        frame.status = FrameStatus.PAUSED
        self.state_registry.update_frame(frame)

        return ResumeHandle.create_handle(
            frame_id=frame_id, snapshot_id=frame.context_snapshot_id
        )

    async def resume_coroutine(self, handle, updates=None):
        """Resume execution, and optionally inject updated data into the context"""
        from dolphin.core.coroutine.execution_frame import FrameStatus

        # 1. Get frame
        frame = self.state_registry.get_frame(handle.frame_id)
        if not frame:
            raise ValueError(f"Frame not found: {handle.frame_id}")

        # Check if recovery is from tool interruption
        is_intervention_resume = frame.status == FrameStatus.WAITING_FOR_INTERVENTION

        # 2. Restore context from snapshot
        snapshot = self.snapshot_store.load_snapshot(handle.snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {handle.snapshot_id}")

        self._restore_context(snapshot)

        # 3. Processing Data Injection
        if updates:
            # Apply updates data
            for key, value in updates.items():
                self.context.set_variable(key, value)

        # 4. Special handling for interrupt recovery
        if is_intervention_resume:
            from dolphin.core.coroutine.execution_frame import WaitReason
            
            # Handle user interruption (UserInterrupt)
            if frame.wait_reason == WaitReason.USER_INTERRUPT:
                # If there is new user input provided via updates, inject it as a message
                if updates and "__user_interrupt_input__" in updates:
                    user_input = updates.pop("__user_interrupt_input__")
                    # Use the convenient method to add user message
                    self.context.add_user_message(user_input, bucket="conversation_history")
                    logger.info(f"UserInterrupt resume: injected user input of length {len(user_input)}")
                
                # Clean up status once handled
                frame.wait_reason = None
                frame.error = None
                
            # Handle tool interruption (ToolInterrupt)
            elif frame.error and "tool_name" in frame.error:
                tool_name = frame.error["tool_name"]
                tool_args = frame.error.get("tool_args", [])

                # If there are tools to recover data, set them to the context
                if updates and "tool_result" in updates:
                    self.context.set_variable("tool_result", updates["tool_result"])

                # Clean up error messages, as the interruption has been resolved
                frame.error = None

        # 5. Create new snapshot (if updated)
        if updates or is_intervention_resume:
            self._save_frame_snapshot(frame)

        # 6. Set the frame status to RUNNING and save
        frame.status = FrameStatus.RUNNING
        self.state_registry.update_frame(frame)

        return frame

    async def terminate_coroutine(self, frame_id: str, terminate_children: bool = True):
        """Terminate execution frame tree

        Args:
            frame_id: The ID of the frame to terminate
            terminate_children: Whether to terminate all child frames as well, default is True

        Returns:
            The terminated frame

        Raises:
            ValueError: If the frame does not exist
        """
        from dolphin.core.coroutine.execution_frame import FrameStatus

        # 1. Get frame
        frame = self.state_registry.get_frame(frame_id)
        if not frame:
            raise ValueError(f"Frame not found: {frame_id}")

        # 2. Terminate all subframes (if needed)
        if terminate_children and frame.children:
            for child_id in frame.children:
                try:
                    await self.terminate_coroutine(child_id, terminate_children=True)
                except ValueError:
                    # The subframe may no longer exist, ignore the error
                    pass

        # 3. Set frame status to TERMINATED
        frame.status = FrameStatus.TERMINATED
        frame.update_timestamp()

        # 4. Save frame state
        self.state_registry.update_frame(frame)

        return frame

    def _create_snapshot(self, frame_id: str):
        """Create context snapshot"""
        return self.context.export_runtime_state(frame_id)

    def _restore_context(self, snapshot):
        """Restore context from snapshot"""
        self.context.apply_runtime_state(snapshot)

    def _save_frame_snapshot(self, frame):
        """Create and save a context snapshot of the execution frame

        Args:
            frame: The execution frame to save a snapshot of

        Returns:
            str: The ID of the newly created snapshot
        """
        new_snapshot = self._create_snapshot(frame.frame_id)
        self.snapshot_store.save_snapshot(new_snapshot)
        frame.context_snapshot_id = new_snapshot.snapshot_id
        self.state_registry.update_frame(frame)
        return new_snapshot.snapshot_id

    def _get_or_parse_blocks(self, frame):
        """Get or parse blocks"""
        content = frame.original_content
        if not content:
            return []

        executor = Executor(context=self.context)
        return executor.get_parsed_blocks(content)

    # === New High-Level API (for Multi-turn Dialogue Scenarios) ===

    async def append_incremental_message(self, payload: dict):
        """Append an incremental message to the current coroutine (utilizing prefix cache)

        Args:
            payload: State or event information (arbitrary structure), for example {"event_type": "...", "content": "...", "metadata": {...}}

                Design philosophy:
                - Messages history accumulates like a log, facilitating prefix cache
                - Each call appends only an incremental message
                - Synchronously updates the history variable in context, compatible with /explore/(history=true)
        """
        # Format as user message
        message_content = self._format_round_message(payload)

        # Append to messages (normal path, keep compatibility)
        self.context.add_user_message(message_content, bucket="conversation_history")

        # Update the history variable at the same time (for the old path /explore/(history=true))
        from dolphin.core.common.enums import Messages
        history_raw = self.context.get_history_messages(normalize=False)

        # Convert to list format if needed (handle different return types)
        if history_raw is None:
            history_list = []
        elif isinstance(history_raw, Messages):
            # Convert Messages object to list of dicts
            history_list = history_raw.get_messages_as_dict()
        elif isinstance(history_raw, list):
            history_list = history_raw
        else:
            logger.warning(f"Unexpected history type: {type(history_raw)}, initializing as empty list")
            history_list = []

        history_list.append({"role": MessageRole.USER.value, "content": message_content})
        self.context.set_variable("history", history_list)

        # Update the snapshot of the current coroutine
        if hasattr(self, "_current_frame_id") and self._current_frame_id:
            frame = self.state_registry.get_frame(self._current_frame_id)
            if frame:
                self._save_frame_snapshot(frame)

    def _format_round_message(self, round_info: dict) -> str:
        """Format round information into message content"""
        import json

        # If the message field already exists, use it directly.
        if "message" in round_info:
            return round_info["message"]

        # Otherwise, convert the entire dict to JSON format
        return json.dumps(round_info, ensure_ascii=False, indent=2)

    async def inject_context(self, updates: dict):
        """Inject context variables (variable replacement mode) into the currently active coroutine.

                ⚠️ Note: This method creates a new snapshot and cannot utilize prefix cache
                ⚠️ For multi-turn conversation scenarios, append_round_message() is recommended

        Args:
            updates: Dictionary of variables to inject
        """
        if not hasattr(self, "_current_frame_id") or not self._current_frame_id:
            raise ValueError("没有活跃的协程")

        frame = self.state_registry.get_frame(self._current_frame_id)
        from dolphin.core.coroutine import ResumeHandle

        handle = ResumeHandle(frame.frame_id, frame.context_snapshot_id, "")
        await self.resume_coroutine(handle, updates=updates)

    async def step_current_coroutine(self):
        """Execute the next step of the currently active coroutine.

        Returns:
            Execution result (bool indicating whether completion is achieved, or ResumeHandle indicating interruption)

                Internal implementation:
                Calls step_coroutine(self._current_frame_id)
        """
        if not hasattr(self, "_current_frame_id") or not self._current_frame_id:
            raise ValueError("没有活跃的协程")

        return await self.step_coroutine(self._current_frame_id)

    def is_waiting_for_intervention(self) -> bool:
        """Check whether the current coroutine is waiting for an interrupt handler.

        Returns:
            bool: Whether it is waiting for an interrupt
        """
        if not hasattr(self, "_current_frame_id") or not self._current_frame_id:
            return False

        frame = self.state_registry.get_frame(self._current_frame_id)
        from dolphin.core.coroutine.execution_frame import FrameStatus

        return frame.status == FrameStatus.WAITING_FOR_INTERVENTION

    def get_intervention_data(self) -> dict:
        """Get interrupt data (such as tool call parameters)

        Returns:
            dict: Interrupt-related data
        """
        if not hasattr(self, "_current_frame_id") or not self._current_frame_id:
            raise ValueError("没有活跃的协程")

        frame = self.state_registry.get_frame(self._current_frame_id)
        if frame.error and frame.error.get("error_type") == "ToolInterrupt":
            return {
                "tool_name": frame.error.get("tool_name", ""),
                "tool_args": frame.error.get("tool_args", []),
                "at_block": frame.error.get("at_block", 0),
            }

        return {}

    def get_messages_range(self, start: int, end: int):
        """Read messages within the specified range (left-closed, right-open), indexed sequentially from the start of the session.

        Args:
            start: Starting index (inclusive)
            end: Ending index (exclusive)

        Returns:
            PlainMessages (list[dict]), each containing fields such as role/content
        """
        messages = self.context.get_messages()
        all_messages_dict = messages.get_messages_as_dict()  # Return PlainMessages

        # Ensure the index is within the valid range
        start = max(0, start)
        end = min(len(all_messages_dict), end)

        return all_messages_dict[start:end]

    def replace_messages_range(self, start: int, end: int, replacement):
        """Replace the [start, end) interval with replacement (a string or a single message).

        Note: The replacement will invalidate the prefix cache for this interval, and subsequent accumulation will continue from the new summary.
                When replacement is a str, it will be automatically wrapped as a user message; when it's a dict, it should include role/content.

        Args:
            start: starting index (inclusive)
            end: ending index (exclusive)
            replacement: string or message dictionary
        """
        from dolphin.core.common.enums import SingleMessage, MessageRole
        from datetime import datetime

        messages = self.context.get_messages()
        all_messages = messages.messages if hasattr(messages, "messages") else []

        # Ensure the index is within the valid range
        start = max(0, start)
        end = min(len(all_messages), end)

        # Handle replacement, convert to SingleMessage
        if isinstance(replacement, str):
            replacement_msg = SingleMessage(
                role=MessageRole.USER,
                content=replacement,
                timestamp=datetime.now().isoformat(),
            )
        elif isinstance(replacement, dict):
            role = replacement.get("role", MessageRole.USER)
            if isinstance(role, str):
                role = MessageRole(role)
            replacement_msg = SingleMessage(
                role=role,
                content=replacement.get("content", ""),
                timestamp=datetime.now().isoformat(),
            )
        elif isinstance(replacement, SingleMessage):
            replacement_msg = replacement
        else:
            raise ValueError(f"Invalid replacement type: {type(replacement)}")

        # Perform replacement
        all_messages[start:end] = [replacement_msg]

        # Update the snapshot of the current coroutine
        if hasattr(self, "_current_frame_id") and self._current_frame_id:
            frame = self.state_registry.get_frame(self._current_frame_id)
            if frame:
                self._save_frame_snapshot(frame)
