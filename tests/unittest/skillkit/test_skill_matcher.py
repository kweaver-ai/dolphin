#!/usr/bin/env python3
"""
Unit tests for SkillMatcher utility class.

Tests skill name matching logic including wildcard, exact, and namespaced matching.
"""

import unittest
from unittest.mock import Mock
from typing import List, Optional

from dolphin.core.skill.skill_matcher import SkillMatcher


def create_mock_skill(name: str, owner: Optional[str] = None) -> Mock:
    """Helper to create a mock SkillFunction."""
    skill = Mock()
    skill.get_function_name.return_value = name
    skill.get_owner_skillkit.return_value = owner
    # Add owner_name property that SkillMatcher now uses
    skill.owner_name = owner
    return skill


class TestMatchSkillName(unittest.TestCase):
    """Test basic skill name matching with fnmatch patterns."""

    def test_exact_match(self):
        """Exact name should match exactly."""
        self.assertTrue(SkillMatcher.match_skill_name("my_tool", "my_tool"))
        self.assertFalse(SkillMatcher.match_skill_name("my_tool", "other_tool"))

    def test_wildcard_suffix(self):
        """Pattern 'prefix*' should match names starting with prefix."""
        self.assertTrue(SkillMatcher.match_skill_name("playwright_navigate", "playwright*"))
        self.assertTrue(SkillMatcher.match_skill_name("playwright", "playwright*"))
        self.assertFalse(SkillMatcher.match_skill_name("other_tool", "playwright*"))

    def test_wildcard_prefix(self):
        """Pattern '*suffix' should match names ending with suffix."""
        self.assertTrue(SkillMatcher.match_skill_name("browser_navigate", "*_navigate"))
        self.assertFalse(SkillMatcher.match_skill_name("browser_click", "*_navigate"))

    def test_wildcard_middle(self):
        """Pattern 'prefix*suffix' should match names with prefix and suffix."""
        self.assertTrue(SkillMatcher.match_skill_name("playwright_browser_navigate", "playwright*navigate"))
        self.assertFalse(SkillMatcher.match_skill_name("playwright_browser_click", "playwright*navigate"))

    def test_single_char_wildcard(self):
        """Pattern with '?' should match single character."""
        self.assertTrue(SkillMatcher.match_skill_name("tool_v1", "tool_v?"))
        self.assertTrue(SkillMatcher.match_skill_name("tool_v2", "tool_v?"))
        self.assertFalse(SkillMatcher.match_skill_name("tool_v10", "tool_v?"))


class TestMatchSkillNames(unittest.TestCase):
    """Test matching against multiple patterns."""

    def test_match_any_pattern(self):
        """Should return True if any pattern matches."""
        patterns = ["playwright*", "_python", "sql*"]
        self.assertTrue(SkillMatcher.match_skill_names("playwright_navigate", patterns))
        self.assertTrue(SkillMatcher.match_skill_names("_python", patterns))
        self.assertTrue(SkillMatcher.match_skill_names("sql_query", patterns))
        self.assertFalse(SkillMatcher.match_skill_names("other_tool", patterns))

    def test_empty_patterns(self):
        """Empty pattern list should not match anything."""
        self.assertFalse(SkillMatcher.match_skill_names("any_tool", []))


class TestFilterSkillsByPattern(unittest.TestCase):
    """Test filtering skill lists."""

    def setUp(self):
        self.skills = [
            create_mock_skill("playwright_navigate"),
            create_mock_skill("playwright_click"),
            create_mock_skill("_python"),
            create_mock_skill("sql_query"),
        ]

    def test_filter_by_single_pattern(self):
        """Filter should return only matching skills."""
        result = SkillMatcher.filter_skills_by_pattern(self.skills, "playwright*")
        self.assertEqual(len(result), 2)
        names = [s.get_function_name() for s in result]
        self.assertIn("playwright_navigate", names)
        self.assertIn("playwright_click", names)

    def test_filter_by_multiple_patterns(self):
        """Filter should return skills matching any pattern."""
        result = SkillMatcher.filter_skills_by_patterns(self.skills, ["playwright*", "_python"])
        self.assertEqual(len(result), 3)


class TestGetOwnerSkillkits(unittest.TestCase):
    """Test collecting owner skillkit names."""

    def test_collect_owners(self):
        """Should collect unique owner names."""
        skills = [
            create_mock_skill("tool1", "skillkit_a"),
            create_mock_skill("tool2", "skillkit_a"),
            create_mock_skill("tool3", "skillkit_b"),
            create_mock_skill("tool4", None),
        ]
        owners = SkillMatcher.get_owner_skillkits(skills)
        self.assertEqual(owners, {"skillkit_a", "skillkit_b"})

    def test_empty_skills(self):
        """Empty skills list should return empty set."""
        owners = SkillMatcher.get_owner_skillkits([])
        self.assertEqual(owners, set())


