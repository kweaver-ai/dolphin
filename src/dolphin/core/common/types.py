from abc import abstractmethod
from enum import Enum


class SourceType(Enum):
    SKILL = "SKILL"
    LLM = "LLM"
    EXPLORE = "EXPLORE"
    ASSIGN = "ASSIGN"
    LIST = "LIST"
    OTHER = "OTHER"


class Var:
    def __init__(self, value):
        self.val = value

    @abstractmethod
    def add(self, var: "Var") -> "Var":
        raise NotImplementedError

    @abstractmethod
    def set_last(self, var: "Var") -> "Var":
        raise NotImplementedError

    @property
    def value(self):
        return self.val

    def to_dict(self):
        return self.val


# Note: ObjectType, ObjectTypeFactory, OutputFormat, etc. are available
# from dolphin.core.common.object_type and dolphin.core.common.output_format
# They are NOT re-exported here to avoid circular imports with enums.py
