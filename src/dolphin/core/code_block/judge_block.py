import traceback
from typing import Any, Optional, AsyncGenerator

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.context.context import Context
from dolphin.core.llm.llm_client import LLMClient
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.context.var_output import SourceType


class JudgeBlock(BasicCodeBlock):
    def __init__(self, context: Context, debug_infos=None):
        super().__init__(context)

        self.llm_client = LLMClient(self.context)
        self.debug_info = debug_infos

    async def judge_tool_call(
        self,
        judge_str: Optional[str],
        system_prompt: Optional[str],
        tools_list: Optional[list[str]],
        model: Optional[str] = None,
        history: Optional[bool] = None,
        ttc_mode: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[dict]]:
        """Using LLM's function calling capability for tool selection"""
        # Save original attributes
        original_content = self.content
        original_system_prompt = getattr(self, "system_prompt", None)
        original_skills = getattr(self, "skills", None)
        original_model = getattr(self, "model", None)
        original_history = getattr(self, "history", None)
        original_ttc_mode = getattr(self, "ttc_mode", None)

        try:
            # Temporarily set attributes to adapt to llm_chat
            self.content = judge_str
            self.system_prompt = system_prompt or ""
            self.skills = tools_list
            self.model = model
            self.history = history
            self.ttc_mode = ttc_mode

            # Get tool list and skillkit information
            available_skill_names = [
                str(name) for name in self.get_skillkit().getSkillNames()
            ]

            # To ensure the LLM prioritizes using tools, add an explicit system prompt
            original_system_prompt = self.system_prompt
            if available_skill_names:
                tool_instruction = f"You have access to these tools: {', '.join(available_skill_names)}. Please use the appropriate tool if it can help complete the task."
                if self.system_prompt:
                    self.system_prompt = f"{self.system_prompt}\n\n{tool_instruction}"
                else:
                    self.system_prompt = tool_instruction

            # Call llm_chat with_skill=True to enable early stopping for tool calling
            func_name: Optional[str] = None
            func_args: Optional[dict[str, Any]] = None

            async for item in self.llm_chat(
                "judge", with_skill=True, early_stop_on_tool_call=True
            ):
                # Check if a complete tool invocation exists (arguments not being None indicates that parameters have been fully parsed)
                if isinstance(item, dict) and "tool_call" in item and item["tool_call"]:
                    assert isinstance(item["tool_call"], dict), (
                        "tool_call is not a dict"
                    )

                    tool_call = item["tool_call"]
                    func_name = tool_call["name"]
                    func_args = tool_call[
                        "arguments"
                    ]  # None indicates incomplete, dict indicates complete parameters

                    # If arguments is not None, it indicates that the tool invocation is complete.
                    if func_args is not None:
                        break

            # If no complete tool invocation is detected, use the default value.
            if func_args is None:
                func_args = {}

            self.context.debug(
                f"judge_tool_call[{self.output_var}] [{judge_str}] tool_name[{func_name}] tool_args[{func_args}]"
            )

            return func_name, func_args

        except Exception as e:
            raise Exception(f"(Judge Block) judge_tool_call failed: {str(e)}")

        finally:
            # Restore original attributes
            self.content = original_content
            self.system_prompt = original_system_prompt  # Here the state will be restored to the previous state before modification.
            self.skills = original_skills
            self.model = original_model
            self.history = original_history
            self.ttc_mode = original_ttc_mode

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.JUDGE,
        replace_variables=True,
    ) -> AsyncGenerator[Any, None]:
        # Execute the parent class logic
        async for _ in super().execute(content, category, replace_variables):
            pass

        self.block_start_log("judge")

        assert self.recorder, "recorder is None"

        try:
            gvpool_all_keys = self.context.get_all_variables().keys()
            if (
                "intervention_judge_block_vars" in gvpool_all_keys
                and "tool" in gvpool_all_keys
            ):
                intervention_vars = self.context.get_var_value(
                    "intervention_judge_block_vars"
                )
                assert intervention_vars is not None, "intervention_vars is None"

                tool_name = intervention_vars["tool_name"]
                judge_call_info = intervention_vars["judge_call_info"]

                self.recorder.set_output_var(
                    judge_call_info["assign_type"], judge_call_info["output_var"]
                )

                self.context.delete_variable("intervention_judge_block_vars")

                input_dict = self.context.get_var_value("tool")
                assert input_dict is not None, "input_dict is None"

                new_tool_name = input_dict["tool_name"]
                assert new_tool_name == tool_name, (
                    "(judge_block) new_tool_name 和中断之前的 tool_name不一致"
                )

                raw_tool_args = input_dict["tool_args"]
                new_tool_args = {arg["key"]: arg["value"] for arg in raw_tool_args}

                props = {"intervention": False, "gvp": self.context}
                
                # *** Handle skip action ***
                skip_tool = self.context.get_var_value("__skip_tool__")
                skip_message = self.context.get_var_value("__skip_message__")
                
                # Clean up skip flags
                if skip_tool:
                    self.context.delete_variable("__skip_tool__")
                if skip_message:
                    self.context.delete_variable("__skip_message__")
                
                self.context.delete_variable("tool")

                # If user chose to skip, don't execute the tool
                if skip_tool:
                    # Generate friendly skip message
                    params_str = ", ".join([f"{k}={v}" for k, v in new_tool_args.items()])
                    default_skip_msg = f"Tool '{tool_name}' was skipped by user"
                    if skip_message:
                        skip_response = f"[SKIPPED] {skip_message}"
                    else:
                        skip_response = f"[SKIPPED] {default_skip_msg} (parameters: {params_str})"
                    
                    yield {"answer": skip_response}
                else:
                    # Normal execution (not skipped)
                    async for resp_item in self.skill_run(
                        source_type=SourceType.SKILL,
                        skill_name=tool_name,
                        skill_params_json=new_tool_args,
                        props=props,
                    ):
                        yield resp_item
            else:
                self.recorder.set_output_var(self.assign_type, self.output_var)

                # Execute the prompt; determine whether to invoke a tool. If so, invoke the tool; otherwise, directly request the LLM.
                # Use the LLM chat-based implementation for tool judgment
                tool_name, tool_args = await self.judge_tool_call(
                    judge_str=self.content,
                    system_prompt=self.system_prompt,
                    tools_list=self.skills,
                    model=self.model,
                    history=self.history,
                    ttc_mode=self.ttc_mode,
                )
                self.context.debug(
                    f"judge_block[{self.output_var}] [{self.content}] tool_name[{tool_name}] tool_args[{tool_args}]"
                )
                if tool_name:
                    # Ensure that output_var has been set (super().execute() should have already set it, but confirm here)
                    if self.recorder and hasattr(self.recorder, "set_output_var"):
                        self.recorder.set_output_var(self.assign_type, self.output_var)

                    intervention_vars = {
                        "tool_name": tool_name,
                        "judge_call_info": {
                            "judge_str": self.content,
                            "assign_type": self.assign_type,
                            "output_var": self.output_var,
                            "params": self.params,
                        },
                    }

                    try:
                        self.context.set_variable(
                            "intervention_judge_block_vars", intervention_vars
                        )

                        props = {"gvp": self.context}

                        async for resp_item in self.skill_run(
                            source_type=SourceType.SKILL,
                            skill_name=tool_name,
                            skill_params_json=tool_args or {},
                            props=props,
                        ):
                            yield resp_item

                    except ToolInterrupt as e:
                        raise e
                    except Exception as e:
                        raise Exception(
                            f"Judge block execution[{content}] tool[{tool_name}] failed: {str(e)}"
                        )
                else:
                    async for item in self.llm_chat(lang_mode="judge"):
                        yield item
        except ToolInterrupt as e:
            raise e
        except Exception as e:
            raise Exception(
                f"Judge block execution failed: {str(e)} traceback: {traceback.format_exc()}"
            )