class TestSplitNamespacedPattern(unittest.TestCase):
    """Test pattern namespace splitting."""

    def test_plain_pattern(self):
        """Plain pattern without namespace."""
        owner_names = {"resource_skillkit", "mcp_skillkit"}
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("my_tool", owner_names)
        self.assertIsNone(owner)
        self.assertEqual(suffix, "my_tool")
        self.assertFalse(is_ns)

    def test_namespaced_pattern(self):
        """Pattern with skillkit namespace."""
        owner_names = {"resource_skillkit", "mcp_skillkit"}
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern(
            "resource_skillkit.load_*", owner_names
        )
        self.assertEqual(owner, "resource_skillkit")
        self.assertEqual(suffix, "load_*")
        self.assertTrue(is_ns)

    def test_skillkit_name_only(self):
        """Skillkit name alone should expand to '.*'."""
        owner_names = {"resource_skillkit"}
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern(
            "resource_skillkit", owner_names
        )
        self.assertEqual(owner, "resource_skillkit")
        self.assertEqual(suffix, "*")
        self.assertTrue(is_ns)

    def test_empty_owner_names(self):
        """Empty owner names should treat as non-namespaced."""
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern(
            "resource_skillkit.tool", set()
        )
        self.assertIsNone(owner)
        self.assertEqual(suffix, "resource_skillkit.tool")
        self.assertFalse(is_ns)

    def test_longest_prefix_match(self):
        """Should use longest matching owner prefix."""
        owner_names = {"mcp", "mcp.browser"}
        # "mcp.browser.navigate" should match "mcp.browser", not "mcp"
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern(
            "mcp.browser.navigate", owner_names
        )
        self.assertEqual(owner, "mcp.browser")
        self.assertEqual(suffix, "navigate")
        self.assertTrue(is_ns)


class TestMatchSkill(unittest.TestCase):
    """Test full skill matching with namespace support."""

    def test_plain_pattern_match(self):
        """Plain pattern should match by skill name."""
        skill = create_mock_skill("my_tool", "some_skillkit")
        self.assertTrue(SkillMatcher.match_skill(skill, "my_tool"))
        self.assertTrue(SkillMatcher.match_skill(skill, "my_*"))
        self.assertFalse(SkillMatcher.match_skill(skill, "other_tool"))

    def test_namespaced_pattern_match(self):
        """Namespaced pattern should match by owner and name."""
        skill = create_mock_skill("load_resource", "resource_skillkit")
        owner_names = {"resource_skillkit"}

        # Should match: correct owner + matching name
        self.assertTrue(SkillMatcher.match_skill(skill, "resource_skillkit.load_*", owner_names))

        # Should not match: wrong owner
        skill_other = create_mock_skill("load_resource", "other_skillkit")
        self.assertFalse(SkillMatcher.match_skill(skill_other, "resource_skillkit.load_*", owner_names))

    def test_skillkit_name_matches_all(self):
        """Skillkit name alone should match all skills from that skillkit."""
        skill = create_mock_skill("any_tool", "resource_skillkit")
        owner_names = {"resource_skillkit"}
        self.assertTrue(SkillMatcher.match_skill(skill, "resource_skillkit", owner_names))


