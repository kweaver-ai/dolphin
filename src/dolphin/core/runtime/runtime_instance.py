from enum import Enum
import time
from typing import List, Optional, TYPE_CHECKING
import uuid

from dolphin.core.common.enums import Messages, SkillInfo, Status, TypeStage
from dolphin.core.common.constants import estimate_tokens_from_chars

if TYPE_CHECKING:
    from dolphin.core.agent.base_agent import BaseAgent
    from dolphin.core.code_block.basic_code_block import BasicCodeBlock


class TypeRuntimeInstance(Enum):
    AGENT = "agent"
    BLOCK = "block"
    PROGRESS = "progress"
    STAGE = "stage"


class RuntimeInstance:
    def __init__(self, type: TypeRuntimeInstance):
        self.type = type
        self.id = str(uuid.uuid4())
        self.parent: RuntimeInstance = None
        self.children: List[RuntimeInstance] = []
        # Provide time fields uniformly for all instances to avoid missing attributes when accessing RuntimeGraph
        self.start_time = time.time()
        self.end_time = None

    def set_parent(self, parent: "RuntimeInstance"):
        self.parent = parent
        parent.children.append(self)

    def get_parent(self):
        return self.parent

    def get_children(self):
        return self.children

    def get_type(self):
        return self.type


class AgentInstance(RuntimeInstance):
    def __init__(self, name: str, agent: "BaseAgent"):
        super().__init__(type=TypeRuntimeInstance.AGENT)
        self.name = name
        self.agent = agent


class BlockInstance(RuntimeInstance):
    def __init__(self, name: str, block: "BasicCodeBlock"):
        super().__init__(type=TypeRuntimeInstance.BLOCK)
        self.name = name
        self.block = block


class LLMInput:
    def __init__(
        self, content: Optional[str] = None, messages: Optional[Messages] = None
    ) -> None:
        self.content = content
        self.messages = messages


class LLMOutput:
    def __init__(
        self,
        raw_output: Optional[str] = None,
        answer: Optional[str] = None,
        think: Optional[str] = None,
        block_answer: Optional[str] = None,
    ) -> None:
        self.raw_output = raw_output
        self.answer = answer
        self.think = think
        self.block_answer = block_answer


class StageInstance(RuntimeInstance):
    def __init__(
        self,
        agent_name: str = "",
        stage: TypeStage = TypeStage.LLM,
        answer: Optional[str] = None,
        think: Optional[str] = None,
        raw_output: Optional[str] = None,
        status: Status = Status.PROCESSING,
        skill_info: Optional[SkillInfo] = None,
        block_answer: Optional[str] = None,
        input_content: Optional[str] = None,
        input_messages: Optional[Messages] = None,
        interrupted: bool = False,
        flags: str = "",
    ):
        super().__init__(type=TypeRuntimeInstance.STAGE)

        self.agent_name = agent_name
        self.stage = stage
        self.input = LLMInput(
            content=input_content,
            messages=input_messages.copy() if input_messages is not None else None,
        )

        if not self.input.content and self.input.messages:
            self.input.content = self.input.messages[-1].content

        self.output = LLMOutput(
            answer=answer, think=think, raw_output=raw_output, block_answer=block_answer
        )
        self.status = status
        self.skill_info = skill_info
        self.interrupted = interrupted
        self.flags = flags

        self.start_time = time.time()
        self.end_time = self.start_time

        self.token_usage = {}

    def get_agent_name(self):
        return self.agent_name

    def get_answer(self):
        return self.output.answer

    def get_think(self):
        return self.output.think

    def get_raw_output(self):
        return self.output.raw_output

    def get_block_answer(self):
        return self.output.block_answer

    def set_end_time(self):
        self.end_time = time.time()

    def get_estimated_input_tokens(self):
        if self.stage != TypeStage.LLM:
            return 0

        # First try to get from whole_messages
        if self.input.messages:
            return self.input.messages.estimated_tokens()
        return 0

    def get_estimated_output_tokens(self):
        if self.stage != TypeStage.LLM:
            return 0

        if self.output.raw_output:
            tokens = estimate_tokens_from_chars(self.output.raw_output)
            return tokens if tokens is not None else 0

        return 0

    def get_estimated_ratio_tokens(self) -> float:
        if self.stage != TypeStage.LLM or self.input.messages is None:
            return 0

        total_tokens = (
            self.get_estimated_input_tokens() + self.get_estimated_output_tokens()
        )
        return (
            (float)(total_tokens) / (float)(self.input.messages.get_max_tokens())
            if self.input.messages.get_max_tokens() > 0
            else 0
        )

    def update(
        self,
        stage: Optional[TypeStage] = None,
        answer: Optional[str] = None,
        think: Optional[str] = None,
        raw_output: Optional[str] = None,
        status: Optional[str] = None,
        skill_info: Optional[SkillInfo] = None,
        block_answer: Optional[str] = None,
        input_messages: Optional[Messages] = None,
        **kwargs,
    ):
        if stage is not None:
            self.stage = stage
        if answer is not None:
            self.output.answer = answer
        if think is not None:
            self.output.think = think
        if raw_output is not None:
            self.output.raw_output = raw_output
        if status is not None:
            self.status = status
        if skill_info is not None:
            self.skill_info = skill_info
        if block_answer is not None:
            self.output.block_answer = block_answer
        if input_messages is not None:
            self.input.messages = input_messages.copy()

        if kwargs:
            for key, value in kwargs.items():
                if key not in [
                    "stage",
                    "answer",
                    "think",
                    "raw_output",
                    "status",
                    "skill_info",
                    "block_answer",
                    "input_messages",
                ]:
                    setattr(self, key, value)

    def get_triditional_dict(self):
        # Safe access to enum values with fallback
        stage_value = (
            self.stage.value if hasattr(self.stage, "value") else str(self.stage)
        )
        status_value = (
            self.status.value
            if self.status and hasattr(self.status, "value")
            else str(self.status)
        )

        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "stage": stage_value,
            "answer": self.output.answer,
            "think": self.output.think,
            "status": status_value,
            "skill_info": self.skill_info.to_dict() if self.skill_info else None,
            "block_answer": self.output.block_answer,
            "input_message": self.input.content,
            "interrupted": self.interrupted,
            "flags": self.flags,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "estimated_input_tokens": self.get_estimated_input_tokens(),
            "estimated_output_tokens": self.get_estimated_output_tokens(),
            "estimated_ratio_tokens": self.get_estimated_ratio_tokens(),
            "token_usage": self.token_usage,
        }

    def llm_empty_answer(self):
        return (
            self.stage == TypeStage.LLM
            and not self.output.answer
            and not self.output.think
            and not self.output.block_answer
        )

    def empty_answer(self):
        return (
            not self.output.answer
            and not self.output.think
            and not self.output.block_answer
        )


