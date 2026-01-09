from abc import ABC
from typing import Dict, Any

# Avoid circular imports by using type hint strings
# from .concept import Concept


class ConceptInstance(ABC):
    """Abstract base class for concept instances (e.g., Object, Relation)

        Attributes:
            concept (Concept): The concept definition this instance belongs to.
            values (Dict[str, Any]): Instance members and their corresponding values.
    """

    def __init__(self, concept: "Concept", values: Dict[str, Any]):
        """Initialize concept instance

        Args:
            concept (Concept): The concept this instance belongs to.
            values (Dict[str, Any]): Instance members and their corresponding values.

        Raises:
            TypeError: If concept is not an instance of Concept.
            ValueError: If the provided values do not match the members or type requirements of Concept.
        """
        # Delayed import to avoid circular dependencies
        from .concept import Concept

        if not isinstance(concept, Concept):
            raise TypeError("必须提供一个 Concept 实例")

        # 1. Verify that the member exists and is complete
        providedMembers = set(values.keys())
        if not concept.validateMembers(providedMembers):
            missing = set(concept.members.keys()) - providedMembers
            extra = providedMembers - set(concept.members.keys())
            errorMsg = f"实例的成员与 Concept '{concept.name}' 不匹配。"
            if missing:
                errorMsg += f" 缺少成员: {missing}."
            if extra:
                errorMsg += f" 多余成员: {extra}."
            raise ValueError(errorMsg)

        # 2. Validate member value types
        for memberName, value in values.items():
            if not concept.validateMemberValue(memberName, value):
                expectedType = concept.members[memberName].name
                actualType = type(value).__name__
                raise TypeError(
                    f"成员 '{memberName}' 的值类型错误。期望类型: {expectedType}, 实际类型: {actualType}"
                )

        # Use object.__setattr__ to avoid triggering custom __setattr__
        object.__setattr__(self, "concept", concept)
        object.__setattr__(self, "values", values)

    def __getattr__(self, name: str) -> Any:
        """Allow accessing member values through attributes"""
        if name == "concept" or name == "values":
            # Prevent infinite recursion
            raise AttributeError

        try:
            # Try to get the value from the values dictionary
            return self.values[name]
        except KeyError:
            # If the value does not exist, an AttributeError is raised.
            raise AttributeError(
                f"'{type(self).__name__}' 对象没有属性 '{name}' 或该属性未在 values 中定义"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        """Allow setting member values through attributes (if the member is defined in the Concept)"""
        if name in ["concept", "values"]:
            # Allow setting internal attributes
            object.__setattr__(self, name, value)
        elif name in self.concept.members:
            # Validate the type of the new value
            if not self.concept.validateMemberValue(name, value):
                expectedType = self.concept.members[name].name
                actualType = type(value).__name__
                raise TypeError(
                    f"尝试设置的成员 '{name}' 的值类型错误。期望类型: {expectedType}, 实际类型: {actualType}"
                )
            # Set value
            self.values[name] = value
        else:
            raise AttributeError(
                f"无法设置属性 '{name}'，因为它不是 Concept '{self.concept.name}' 定义的成员"
            )

    def __repr__(self) -> str:
        """Return the string representation of the instance."""
        return f"{type(self).__name__}(concept='{self.concept.name}', values={self.values})"

    # Additional generic instance methods can be added
    # For example, get the value of a specific member, check if a member exists, etc.


# Additional general instance methods can be added
# For example, retrieving the value of a specific member, checking whether a member exists, etc.
