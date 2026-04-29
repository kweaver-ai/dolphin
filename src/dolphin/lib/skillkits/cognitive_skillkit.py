from typing import List, Dict, Optional
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit


class CognitiveSkillkit(Skillkit):
    # Use Skillkit's generic compressor, override default rules for this kit
    DEFAULT_COMPRESS_RULES: Dict[str, Dict[str, List[str]]] = {
        "_cog_think": {"include": ["action"]},
        "_cog_gen_sql": {"include": ["sql_generation"]},
    }

    def getName(self) -> str:
        return "cognitive_skillkit"

    def _cog_think(self, reflection: str, plan: str, action: str, **kwargs) -> str:
        """
        A tool for structured reasoning and planning, enabling users to break down complex problems into reflection, planning, and actionable steps.
        Stores thoughts in memory for complex reasoning. No need to plan every time, just plan every 2 steps.

        Args:
            reflection (str): Analysis, assumptions, insights, or summary of prior steps. May contain errors, emphasizing deep reasoning.
            plan (str): A plan breaking down the problem into executable steps.
            action (str): Specific, executable, and verifiable next steps, potentially involving tool calls.
            **kwargs: Additional properties passed to the tool.

        Returns:
            str: Formatted string of the reasoning step.
        """
        return f"""
            reflection: {reflection}
            plan: {plan}
            action: {action}
        """

    def _cog_gen_sql(
        self, reflection: str, schema_link: str, sql_generation: str, **kwargs
    ) -> str:
        """Tools for structured SQL generation, including reasoning steps that decompose complex SQL generation into reflection, schema analysis, and SQL construction.

        Args:
            reflection (str): Problem analysis, understanding requirements, and reasoning about query structure.
            schema_link (str): Database schema analysis, table relationships, and field mappings relevant to the query.
            sql_generation (str): Actual SQL statement generation, including specific syntax and logical implementation.
            **kwargs: Additional attributes passed to the tool.

        Returns:
            str: Formatted string of the SQL generation process.
        """
        return f"""
            reflection: {reflection}
            schema_link: {schema_link}
            sql_generation: {sql_generation}
        """

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self._cog_think),
            SkillFunction(self._cog_gen_sql),
        ]

    @staticmethod
    def is_cognitive_skill(skillname: str) -> bool:
        return skillname.startswith("_cog_think") or skillname.startswith(
            "_cog_gen_sql"
        )

    @staticmethod
    def compress_msg(
        message: str, rules: Optional[Dict[str, Dict[str, List[str]]]] = None
    ) -> str:
        """Delegates to generic compressor in Skillkit, using this kit's default rules unless overridden."""
        active_rules = rules or CognitiveSkillkit.DEFAULT_COMPRESS_RULES
        # Reuse generic logic and regex-based scanning in base Skillkit
        return Skillkit.compress_message_with_rules(
            message, rules=active_rules, marker_prefix="=>#"
        )

    @staticmethod
    def set_compress_rules(rules: Dict[str, Dict[str, List[str]]]):
        """Set default compression rules for cognitive messages at runtime."""
        CognitiveSkillkit.DEFAULT_COMPRESS_RULES = rules or {}