class ProgressInstance(RuntimeInstance):
    def __init__(self, context, parent: Optional["ProgressInstance"] = None, flags=""):
        super().__init__(type=TypeRuntimeInstance.PROGRESS)

        self.context = context
        self.stages: List[StageInstance] = []
        self.flags = flags

    def add_stage(
        self,
        agent_name: str = "",
        stage: TypeStage = TypeStage.LLM,
        answer: str = "",
        think: str = "",
        raw_output: str = "",
        status: Status = Status.PROCESSING,
        skill_info: Optional[SkillInfo] = None,
        block_answer: str = "",
        input_content: str = "",
        input_messages: Optional[Messages] = None,
        interrupted: bool = False,
    ):
        pop_last_stage = False
        if len(self.stages) > 0 and self.stages[-1].llm_empty_answer():
            pop_last_stage = True

        stage_instance = StageInstance(
            agent_name=agent_name,
            stage=stage,
            answer=answer,
            think=think,
            raw_output=raw_output,
            status=status,
            skill_info=skill_info,
            block_answer=block_answer,
            input_content=input_content,
            input_messages=input_messages,
            interrupted=interrupted,
            flags=self.flags,
        )
        self.add_stage_instance(stage_instance, pop_last_stage)

    def add_stage_instance(
        self, stage_instance: StageInstance, pop_last_stage: bool = False
    ):
        stage_instance.set_parent(self)
        if pop_last_stage:
            self.stages.pop()
        self.stages.append(stage_instance)

        # Register stage instance to runtime_graph if available
        if (
            self.context
            and hasattr(self.context, "runtime_graph")
            and self.context.runtime_graph
        ):
            self.context.runtime_graph.set_stage(stage_instance, pop_last_stage)

        self.set_variable()

    def set_last_stage(
        self,
        stage: Optional[TypeStage] = None,
        answer: Optional[str] = None,
        think: Optional[str] = None,
        raw_output: Optional[str] = None,
        status: Status = Status.PROCESSING,
        skill_info: Optional[SkillInfo] = None,
        block_answer: Optional[str] = None,
        input_messages: Optional[Messages] = None,
        **kwargs,
    ):
        # If no stages exist, create a new one
        if len(self.stages) == 0:
            # If stage is None and we have no stages, default to LLM
            default_stage = stage if stage is not None else TypeStage.LLM
            self.add_stage(
                stage=default_stage,
                answer=answer,
                think=think,
                raw_output=raw_output,
                status=status,
                skill_info=skill_info,
                block_answer=block_answer,
                input_messages=input_messages,
            )
            return

        # Check if we need to create a new stage (when stage type changes)
        last_stage = self.stages[-1]

        # Create new stage if stage type is changing (and it's not None)
        if stage is not None and stage != last_stage.stage:
            self.add_stage(
                stage=stage,
                answer=answer,
                think=think,
                raw_output=raw_output,
                status=status,
                skill_info=skill_info,
                block_answer=block_answer,
                input_messages=input_messages,
            )
            return

        last_stage.update(
            stage=stage,
            answer=answer,
            think=think,
            raw_output=raw_output,
            status=status,
            skill_info=skill_info,
            block_answer=block_answer,
            input_messages=input_messages,
            **kwargs,
        )
        last_stage.set_end_time()
        self.set_variable()

    def get_last_stage(self):
        return self.stages[-1] if len(self.stages) > 0 else None

    def get_last_answer(self) -> dict:
        return self.stages[-1].get_triditional_dict()

    def get_step_answers(self):
        last_stage = self.get_last_stage()
        if last_stage is None:
            return ""

        last_answer = last_stage.get_answer()
        if isinstance(last_answer, str) and len(last_answer.strip()) != 0:
            return last_answer
        elif not isinstance(last_answer, str):
            return last_answer
        else:
            block_answer = last_stage.get_block_answer()
            think = last_stage.get_think()
            answer = last_stage.get_answer()
            return str(block_answer) + "\n\n" + str(think) + "\n\n" + str(answer)

    def get(self):
        """
        Get stages as serializable dictionaries instead of raw objects
        This ensures compatibility when stages are used as variable values
        """
        return [stage.get_triditional_dict() for stage in self.stages]

    def get_raw_stages(self):
        """
        Get raw StageInstance objects for internal use
        Use this method when you need direct access to StageInstance objects
        """
        return self.stages

    def set_variable(self):
        self.context.set_variable(
            "_progress", [stage.get_triditional_dict() for stage in self.stages]
        )
