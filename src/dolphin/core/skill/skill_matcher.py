"""Skill Name Matching Utility Class

Provides unified skill name matching logic, supporting wildcard matching and exact matching
"""

import fnmatch
from typing import Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.core.skill.skill_function import SkillFunction


class SkillMatcher:
    """Skill Name Matching Utility Class

        Supports the following matching patterns:
        - Exact match: "playwright_browser_navigate"
        - Wildcard match: "playwright*", "*_browser_*", "playwright_browser_*"
        - List match: ["playwright*", "_python"]
    """

    @staticmethod
    def match_skill_name(skill_name: str, pattern: str) -> bool:
        """Determine whether the skill name matches the specified pattern

        Args:
            skill_name (str): The skill name
            pattern (str): The matching pattern, supports wildcards

        Returns:
            bool: Whether it matches
        """
        return fnmatch.fnmatch(skill_name, pattern)

    @staticmethod
    def match_skill_names(skill_name: str, patterns: List[str]) -> bool:
        """Determine whether the skill name matches any one in the specified pattern list.

        Args:
            skill_name (str): The skill name
            patterns (List[str]): The list of matching patterns

        Returns:
            bool: Whether it matches any one pattern
        """
        return any(
            SkillMatcher.match_skill_name(skill_name, pattern) for pattern in patterns
        )

    @staticmethod
    def filter_skills_by_pattern(
        skills: List["SkillFunction"], pattern: str
    ) -> List["SkillFunction"]:
        """Filter a list of skills based on a single pattern

        Args:
            skills (List[SkillFunction]): List of skills
            pattern (str): Matching pattern

        Returns:
            List[SkillFunction]: Filtered list of skills
        """
        return [
            skill
            for skill in skills
            if SkillMatcher.match_skill_name(skill.get_function_name(), pattern)
        ]

    @staticmethod
    def filter_skills_by_patterns(
        skills: List["SkillFunction"], patterns: List[str]
    ) -> List["SkillFunction"]:
        """Filter the skill list based on multiple patterns

        Args:
            skills (List[SkillFunction]): List of skills
            patterns (List[str]): List of matching patterns

        Returns:
            List[SkillFunction]: Filtered list of skills
        """
        matched_skills = []
        for skill in skills:
            skill_name = skill.get_function_name()
            if SkillMatcher.match_skill_names(skill_name, patterns):
                matched_skills.append(skill)
        return matched_skills

    @staticmethod
    def find_first_matching_skill(
        skills: List["SkillFunction"], pattern: str
    ) -> Optional["SkillFunction"]:
        """Find the first skill that matches the specified pattern

        Args:
            skills (List[SkillFunction]): List of skills
            pattern (str): Matching pattern

        Returns:
            Optional[SkillFunction]: The first matching skill, or None if not found
        """
        for skill in skills:
            if SkillMatcher.match_skill_name(skill.get_function_name(), pattern):
                return skill
        return None

    @staticmethod
    def get_matching_skills(
        skills: List["SkillFunction"], skill_names: Optional[List[str]] = None
    ) -> List["SkillFunction"]:
        """Get skills matching the specified list of names

        Args:
            skills (List[SkillFunction]): List of skills
            skill_names (Optional[List[str]]): List of skill names, supports wildcards; None means return all skills

        Returns:
            List[SkillFunction]: List of matching skills
        """
        if skill_names is None:
            return skills

        return SkillMatcher.filter_skills_by_patterns(skills, skill_names)

    @staticmethod
    def get_matching_skills_by_names(
        skills: List["SkillFunction"], skill_names: List[str]
    ) -> List["SkillFunction"]:
        return [skill for skill in skills if skill.get_function_name() in skill_names]

    @staticmethod
    def get_skill_by_name(
        skills: List["SkillFunction"], skill_name: str
    ) -> Optional["SkillFunction"]:
        """Get a skill by its name, supporting wildcard matching.

        Args:
            skills (List[SkillFunction]): List of skills
            skill_name (str): Name of the skill, supports wildcards

        Returns:
            Optional[SkillFunction]: The matched skill, returns None if not found
        """
        return SkillMatcher.find_first_matching_skill(skills, skill_name)

    @staticmethod
    def get_owner_skillkits(skills: Iterable["SkillFunction"]) -> Set[str]:
        """Collect all known owner skillkit names from skills via owner_name property."""
        owners: Set[str] = set()
        for skill in skills:
            if hasattr(skill, "owner_name") and skill.owner_name:
                owners.add(skill.owner_name)
        return owners

    @staticmethod
    def split_namespaced_pattern(
        pattern: str, owner_names: Set[str]
    ) -> Tuple[Optional[str], str, bool]:
        """Split a pattern into optional <skillkit> namespace and the remaining tool-name pattern.

        Supported forms:
        - "<skillkit>": shorthand for "<skillkit>.*"
        - "<skillkit>.<pattern>": namespaced matching (skill owner must equal <skillkit>)
        - "<pattern>": non-namespaced matching (matches tool name directly)

        Notes:
        - If owner_names is empty, always treat as non-namespaced.
        - Uses longest owner prefix match to support owner names containing dots.
        """
        if not owner_names:
            return None, pattern, False

        if pattern in owner_names:
            return pattern, "*", True

        for owner in sorted(owner_names, key=len, reverse=True):
            prefix = owner + "."
            if pattern.startswith(prefix):
                suffix = pattern[len(prefix) :] or "*"
                return owner, suffix, True

        return None, pattern, False

    @staticmethod
    def match_skill(
        skill: "SkillFunction", pattern: str, owner_names: Optional[Set[str]] = None
    ) -> bool:
        """Match a skill against a (possibly namespaced) pattern."""
        owner_names = owner_names or set()
        owner, suffix, is_namespaced = SkillMatcher.split_namespaced_pattern(
            pattern, owner_names
        )
        if not is_namespaced:
            return SkillMatcher.match_skill_name(skill.get_function_name(), pattern)

        skill_owner = getattr(skill, "owner_name", None)
        return skill_owner == owner and SkillMatcher.match_skill_name(
            skill.get_function_name(), suffix
        )

    @staticmethod
    def match_skills_batch(
        skills: List["SkillFunction"],
        patterns: List[str],
        owner_names: Optional[Set[str]] = None,
    ) -> Tuple[List["SkillFunction"], bool]:
        """Batch match skills against multiple patterns.

        This method is optimized to:
        - Pre-parse all patterns once (avoid repeated split_namespaced_pattern calls)
        - Deduplicate matched skills (each skill appears at most once)
        - Track whether any namespaced pattern was used

        Args:
            skills: List of skills to match against
            patterns: List of patterns (plain or namespaced)
            owner_names: Set of known skillkit owner names

        Returns:
            Tuple of (matched_skills, any_namespaced_pattern)
        """
        owner_names = owner_names or set()

        # Pre-sort owner_names once for consistent longest-prefix matching
        sorted_owners = sorted(owner_names, key=len, reverse=True) if owner_names else []

        # Pre-parse all patterns
        parsed_patterns: List[Tuple[Optional[str], str, bool]] = []
        any_namespaced = False
        for pattern in patterns:
            owner, suffix, is_ns = SkillMatcher._split_namespaced_pattern_with_sorted_owners(
                pattern, owner_names, sorted_owners
            )
            parsed_patterns.append((owner, suffix, is_ns))
            any_namespaced = any_namespaced or is_ns

        # Match skills with deduplication
        matched: List["SkillFunction"] = []
        seen_ids: Set[int] = set()

        for skill in skills:
            skill_id = id(skill)
            if skill_id in seen_ids:
                continue

            skill_name = skill.get_function_name()
            skill_owner = getattr(skill, "owner_name", None)

            for owner, suffix, is_ns in parsed_patterns:
                if is_ns:
                    # Namespaced pattern: match owner and skill name
                    if skill_owner == owner and fnmatch.fnmatch(skill_name, suffix):
                        matched.append(skill)
                        seen_ids.add(skill_id)
                        break
                else:
                    # Plain pattern: match skill name only
                    if fnmatch.fnmatch(skill_name, suffix):
                        matched.append(skill)
                        seen_ids.add(skill_id)
                        break

        return matched, any_namespaced

    @staticmethod
    def _split_namespaced_pattern_with_sorted_owners(
        pattern: str, owner_names: Set[str], sorted_owners: List[str]
    ) -> Tuple[Optional[str], str, bool]:
        """Split pattern with pre-sorted owners (avoids repeated sorting)."""
        if not owner_names:
            return None, pattern, False

        if pattern in owner_names:
            return pattern, "*", True

        for owner in sorted_owners:
            prefix = owner + "."
            if pattern.startswith(prefix):
                suffix = pattern[len(prefix):] or "*"
                return owner, suffix, True

        return None, pattern, False
