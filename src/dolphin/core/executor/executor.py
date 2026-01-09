import ast
import asyncio
import re
import traceback
from typing import Optional

from dolphin.core import flags
from dolphin.core.code_block.assign_block import AssignBlock
from dolphin.core.logging.logger import get_logger
from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.code_block.explore_block_v2 import ExploreBlockV2
from dolphin.core.code_block.judge_block import JudgeBlock
from dolphin.core.code_block.prompt_block import PromptBlock
from dolphin.core.code_block.tool_block import ToolBlock
from dolphin.core.common.enums import StreamItem, count_occurrences
from dolphin.core.common.constants import KEY_STATUS, KEY_PREVIOUS_STATUS
from dolphin.core.context.context import Context
from dolphin.core.parser.parser import Parser
from dolphin.core.utils.tools import ToolInterrupt


def split_by_multiple_prefixes(text, prefixes):
    # Initialize result list
    result = []
    # Current processing position
    current_pos = 0

    while current_pos < len(text):
        # Find the next closest delimiter position
        next_pos = len(text)
        found_prefix = None

        # Find all possible delimiters after the current position
        for prefix in prefixes:
            pos = text.find(prefix, current_pos + 1)  # +1 is to avoid repeated lookups at the current position
            if pos != -1 and pos < next_pos:
                next_pos = pos
                found_prefix = prefix

        # If the separator is found
        if found_prefix:
            # Add the current paragraph to the result.
            segment = text[current_pos:next_pos]
            if segment:  # Add only non-empty segments
                result.append(segment)
            current_pos = next_pos
        else:
            # If no more delimiters are found, add the remaining part.
            segment = text[current_pos:]
            if segment:  # Add only non-empty paragraphs
                result.append(segment)
            break

    return result


def split_and_join(string_list, int_list):
    result = []
    # Traverse split points
    for i in range(len(int_list)):
        start = int_list[i]
        # If it is the last split point, end equals the list length.
        if i == len(int_list) - 1:
            end = len(string_list)
        else:
            end = int_list[i + 1]
        # Concatenate the strings within this range.
        joined_str = "".join(string_list[start:end])
        result.append(joined_str)
    return result


