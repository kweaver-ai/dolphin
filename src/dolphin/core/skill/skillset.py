from __future__ import annotations
from typing import Dict, List, Optional

from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skill_matcher import SkillMatcher

from .skillkit import Skillkit


class Skillset(Skillkit):
    """A container that aggregates skills from multiple skillkits.

    Unlike regular Skillkits that create skills via _createSkills(),
    Skillset dynamically collects skills from other skillkits.
    It overrides getSkills() to return its managed collection directly,
    bypassing the base class caching mechanism.

    Note: Metadata prompt functionality is NOT handled here. It is collected
    dynamically via skill.owner_skillkit in ExploreStrategy._collect_metadata_prompt().
    """

    def __init__(self):
        super().__init__()
        self.skills: Dict[str, SkillFunction] = {}

    def merge(self, otherSkillset: Skillset):
        self.skills.update(otherSkillset.skills)

    def addSkillkit(self, skillkit: Skillkit):
        """Add all skills from a skillkit to this skillset.

        Skills are retrieved via skillkit.getSkills(), which automatically
        binds owner_skillkit in the base Skillkit class. This binding is
        used by ExploreStrategy to collect metadata prompts dynamically.
        """
        for skill in skillkit.getSkills():
            self.addSkill(skill)

    def addSkill(self, skill: SkillFunction):
        if skill.get_function_name() not in self.getSkillNames():
            self.skills[skill.get_function_name()] = skill

    def getSkillNames(self):
        return self.skills.keys()

    def getSkills(self) -> List[SkillFunction]:
        """Return the aggregated skills directly.

        This overrides the base class implementation to return the
        dynamically managed skills collection without caching.
        Skills already have owner_skillkit bound from their source skillkits.
        """
        return list(self.skills.values())

    @staticmethod
    def createSkillset(
        globalSkillset: Skillset, skillNames: Optional[List[str]] = None
    ):
        newSkillset = Skillset()
        if skillNames is None:
            return globalSkillset

        # Get skills using wildcard matching with SkillMatcher
        matched_skills = SkillMatcher.get_matching_skills(
            globalSkillset.getSkills(), skillNames
        )
        for skill in matched_skills:
            newSkillset.addSkill(skill)
        return newSkillset

    def isEmpty(self) -> bool:
        return len(self.skills) == 0
