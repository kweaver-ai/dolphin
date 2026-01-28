"""PlanActSkillkit compatibility shim.

This module preserves the historical `plan_act` skillkit entry point while
redirecting implementation to the unified PlanSkillkit.

Note:
    New code should prefer `PlanSkillkit` / `plan_skillkit`.
"""

from dolphin.lib.skillkits.plan_skillkit import PlanSkillkit


class PlanActSkillkit(PlanSkillkit):
    """Backward-compatible alias for PlanSkillkit.

    The legacy skillkit name is kept to avoid breaking older configs that
    reference `plan_act`.
    """

    def getName(self) -> str:
        return "plan_act"

