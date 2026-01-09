from typing import Dict, Any

from dolphin.lib.ontology.basic.base import ConceptInstance
from dolphin.lib.ontology.basic.concept import Concept


class Relation(ConceptInstance):
    """A concrete instance (relation) of a Concept

        A Relation must adhere to the member contract defined by its associated Concept.
        The values of members are typically used to connect Objects, but may also be any Python type.
    """

    pass  # All basic functions inherit from ConceptInstance

    def __init__(self, concept: Concept, values: Dict[str, Any]):
        """Initialize Relation

        Args:
            concept (Concept): The Concept to which this Relation belongs.
            values (Dict[str, Any]): The members of the Relation and their corresponding values.

        Raises:
            ValueError: If the provided values do not meet the member requirements of the Concept.
            TypeError: If concept is not an instance of Concept.
        """
        if not isinstance(concept, Concept):
            raise TypeError("必须提供一个 Concept 实例")

        provided_members = set(values.keys())
        if not concept.validateMembers(provided_members):
            missing = concept.members - provided_members
            extra = provided_members - concept.members
            error_msg = f"Relation 的成员与 Concept '{concept.name}' 不匹配。"
            if missing:
                error_msg += f" 缺少成员: {missing}."
            if extra:
                error_msg += f" 多余成员: {extra}."
            # Strict mode: missing or extra members are not allowed.
            raise ValueError(error_msg)

        self.concept = concept
        self.values = values

    def __getattr__(self, name: str) -> Any:
        """Allow accessing member values through attributes"""
        if name in self.values:
            return self.values[name]
        raise AttributeError(f"'{type(self).__name__}' 对象没有属性 '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Allow setting member values through attributes (if the member is defined)"""
        if name in ["concept", "values"]:
            super().__setattr__(name, value)
        elif name in self.concept.members:
            self.values[name] = value
        else:
            raise AttributeError(
                f"无法设置属性 '{name}'，因为它不是 Concept '{self.concept.name}' 定义的成员"
            )

    def __repr__(self) -> str:
        return f"Relation(concept='{self.concept.name}', values={self.values})"
