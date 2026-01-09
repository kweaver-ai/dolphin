from typing import List
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit


class NoopSkillkit(Skillkit):
    """
    just for test
    """

    def __init__(self):
        super().__init__()
        self.globalContext = None

    def getName(self) -> str:
        return " noop_skillkit"

    def noop_calling(self, **kwargs) -> str:
        """Do nothing, for testing

        Args:
            None

        Returns:
            str: Do nothing, for testing
        """
        print("do nothing")
        return "do nothing"

    def _createSkills(self) -> List[SkillFunction]:
        return [SkillFunction(self.noop_calling)]
