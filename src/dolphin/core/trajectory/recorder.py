from __future__ import annotations
from dolphin.core.common.enums import StreamItem
from dolphin.core.common.enums import TypeStage, Status, SkillInfo, SkillType
from dolphin.core.runtime.runtime_instance import ProgressInstance
from dolphin.core.common.types import SourceType
from typing import Union, Dict, Any


class Recorder:
    def __init__(
        self,
        context,
        progress: ProgressInstance,
        assign_type=None,
        output_var=None,
        output_dump_process=False,
        flags="",
    ):
        self.context = context
        self.progress = progress
        self.assign_type = assign_type
        self.output_var = output_var
        self.output_dump_process = output_dump_process
        self.appended = False

    def set_output_var(self, assign_type, output_var):
        self.assign_type = assign_type
        self.output_var = output_var

    def set_output_dump_process(self, output_dump_process):
        self.output_dump_process = output_dump_process

    def getProgress(self):
        return self.progress

    def update(
        self,
        item: Union[StreamItem, Dict[str, Any], str] = {},
        stage=None,  # Changed to None, let us infer automatically
        is_completed=False,
        has_error=False,
        input_messages=None,
        source_type=SourceType.OTHER,
        raw_output=None,
        skill_name=None,
        skill_args={},
        skill_type=None,
        checked=True,
    ):
        skill_info = None
        if skill_name:
            stage = TypeStage.SKILL
            # Use provided skill_type or default to TOOL
            if skill_type is None:
                skill_type = SkillType.TOOL
            skill_info = SkillInfo.build(
                skill_type=skill_type,
                skill_name=skill_name,
                skill_args=skill_args,
                checked=checked,
            )
            source_type = SourceType.SKILL

        # Auto-detect stage type based on source_type if not explicitly provided
        if stage is None:
            if source_type == SourceType.SKILL:
                stage = TypeStage.SKILL
            elif source_type == SourceType.ASSIGN:
                stage = TypeStage.ASSIGN
            elif source_type == SourceType.EXPLORE:
                # For EXPLORE source, don't create new stage, just update existing one
                # Use None to signal that we should update the last stage without changing its type
                stage = None
            else:
                stage = TypeStage.LLM  # Default fallback

        if not is_completed:
            status = Status.PROCESSING
        elif has_error:
            status = Status.FAILED
        else:
            status = Status.COMPLETED

        params = {
            "stage": stage,
            "status": status,
            "skill_info": skill_info,
            "raw_output": raw_output,
            "input_messages": input_messages,
        }

        if isinstance(item, StreamItem):
            params.update(item.to_dict())
        else:
            if isinstance(item, dict):
                safe_item = {k: v for k, v in item.items() if k not in params.keys()}
            else:
                safe_item = {"answer": item}
            params.update(safe_item)
        self.progress.set_last_stage(**params)

        # Ensure end_time is set for completed stages
        if is_completed:
            last_stage = self.progress.get_last_stage()
            if last_stage:
                last_stage.set_end_time()

        # If item is None and has already been set via set_last_stage, there's no need to process it again.
        if item is not None:
            self.update_output_variable(
                item=item,
                source_type=source_type,
                skill_name=skill_name,
                skill_args=skill_args,
                skill_type=skill_type,
                checked=checked,
            )

        return item

    def update_output_variable(
        self,
        item: Union[StreamItem, Dict[str, Any], str],
        source_type=SourceType.OTHER,
        skill_name=None,
        skill_args={},
        skill_type=None,
        checked=True,
    ):
        skill_info = None
        if skill_name:
            # Use provided skill_type or default to TOOL
            if skill_type is None:
                skill_type = SkillType.TOOL
            skill_info = SkillInfo.build(
                skill_type=skill_type,
                skill_name=skill_name,
                skill_args=skill_args,
                checked=checked,
            )
            source_type = SourceType.SKILL

        # If item is a dictionary and contains the output_var_value field, prioritize using the parsed object
        var_value = item
        if isinstance(item, dict) and "output_var_value" in item:
            var_value = item["output_var_value"]
            item.pop("output_var_value")
        elif isinstance(item, StreamItem):
            var_value = item.to_dict()

        if self.assign_type == ">>":
            if not self.appended:
                self.context.append_var_output(
                    name=self.output_var,
                    value=var_value,
                    source_type=source_type,
                    skill_info=skill_info,
                )
                self.appended = True
            else:
                self.context.set_last_var_output(
                    name=self.output_var,
                    value=var_value,
                    source_type=source_type,
                    skill_info=skill_info,
                )
        else:
            self.context.set_var_output(
                name=self.output_var,
                value=var_value,
                source_type=source_type,
                skill_info=skill_info,
            )

    def get_answer(self):
        return self.progress.get_last_answer().get("answer", "")

    def get_progress_answers(self) -> dict:
        return self.progress.get_last_answer()

    def get_all_answers(self) -> list[dict]:
        return self.progress.get()
