from dolphin.core.common.types import SourceType, Var
from dolphin.core.common.enums import ToolInfo


class VarOutput(Var):
    def __init__(self, name, value, source_type=SourceType.OTHER, tool_info=None, skill_info=None):
        super().__init__(value)

        self.name = name
        self.source_type = source_type
        # skill_info is a deprecated alias for tool_info
        self.tool_info = tool_info if tool_info is not None else skill_info

    @property
    def skill_info(self):
        """Deprecated: use tool_info instead."""
        return self.tool_info

    def add(self, var: Var):
        if self.source_type == SourceType.LIST:
            self.val.append(var)
            return self

        return VarOutput(name=self.name, value=[self, var], source_type=SourceType.LIST)

    def set_last(self, var: Var):
        if self.source_type == SourceType.LIST:
            self.val[-1] = var
            return self

    def to_dict(self):
        # Processing the serialization of value
        if self.source_type == SourceType.LIST:
            # LIST type: recursively serialize each VarOutput item
            value = [item.to_dict() for item in self.val]
        elif self.source_type == SourceType.EXPLORE:
            # EXPLORE type: value is already a list of dictionaries, use directly
            value = self.val
        else:
            value = self.val

        tool_info_dict = self.tool_info.to_dict() if self.tool_info else {}
        return {
            "__type__": "VarOutput",  # Type identifier for deserialization
            "name": self.name,
            "value": value,
            "source_type": self.source_type.value,
            "tool_info": tool_info_dict,
            # Deprecated alias kept for consumers still reading the old key
            "skill_info": tool_info_dict,
        }

    @staticmethod
    def is_serialized_dict(data) -> bool:
        """Check if data is a serialized VarOutput dictionary"""
        return isinstance(data, dict) and data.get("__type__") == "VarOutput"

    @staticmethod
    def from_dict(dict_data: dict) -> "VarOutput":
        source_type = SourceType(dict_data.get("source_type"))
        if source_type == SourceType.LIST:
            # LIST type: recursively deserialize each VarOutput item
            value = [VarOutput.from_dict(item) for item in dict_data["value"]]
        elif source_type == SourceType.EXPLORE:
            # EXPLORE type: value is a regular dictionary list (exploration results), no recursive deserialization needed
            value = dict_data["value"]
        else:
            value = dict_data["value"]

        return VarOutput(
            name=dict_data["name"],
            value=value,
            source_type=source_type,
            tool_info=(
                ToolInfo.from_dict(dict_data.get("tool_info", dict_data.get("skill_info")))
                if dict_data.get("tool_info") or dict_data.get("skill_info")
                else None
            ),
        )

    @property
    def value(self):
        if self.source_type == SourceType.LIST:
            return [item.value for item in self.val]
        return self.val

    def __str__(self):
        return f"{self.name}: {self.val}"

    def __repr__(self):
        return self.__str__()