class TestMatchSkillsBatch(unittest.TestCase):
    """Test batch matching with deduplication."""

    def setUp(self):
        self.skills = [
            create_mock_skill("playwright_navigate", "mcp_skillkit"),
            create_mock_skill("playwright_click", "mcp_skillkit"),
            create_mock_skill("_python", None),
            create_mock_skill("load_resource", "resource_skillkit"),
        ]
        self.owner_names = {"mcp_skillkit", "resource_skillkit"}

    def test_batch_match_multiple_patterns(self):
        """Should match skills against multiple patterns."""
        patterns = ["playwright*", "_python"]
        matched, any_ns = SkillMatcher.match_skills_batch(
            self.skills, patterns, self.owner_names
        )
        self.assertEqual(len(matched), 3)
        names = [s.get_function_name() for s in matched]
        self.assertIn("playwright_navigate", names)
        self.assertIn("playwright_click", names)
        self.assertIn("_python", names)
        self.assertFalse(any_ns)

    def test_batch_match_deduplication(self):
        """Same skill should not appear twice even if matching multiple patterns."""
        # Both patterns match "playwright_navigate"
        patterns = ["playwright*", "*_navigate"]
        matched, _ = SkillMatcher.match_skills_batch(
            self.skills, patterns, self.owner_names
        )
        # Should be deduplicated
        navigate_count = sum(
            1 for s in matched if s.get_function_name() == "playwright_navigate"
        )
        self.assertEqual(navigate_count, 1)

    def test_batch_match_namespaced_patterns(self):
        """Should correctly identify namespaced patterns."""
        patterns = ["mcp_skillkit.playwright*", "_python"]
        matched, any_ns = SkillMatcher.match_skills_batch(
            self.skills, patterns, self.owner_names
        )
        self.assertTrue(any_ns)
        self.assertEqual(len(matched), 3)

    def test_batch_match_empty_patterns(self):
        """Empty patterns should return empty results."""
        matched, any_ns = SkillMatcher.match_skills_batch(
            self.skills, [], self.owner_names
        )
        self.assertEqual(len(matched), 0)
        self.assertFalse(any_ns)

    def test_batch_match_no_matches(self):
        """Non-matching patterns should return empty results."""
        patterns = ["nonexistent_*"]
        matched, any_ns = SkillMatcher.match_skills_batch(
            self.skills, patterns, self.owner_names
        )
        self.assertEqual(len(matched), 0)
        self.assertFalse(any_ns)

    def test_batch_match_preserves_order(self):
        """Matched skills should maintain original order."""
        patterns = ["*"]  # Match all
        matched, _ = SkillMatcher.match_skills_batch(
            self.skills, patterns, self.owner_names
        )
        self.assertEqual(len(matched), len(self.skills))
        for i, skill in enumerate(matched):
            self.assertEqual(skill.get_function_name(), self.skills[i].get_function_name())


class TestSplitNamespacedPatternWithSortedOwners(unittest.TestCase):
    """Test the optimized split function with pre-sorted owners."""

    def test_with_sorted_owners(self):
        """Should work correctly with pre-sorted owners."""
        owner_names = {"mcp", "mcp.browser"}
        sorted_owners = sorted(owner_names, key=len, reverse=True)

        owner, suffix, is_ns = SkillMatcher._split_namespaced_pattern_with_sorted_owners(
            "mcp.browser.navigate", owner_names, sorted_owners
        )
        self.assertEqual(owner, "mcp.browser")
        self.assertEqual(suffix, "navigate")
        self.assertTrue(is_ns)