class Executor:
    def __init__(
        self,
        context: Context,
        debug_info: Optional[dict] = None,
        breakpoint_infos: Optional[dict] = None,
        step_mode: bool = False,
        debug_mode: bool = False,
        break_on_start: bool = False,
        break_at: Optional[list] = None,
    ):
        self.context = context
        self.debug_info = debug_info
        self.breakpoint_infos = breakpoint_infos
        self.step_mode = step_mode  # Deprecated: kept for backward compatibility
        self.debug_mode = debug_mode  # Added: Whether to enable debug mode
        self.debug_controller = None

        # If debug mode is enabled, initialize the debug controller.
        if self.debug_mode:
            from dolphin.core.executor.debug_controller import DebugController

            self.debug_controller = DebugController(
                self.context,
                break_on_start=break_on_start,
                break_at=break_at,
            )
            self.debug_controller.enable_step_mode()

        self.logger = get_logger("executor")

        # Trajectory configuration: read from context attribute
        # If trajectorypath is specified, stage trajectory saving is automatically enabled
        self.trajectory_path = getattr(context, "trajectorypath", None)
        self.agent_name = getattr(context, "agent_name", "main")

        # Initialize trajectory recording
        if self.trajectory_path:
            self.context.init_trajectory(self.trajectory_path)

        self.parser = Parser(context=self.context)
        self.tool_block = ToolBlock(context=self.context)

        self.explore_block = (
            ExploreBlockV2(context=self.context)
            if flags.is_enabled(flags.EXPLORE_BLOCK_V2)
            else ExploreBlock(context=self.context)
        )

        self.judge_block = JudgeBlock(context=self.context)
        self.prompt_block = PromptBlock(context=self.context)
        self.assign_block = AssignBlock(context=self.context)


    def _increment_stage_counter(self, stage_name: str):
        """Only increment counters for the specified stage, without saving trajectories.

                Used for Blocks that need to manage trajectory saving themselves (e.g., ExploreBlock)

        Args:
            stage_name: Name of the stage, such as 'judge', 'tool', 'explore', etc.
        """
        status = self.context.get_var_value(KEY_STATUS)

        # Initialize status dict if None
        if status is None:
            status = {}

        counter_key = f"{stage_name}_time"

        # Initialize counter if it doesn't exist
        if counter_key not in status:
            status[counter_key] = 0

        status[counter_key] += 1
        self.context.set_variable(KEY_STATUS, status)

    def _save_stage_trajectory(self, stage_name: str):
        """Save stage trajectory to trajectory file

        Args:
            stage_name: Stage name, such as 'judge', 'tool', 'explore', etc.
        """
        if not self.context.trajectory:
            return

        try:
            status = self.context.get_var_value(KEY_STATUS) or {}
            counter_key = f"{stage_name}_time"
            stage_index = status.get(counter_key, 0)

            tools = self.context.skillkit.getSkillsSchema()

            # Get model name from context (set by ExploreBlock during llm_chat_stream)
            # Returns None if no model has been used yet in this session
            current_model = self.context.get_last_model_name()

            self.context.trajectory.finalize_stage(
                stage_name=stage_name,
                stage_index=stage_index,
                context_manager=self.context.context_manager,
                tools=tools,
                user_id=self.context.user_id or "",
                model=current_model,
            )
            self.logger.debug(f"Saved stage trajectory for {stage_name} (index: {stage_index})")
        except Exception as e:
            # Record errors without interrupting execution
            self.logger.warning(f"Failed to save stage trajectory for {stage_name}: {e}", exc_info=True)

    def _increment_and_save_stage(self, stage_name: str):
        """Increment the counter for the specified stage and save the stage trajectory.

                This is a convenient method that combines counter incrementing and trajectory saving.
                For Blocks that need to manage trajectory themselves (such as ExploreBlock),
                they can call _increment_stage_counter() only.

        Args:
            stage_name: Name of the stage, such as 'judge', 'tool', 'explore', etc.
        """
        self._increment_stage_counter(stage_name)
        self._save_stage_trajectory(stage_name)

    async def blocks_act(self, blocks):
        for block_index, action_block in enumerate(blocks):
            # Debug mode: check whether pause is needed
            if self.debug_controller and self.debug_controller.should_pause_at_block(
                block_index
            ):
                if not await self.debug_controller.pause_and_wait_for_input(
                    block_index, action_block
                ):
                    # User exits debugging, stops execution
                    return
            previous_status = self.context.get_var_value(KEY_PREVIOUS_STATUS)
            status = self.context.get_var_value(KEY_STATUS)

            # Check if status variables are None and reinitialize if needed
            if status is None:
                status = {
                    "tool_time": 0,
                    "judge_time": 0,
                    "prompt_time": 0,
                    "explore_time": 0,
                    "assign_time": 0,
                }
                self.context.set_variable(KEY_STATUS, status)
            else:
                # Ensure all required keys exist in status dict
                required_keys = ["tool_time", "judge_time", "prompt_time", "explore_time", "assign_time"]
                for key in required_keys:
                    if key not in status:
                        status[key] = 0
                self.context.set_variable(KEY_STATUS, status)

            if previous_status is None:
                previous_status = {
                    "tool_time": 0,
                    "judge_time": 0,
                    "prompt_time": 0,
                    "explore_time": 0,
                    "assign_time": 0,
                }
                self.context.set_variable(KEY_PREVIOUS_STATUS, previous_status)
            else:
                # Ensure all required keys exist in previous_status dict
                required_keys = ["tool_time", "judge_time", "prompt_time", "explore_time", "assign_time"]
                for key in required_keys:
                    if key not in previous_status:
                        previous_status[key] = 0
                self.context.set_variable(KEY_PREVIOUS_STATUS, previous_status)

            if action_block[0] == "if":
                async for resp in self.ifelse_block(action_block[1]):
                    yield resp
            elif action_block[0] == "for":
                async for resp in self.for_block(action_block[1]):
                    yield resp
            elif action_block[0] == "judge":
                if (
                    self.step_mode
                    or status["judge_time"] >= previous_status["judge_time"]
                ):
                    async for resp in self.judge_block.execute(action_block[1]):
                        yield resp
                    self._increment_and_save_stage("judge")
            elif action_block[0] == "tool":
                if (
                    self.step_mode
                    or status["tool_time"] >= previous_status["tool_time"]
                ):
                    async for resp in self.tool_block.execute(action_block[1]):
                        yield resp
                    self._increment_and_save_stage("tool")
            elif action_block[0] == "explore":
                if (
                    self.step_mode
                    or status["explore_time"] >= previous_status["explore_time"]
                ):
                    async for resp in self.explore_block.execute(action_block[1]):
                        yield resp
                    # ExploreBlock saves trajectory itself in _update_history_and_cleanup()
                    # Here we only increment the counter to avoid saving repeatedly
                    self._increment_stage_counter("explore")
            elif action_block[0] == "prompt":
                if (
                    self.step_mode
                    or status["prompt_time"] >= previous_status["prompt_time"]
                ):
                    async for resp in self.prompt_block.execute(action_block[1]):
                        yield resp
                    self._increment_and_save_stage("prompt")
            elif action_block[0] == "assign":
                if (
                    self.step_mode
                    or status["assign_time"] >= previous_status["assign_time"]
                ):
                    async for resp in self.assign_block.execute(action_block[1]):
                        yield resp
                    self._increment_and_save_stage("assign")
            elif action_block[0] == "parallel":
                async for resp in self.parallel_block(action_block[1]):
                    yield resp

    async def ifelse_block(self, content):
        pre = ["/if/", "elif", "/for/", "/parallel/", "else", "/end/"]
        split_result = split_by_multiple_prefixes(content, pre)
        count = 1
        elif_list = []
        else_list = []
        for i in range(1, len(split_result)):
            if split_result[i].startswith("/if/"):
                count += 1
            elif split_result[i].startswith("elif"):
                if count == 1:
                    elif_list.append(i)
            elif split_result[i].startswith("else"):
                if count == 1:
                    else_list.append(i)
            elif split_result[i].startswith("/end/"):
                count -= 1
            elif split_result[i].startswith("/for/"):
                count += 1
            elif split_result[i].startswith("/parallel/"):
                count += 1
        join_list = [0] + elif_list + else_list
        join_str_list = split_and_join(split_result, join_list)
        join_str_list[-1] = join_str_list[-1][:-5]
        ifelse_list = []
        try:
            for i in range(len(join_str_list)):
                join_str = join_str_list[i]
                condition, action = join_str_list[i].split(":", 1)
                condition = condition.strip()
                action = action.strip()
                ifelse_list.append((condition, action))
        except Exception:
            raise Exception(
                f"Syntax Error({content})，check the '/if/','elif','else','/end/'"
            )
        variables = self.context.get_all_variables_values()
        for condition, action in ifelse_list:
            if condition[:4] == "/if/" or condition[:4] == "elif":
                result = eval(condition[4:].replace("$", ""), globals(), variables)
                if result:
                    action_blocks = self.parser.parse(self, action)
                    async for resp in self.blocks_act(action_blocks):
                        yield resp
                    break
            else:
                action_blocks = self.parser.parse(self, action)
                async for resp in self.blocks_act(action_blocks):
                    yield resp

    async def for_block(self, content):
        content = content[:-5]
        pattern = r"/for/\s*\$(\s*[^ ]+)\s*in\s*\$(\s*[^:]+)\s*:"

        match = re.search(pattern, content)
        if match:
            var_temp_name = match.group(1).strip()
            var_loop_name = match.group(2).strip()
            loop_obj = self.context.get_var_value(var_loop_name)

            try:
                # Compatibility: allow looping over prompt/skill result objects
                if isinstance(loop_obj, list):
                    lst = loop_obj
                elif isinstance(loop_obj, StreamItem):
                    if isinstance(loop_obj.output_var_value, list):
                        lst = loop_obj.output_var_value
                    elif isinstance(loop_obj.answer, str) and loop_obj.answer.startswith("[") and loop_obj.answer.endswith("]"):
                        lst = ast.literal_eval(loop_obj.answer)
                    else:
                        raise TypeError("Variable is not a list.")
                elif isinstance(loop_obj, dict):
                    # Duck-typing compatibility for prompt/skill result dicts:
                    # accept only if it carries an iterable result payload.
                    if isinstance(loop_obj.get("output_var_value"), list):
                        lst = loop_obj.get("output_var_value")
                    elif isinstance(loop_obj.get("answer"), list):
                        lst = loop_obj.get("answer")
                    elif (
                        isinstance(loop_obj.get("answer"), str)
                        and loop_obj.get("answer").startswith("[")
                        and loop_obj.get("answer").endswith("]")
                    ):
                        lst = ast.literal_eval(loop_obj.get("answer"))
                    else:
                        raise TypeError("Variable is not a list.")
                elif (
                    isinstance(loop_obj, str)
                    and loop_obj.startswith("[")
                    and loop_obj.endswith("]")
                ):
                    lst = ast.literal_eval(loop_obj)
                else:
                    raise TypeError("Variable is not a list.")
            except Exception as e:
                raise TypeError(
                    f"Syntax Error for loop variable ${var_loop_name}({loop_obj}), error: {e}"
                )

            for i, element in enumerate(lst):
                self.context.set_variable(var_temp_name, element)
                action_blocks = self.parser.parse(
                    self, ":".join(content.split(":")[1:])
                )
                async for resp in self.blocks_act(action_blocks):
                    yield resp

    async def parallel_block(self, content):
        content = content[10:-5]
        action_blocks = self.parser.parse(self, content)

        # Create a list of asynchronous generator objects
        tasks = []
        for i in range(len(action_blocks)):
            tasks.append(("task" + str(i + 1), self.blocks_act([action_blocks[i]])))
        active_generators = list(tasks)

        # Loop until all generators are complete
        while active_generators:
            # Create the task for the current iteration
            current_tasks = []

            for name, gen in active_generators:
                # Create a task to get the next value for each generator
                current_tasks.append((name, asyncio.create_task(gen.__anext__())))

            # Wait for all tasks to complete the current iteration
            await asyncio.sleep(0)

            # Process results and update the active generator list
            next_active = []
            for (name, gen), (_, task_obj) in zip(active_generators, current_tasks):
                try:
                    result = await task_obj
                    if result is not None:
                        yield ""
                        next_active.append((name, gen))
                    else:
                        # Generator has completed
                        yield ""
                except StopAsyncIteration:
                    # Generator has completed
                    yield ""

            active_generators = next_active
            yield ""
        yield ""

    def _preparation(self, content):
        # remove comment
        uncommented_content = self.parser.remove_comment(content)
        # Split the string into a list by lines
        lines = uncommented_content.splitlines()

        # Filter out lines that start with 'import'
        filtered_lines = [
            line.lstrip() for line in lines if not line.strip().startswith("import")
        ]

        # Reconstruct the filtered lines into a string
        content_new = "\n".join(filtered_lines)
        # Split only the outermost blocks
        num0 = count_occurrences(["/if/", "/for/", "/parallel"], content_new)
        num1 = count_occurrences(["/end/"], content_new)
        if num0 != num1:
            raise Exception(
                f"Syntax Error({content})，check the '/if/','/for/','/end/'"
            )
        # State Initialization
        # Check if this is an interrupt recovery scenario by looking for intervention markers
        is_interrupt_recovery = (
            self.context.get_var_value("intervention_tool_block_vars") is not None
            or self.context.get_var_value("intervention_judge_block_vars") is not None
            or self.context.get_var_value("intervention_explore_block_vars") is not None
        ) and self.context.get_var_value("tool") is not None
        
        if self.context.get_var_value(KEY_STATUS):
            previous_status = self.context.get_var_value(KEY_STATUS)
            if isinstance(previous_status, dict) and all(
                key in previous_status
                for key in [
                    "tool_time",
                    "judge_time",
                    "prompt_time",
                    "explore_time",
                    "assign_time",
                ]
            ):
                if is_interrupt_recovery:
                    # In interrupt recovery scenario, keep status unchanged
                    # and set previous_status to 0 so all blocks will execute
                    self.context.set_variable(
                        KEY_PREVIOUS_STATUS,
                        {
                            "tool_time": 0,
                            "judge_time": 0,
                            "prompt_time": 0,
                            "explore_time": 0,
                            "assign_time": 0,
                        },
                    )
                    # Keep the existing status (don't reset it)
                else:
                    # Normal scenario: save current status as previous_status
                    self.context.set_variable(KEY_PREVIOUS_STATUS, previous_status)
                    # Reset status to 0 for new execution
                    self.context.set_variable(
                        KEY_STATUS,
                        {
                            "tool_time": 0,
                            "judge_time": 0,
                            "prompt_time": 0,
                            "explore_time": 0,
                            "assign_time": 0,
                        },
                    )
            else:
                self.context.set_variable(
                    KEY_PREVIOUS_STATUS,
                    {
                        "tool_time": 0,
                        "judge_time": 0,
                        "prompt_time": 0,
                        "explore_time": 0,
                        "assign_time": 0,
                    },
                )
                self.context.set_variable(
                    KEY_STATUS,
                    {
                        "tool_time": 0,
                        "judge_time": 0,
                        "prompt_time": 0,
                        "explore_time": 0,
                        "assign_time": 0,
                    },
                )
        else:
            self.context.set_variable(
                KEY_PREVIOUS_STATUS,
                {
                    "tool_time": 0,
                    "judge_time": 0,
                    "prompt_time": 0,
                    "explore_time": 0,
                    "assign_time": 0,
                },
            )
            self.context.set_variable(
                KEY_STATUS,
                {
                    "tool_time": 0,
                    "judge_time": 0,
                    "prompt_time": 0,
                    "explore_time": 0,
                    "assign_time": 0,
                },
            )

        return self.parser.parse(self, content_new)

    def _clean_up(self):
        self.context.delete_variable(KEY_PREVIOUS_STATUS)
        self.context.delete_variable(KEY_STATUS)

    async def run(self, content, output_variables: list[str] = [], **kwargs):
        blocks = self._preparation(content)
        # Precompute output_variables conditions to avoid checking them in each iteration
        should_filter = output_variables is not None and len(output_variables) > 0

        try:
            # Execute all blocks, blocks_act will generate the result of each block and return it streamingly.
            async for resp in self.blocks_act(blocks):
                # Return the result based on the precomputed condition
                if should_filter:
                    # Return only the specified variables using the efficient get_variables method
                    filtered_variables = self.context.get_variables_values(
                        output_variables
                    )
                    yield filtered_variables
                else:
                    # Return all variables
                    yield self.context.get_all_variables()
        except ToolInterrupt:
            # Similarly return the filtered variables when interrupted
            if should_filter:
                filtered_variables = self.context.get_variables_values(output_variables)
                yield filtered_variables
            else:
                yield self.context.get_all_variables()
            raise
        finally:
            self._clean_up()

    async def run_and_get_result(self, content, **kwargs):
        blocks = self._preparation(content)
        try:
            async for resp in self.blocks_act(blocks):
                yield resp
        except ToolInterrupt:
            raise Exception(f"ToolInterrupt traceback[{traceback.format_exc()}]")
        except Exception as e:
            raise Exception(
                f"Tool block execution failed: {str(e)} traceback[{traceback.format_exc()}]"
            )
        finally:
            self._clean_up()

    async def run_step(self, blocks, block_pointer: int):
        """Execute a single step, return (new pointer position, whether completed)"""

        if block_pointer >= len(blocks):
            yield (block_pointer, True)
            return

        # Execute the current block
        current_block = blocks[block_pointer]
        async for result in self.blocks_act([current_block]):
            yield result

        # Return step completion information
        new_pointer = block_pointer + 1
        is_complete = new_pointer >= len(blocks)
        yield (new_pointer, is_complete)

    def get_parsed_blocks(self, content: str):
        """Get parsed blocks (cache mechanism)"""
        return self._preparation(content)
