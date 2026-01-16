from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.utils.tools import ToolInterrupt
from dolphin.core.common.enums import CategoryBlock, TypeStage
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import console
from dolphin.core.context.var_output import SourceType
from typing import Optional, AsyncGenerator, Dict, Any


class ToolBlock(BasicCodeBlock):
    def __init__(self, context: Context, debug_infos: Optional[dict] = None):
        super().__init__(context=context)
        self.already_append_flag = False
        # Enable tool interrupt mechanism for ToolBlock
        self._enable_tool_interrupt = True

    def parse_tool_call(self):
        """Parse tool calls, now using the unified parse_block_content method

        Args:
            content: Tool call content

        Returns:
            Dictionary containing the parsing results
        """
        # Return a compatible format
        return {
            "tool_name": self.content,  # The tool name is stored in content.
            "args": self.params,
            "assign_type": self.assign_type,
            "output_var": self.output_var,
        }

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.TOOL,
        replace_variables=True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for _ in super().execute(content, category, replace_variables):
            pass

        self.block_start_log("tool")
        try:
            gvpool_all_keys = self.context.get_all_variables().keys()
            if (
                "intervention_tool_block_vars" in gvpool_all_keys
                and "tool" in gvpool_all_keys
            ):
                intervention_vars = self.context.get_var_value(
                    "intervention_tool_block_vars"
                )
                assert intervention_vars is not None, "intervention_vars is None"

                tool_name = intervention_vars["tool_name"]
                tool_call_info = intervention_vars["tool_call_info"]
                self.context.delete_variable("intervention_tool_block_vars")
                if self.recorder is not None:
                    self.recorder.set_output_var(
                        tool_call_info["assign_type"], tool_call_info["output_var"]
                    )

                input_dict = self.context.get_var_value("tool")
                assert input_dict is not None, "input_dict is None"

                new_tool_name = input_dict["tool_name"]
                assert new_tool_name == tool_name, (
                    "(tool_block) new_tool_name 和中断之前的 tool_name不一致"
                )
                tool_obj = self.context.get_skill(tool_name)
                raw_tool_args = input_dict["tool_args"]
                new_tool_args = {arg["key"]: arg["value"] for arg in raw_tool_args}

                props = {"intervention": False, "gvp": self.context}
                input_dict = self.context.delete_variable("tool")

                resp_item = None
                async for resp_item in self.skill_run(
                    source_type=SourceType.SKILL,
                    skill_name=tool_name,
                    skill_params_json=new_tool_args,
                    props=props,
                ):
                    yield resp_item

                if self.recorder is not None:
                    self.recorder.update(
                        stage=TypeStage.SKILL,
                        item=resp_item,
                        skill_name=tool_name,
                        skill_args=new_tool_args,
                        skill_type=self.context.get_skill_type(tool_name),
                        source_type=SourceType.SKILL,
                        is_completed=True,
                    )
                yield {"data": resp_item}
            else:
                # step1: First parse, then retrieve the actual values from gvpool when actually calling the function (the actual variable values might be of type dict, list)
                tool_call_info = self.parse_tool_call()
                if self.recorder is not None:
                    self.recorder.set_output_var(
                        tool_call_info["assign_type"], tool_call_info["output_var"]
                    )

                # step2: Obtain the tool object and execute the tool call
                tool_name = tool_call_info["tool_name"]

                intervention_vars = {
                    "tool_name": tool_call_info["tool_name"],
                    "tool_call_info": tool_call_info,
                }

                self.context.set_variable(
                    "intervention_tool_block_vars", intervention_vars
                )
                interventions = self.context.get_var_value("interventions") or []
                interventions += [intervention_vars]
                self.context.set_variable("interventions", interventions)

                async for resp_item in self.skill_run(
                    source_type=SourceType.SKILL,
                    skill_name=tool_name,
                    skill_params_json=tool_call_info["args"],
                ):
                    yield resp_item

            console("\n", verbose=self.context.is_verbose())
        except ToolInterrupt as e:
            raise e
        except Exception as e:
            raise Exception(f"Tool block execution failed: {str(e)}")