class TestMissingMethods(unittest.TestCase):
    """Test methods that currently have no coverage."""

    def setUp(self):
        self.skills = [
            create_mock_skill("tool_a"),
            create_mock_skill("tool_b"),
            create_mock_skill("tool_c"),
        ]

    def test_find_first_matching_skill_found(self):
        """Should return first matching skill."""
        result = SkillMatcher.find_first_matching_skill(self.skills, "tool_*")
        self.assertEqual(result.get_function_name(), "tool_a")

    def test_find_first_matching_skill_not_found(self):
        """Should return None when no match."""
        result = SkillMatcher.find_first_matching_skill(self.skills, "nonexistent*")
        self.assertIsNone(result)

    def test_find_first_matching_skill_exact_match(self):
        """Should find skill by exact name."""
        result = SkillMatcher.find_first_matching_skill(self.skills, "tool_b")
        self.assertEqual(result.get_function_name(), "tool_b")

    def test_get_matching_skills_with_none(self):
        """None skill_names should return all skills."""
        result = SkillMatcher.get_matching_skills(self.skills, None)
        self.assertEqual(len(result), 3)

    def test_get_matching_skills_with_patterns(self):
        """Should filter using pattern list."""
        result = SkillMatcher.get_matching_skills(self.skills, ["tool_a", "tool_c"])
        self.assertEqual(len(result), 2)

    def test_get_matching_skills_by_names_exact(self):
        """Should match by exact names only (no wildcards)."""
        result = SkillMatcher.get_matching_skills_by_names(self.skills, ["tool_a", "tool_c"])
        self.assertEqual(len(result), 2)
        names = [s.get_function_name() for s in result]
        self.assertIn("tool_a", names)
        self.assertIn("tool_c", names)

    def test_get_matching_skills_by_names_no_wildcard(self):
        """Wildcards should NOT work in get_matching_skills_by_names."""
        result = SkillMatcher.get_matching_skills_by_names(self.skills, ["tool_*"])
        self.assertEqual(len(result), 0)  # No exact match for "tool_*"

    def test_get_skill_by_name_exact(self):
        """Should return skill by exact name."""
        result = SkillMatcher.get_skill_by_name(self.skills, "tool_b")
        self.assertEqual(result.get_function_name(), "tool_b")

    def test_get_skill_by_name_pattern(self):
        """Should return first skill matching pattern."""
        result = SkillMatcher.get_skill_by_name(self.skills, "*_c")
        self.assertEqual(result.get_function_name(), "tool_c")

    def test_get_skill_by_name_not_found(self):
        """Should return None when not found."""
        result = SkillMatcher.get_skill_by_name(self.skills, "nonexistent")
        self.assertIsNone(result)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and special scenarios."""

    def test_case_sensitivity(self):
        """fnmatch is case-sensitive by default."""
        self.assertTrue(SkillMatcher.match_skill_name("MyTool", "MyTool"))
        self.assertFalse(SkillMatcher.match_skill_name("MyTool", "mytool"))
        self.assertFalse(SkillMatcher.match_skill_name("mytool", "MyTool"))

    def test_case_sensitivity_with_wildcard(self):
        """Case sensitivity should apply to wildcards too."""
        self.assertTrue(SkillMatcher.match_skill_name("MyTool", "My*"))
        self.assertFalse(SkillMatcher.match_skill_name("MyTool", "my*"))

    def test_special_characters_underscore_prefix(self):
        """Skills with underscore prefix should match correctly."""
        self.assertTrue(SkillMatcher.match_skill_name("_private_tool", "_*"))
        self.assertTrue(SkillMatcher.match_skill_name("_private_tool", "_private_*"))

    def test_special_characters_hyphen(self):
        """Skills with hyphens should match correctly."""
        self.assertTrue(SkillMatcher.match_skill_name("tool-v2", "tool-*"))
        self.assertTrue(SkillMatcher.match_skill_name("my-cool-tool", "*-cool-*"))

    def test_pattern_with_dot_not_namespace(self):
        """Pattern with dot should NOT be treated as namespace if owner not in set."""
        skill = create_mock_skill("some.tool.name", None)
        owner_names = {"other_skillkit"}
        # Should match the full pattern as skill name
        self.assertTrue(SkillMatcher.match_skill(skill, "some.tool.name", owner_names))
        self.assertTrue(SkillMatcher.match_skill(skill, "some.tool.*", owner_names))

    def test_namespaced_pattern_skill_without_owner(self):
        """Namespaced pattern should NOT match skill with no owner."""
        skill = create_mock_skill("load_resource", None)  # No owner
        owner_names = {"resource_skillkit"}
        self.assertFalse(
            SkillMatcher.match_skill(skill, "resource_skillkit.load_*", owner_names)
        )

    def test_empty_pattern_string(self):
        """Empty pattern should match only empty skill name."""
        self.assertTrue(SkillMatcher.match_skill_name("", ""))
        self.assertFalse(SkillMatcher.match_skill_name("tool", ""))

    def test_empty_skill_name(self):
        """Empty skill name should only match empty or * pattern."""
        self.assertTrue(SkillMatcher.match_skill_name("", ""))
        self.assertTrue(SkillMatcher.match_skill_name("", "*"))
        self.assertFalse(SkillMatcher.match_skill_name("", "tool*"))

    def test_filter_empty_skills_list(self):
        """Filtering empty skill list should return empty list."""
        result = SkillMatcher.filter_skills_by_pattern([], "any*")
        self.assertEqual(result, [])

    def test_filter_by_patterns_empty_skills_list(self):
        """Filtering empty skill list with multiple patterns should return empty list."""
        result = SkillMatcher.filter_skills_by_patterns([], ["any*", "other*"])
        self.assertEqual(result, [])

    def test_batch_match_skill_matches_multiple_patterns(self):
        """Skill matching multiple patterns should appear only once (dedup)."""
        skills = [create_mock_skill("abc_xyz")]
        patterns = ["abc*", "*xyz", "abc_xyz"]
        matched, _ = SkillMatcher.match_skills_batch(skills, patterns)
        self.assertEqual(len(matched), 1)

    def test_match_star_only(self):
        """Single * should match any skill name."""
        self.assertTrue(SkillMatcher.match_skill_name("anything", "*"))
        self.assertTrue(SkillMatcher.match_skill_name("", "*"))
        self.assertTrue(SkillMatcher.match_skill_name("very_long_skill_name_here", "*"))

    def test_double_wildcard(self):
        """Pattern with ** should work like * (fnmatch behavior)."""
        self.assertTrue(SkillMatcher.match_skill_name("abc", "**"))
        self.assertTrue(SkillMatcher.match_skill_name("abc", "a**"))


class TestNamespaceComplexCases(unittest.TestCase):
    """Complex namespace matching scenarios."""

    def test_owner_name_with_underscore(self):
        """Owner names with underscores should work correctly."""
        owner_names = {"mcp", "mcp_browser"}

        # "mcp.tool" should match "mcp" as owner
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("mcp.tool", owner_names)
        self.assertEqual(owner, "mcp")
        self.assertEqual(suffix, "tool")
        self.assertTrue(is_ns)

        # "mcp_browser.tool" should match "mcp_browser" as owner
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern(
            "mcp_browser.tool", owner_names
        )
        self.assertEqual(owner, "mcp_browser")
        self.assertEqual(suffix, "tool")
        self.assertTrue(is_ns)

    def test_trailing_dot_in_pattern(self):
        """Pattern ending with dot after owner name."""
        owner_names = {"skillkit"}
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("skillkit.", owner_names)
        # Empty suffix should become "*"
        self.assertEqual(owner, "skillkit")
        self.assertEqual(suffix, "*")
        self.assertTrue(is_ns)

    def test_multiple_dots_in_suffix(self):
        """Suffix with dots (owner.a.b.c)."""
        owner_names = {"owner"}
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("owner.a.b.c", owner_names)
        self.assertEqual(owner, "owner")
        self.assertEqual(suffix, "a.b.c")
        self.assertTrue(is_ns)

    def test_owner_name_is_prefix_of_another(self):
        """When one owner name is prefix of another (with dot separator)."""
        owner_names = {"api", "api.v2"}

        # "api.tool" should match "api" (shorter owner)
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("api.tool", owner_names)
        self.assertEqual(owner, "api")
        self.assertEqual(suffix, "tool")

        # "api.v2.tool" should match "api.v2" (longer prefix wins)
        owner, suffix, is_ns = SkillMatcher.split_namespaced_pattern("api.v2.tool", owner_names)
        self.assertEqual(owner, "api.v2")
        self.assertEqual(suffix, "tool")

    def test_namespaced_match_wrong_owner(self):
        """Namespaced pattern should not match skill from different owner."""
        skill = create_mock_skill("load_data", "other_skillkit")
        owner_names = {"resource_skillkit", "other_skillkit"}

        # Pattern specifies resource_skillkit, but skill belongs to other_skillkit
        self.assertFalse(
            SkillMatcher.match_skill(skill, "resource_skillkit.load_*", owner_names)
        )

        # Same pattern should match if skill belongs to correct owner
        skill_correct = create_mock_skill("load_data", "resource_skillkit")
        self.assertTrue(
            SkillMatcher.match_skill(skill_correct, "resource_skillkit.load_*", owner_names)
        )

    def test_batch_match_mixed_namespaced_and_plain(self):
        """Batch matching with mix of namespaced and plain patterns."""
        skills = [
            create_mock_skill("tool_a", "skillkit_x"),
            create_mock_skill("tool_b", "skillkit_y"),
            create_mock_skill("tool_c", None),
        ]
        owner_names = {"skillkit_x", "skillkit_y"}

        # Mix of namespaced and plain patterns
        patterns = ["skillkit_x.*", "tool_c"]
        matched, any_ns = SkillMatcher.match_skills_batch(skills, patterns, owner_names)

        self.assertTrue(any_ns)
        self.assertEqual(len(matched), 2)
        names = [s.get_function_name() for s in matched]
        self.assertIn("tool_a", names)  # Matched by skillkit_x.*
        self.assertIn("tool_c", names)  # Matched by tool_c

    def test_owner_only_pattern_matches_all_skills_from_owner(self):
        """Skillkit name alone should match all skills from that owner."""
        skills = [
            create_mock_skill("skill_1", "my_skillkit"),
            create_mock_skill("skill_2", "my_skillkit"),
            create_mock_skill("skill_3", "other_skillkit"),
        ]
        owner_names = {"my_skillkit", "other_skillkit"}

        patterns = ["my_skillkit"]
        matched, any_ns = SkillMatcher.match_skills_batch(skills, patterns, owner_names)

        self.assertTrue(any_ns)
        self.assertEqual(len(matched), 2)
        for s in matched:
            self.assertEqual(s.get_owner_skillkit(), "my_skillkit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
