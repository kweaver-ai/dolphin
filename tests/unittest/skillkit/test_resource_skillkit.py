"""Unit tests for Claude Skill format support.

This module tests:
1. Claude Skills fixtures validity and structure
2. SkillLoader parsing compatibility
3. ResourceSkillkit three-level progressive loading
4. Integration with Dolphin's skillkit system

Test fixtures are downloaded from:
- Anthropic official: https://github.com/anthropics/skills
- Superpowers community: https://github.com/obra/superpowers
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from unittest.mock import patch


# Get the fixtures directory path
FIXTURES_BASE = Path(__file__).parent.parent.parent / "fixtures" / "skills"
ANTHROPIC_SKILLS_DIR = FIXTURES_BASE / "anthropic"
SUPERPOWERS_SKILLS_DIR = FIXTURES_BASE / "superpowers"

# Project skills directory (for ResourceSkillkit integration tests)
PROJECT_SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "skills"


def get_all_skill_files() -> List[Path]:
    """Get all skill markdown files from fixtures."""
    skills = []
    for skills_dir in [ANTHROPIC_SKILLS_DIR, SUPERPOWERS_SKILLS_DIR]:
        if skills_dir.exists():
            skills.extend(skills_dir.glob("*.md"))
    return sorted(skills)


def parse_frontmatter(content: str) -> tuple[Dict[str, Any] | None, str]:
    """Parse YAML frontmatter from skill content.

    Args:
        content: The full file content

    Returns:
        Tuple of (frontmatter_dict, body). frontmatter_dict is None if not found.
    """
    import re
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
    match = pattern.match(content)

    if not match:
        return None, content

    yaml_content = match.group(1)
    body = match.group(2)

    try:
        frontmatter = yaml.safe_load(yaml_content)
        if not isinstance(frontmatter, dict):
            return None, content
        return frontmatter, body
    except yaml.YAMLError:
        return None, content


class TestSkillFixturesExist(unittest.TestCase):
    """Test that skill fixtures exist."""

    def test_fixtures_directory_exists(self):
        """Test that fixtures base directory exists."""
        self.assertTrue(FIXTURES_BASE.exists(), f"Fixtures directory not found: {FIXTURES_BASE}")

    def test_anthropic_skills_exist(self):
        """Test that Anthropic official skills exist."""
        self.assertTrue(
            ANTHROPIC_SKILLS_DIR.exists(),
            f"Anthropic skills directory not found: {ANTHROPIC_SKILLS_DIR}"
        )
        skills = list(ANTHROPIC_SKILLS_DIR.glob("*.md"))
        self.assertGreater(len(skills), 0, "No Anthropic skills found")

    def test_superpowers_skills_exist(self):
        """Test that Superpowers community skills exist."""
        self.assertTrue(
            SUPERPOWERS_SKILLS_DIR.exists(),
            f"Superpowers skills directory not found: {SUPERPOWERS_SKILLS_DIR}"
        )
        skills = list(SUPERPOWERS_SKILLS_DIR.glob("*.md"))
        self.assertGreater(len(skills), 0, "No Superpowers skills found")



class TestSkillFrontmatter(unittest.TestCase):
    """Test YAML frontmatter parsing for all skill fixtures."""

    def test_all_skills_have_valid_frontmatter(self):
        """Test that all skill files have valid YAML frontmatter."""
        skills = get_all_skill_files()
        self.assertGreater(len(skills), 0, "No skill files found")

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                self.assertIsNotNone(
                    frontmatter,
                    f"Skill {skill_path.name} has no valid YAML frontmatter"
                )

    def test_all_skills_have_name_field(self):
        """Test that all skills have a 'name' field in frontmatter."""
        skills = get_all_skill_files()

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                self.assertIsNotNone(frontmatter)
                self.assertIn(
                    "name", frontmatter,
                    f"Skill {skill_path.name} missing 'name' field"
                )
                self.assertTrue(
                    frontmatter["name"],
                    f"Skill {skill_path.name} has empty 'name' field"
                )

    def test_all_skills_have_description_field(self):
        """Test that all skills have a 'description' field in frontmatter."""
        skills = get_all_skill_files()

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                self.assertIsNotNone(frontmatter)
                self.assertIn(
                    "description", frontmatter,
                    f"Skill {skill_path.name} missing 'description' field"
                )
                self.assertTrue(
                    frontmatter["description"],
                    f"Skill {skill_path.name} has empty 'description' field"
                )

    def test_name_is_valid_identifier(self):
        """Test that skill names are valid identifiers (lowercase, hyphens)."""
        skills = get_all_skill_files()
        import re

        # Pattern for valid skill names: lowercase letters, numbers, hyphens
        valid_name_pattern = re.compile(r"^[a-z][a-z0-9-]*$")

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                self.assertIsNotNone(frontmatter)
                name = frontmatter.get("name", "")

                self.assertTrue(
                    valid_name_pattern.match(name),
                    f"Skill name '{name}' in {skill_path.name} is not a valid identifier "
                    "(should be lowercase with hyphens)"
                )


class TestSkillContent(unittest.TestCase):
    """Test skill content structure and quality."""

    def test_all_skills_have_body_content(self):
        """Test that all skills have non-empty body content."""
        skills = get_all_skill_files()

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                _, body = parse_frontmatter(content)

                body = body.strip()
                self.assertTrue(
                    len(body) > 100,
                    f"Skill {skill_path.name} has insufficient body content (< 100 chars)"
                )

    def test_all_skills_have_markdown_headers(self):
        """Test that all skills have at least one markdown header."""
        skills = get_all_skill_files()

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                _, body = parse_frontmatter(content)

                # Check for markdown headers (# or ##)
                has_header = any(
                    line.strip().startswith("#")
                    for line in body.split("\n")
                )

                self.assertTrue(
                    has_header,
                    f"Skill {skill_path.name} has no markdown headers"
                )

    def test_skill_file_sizes_reasonable(self):
        """Test that skill files are within reasonable size limits."""
        skills = get_all_skill_files()

        MIN_SIZE = 500  # Minimum 500 bytes
        MAX_SIZE = 100 * 1024  # Maximum 100KB

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                size = skill_path.stat().st_size

                self.assertGreaterEqual(
                    size, MIN_SIZE,
                    f"Skill {skill_path.name} is too small ({size} bytes < {MIN_SIZE})"
                )
                self.assertLessEqual(
                    size, MAX_SIZE,
                    f"Skill {skill_path.name} is too large ({size} bytes > {MAX_SIZE})"
                )


class TestAnthropicSkills(unittest.TestCase):
    """Test Anthropic official skills specifically."""

    def test_expected_anthropic_skills_present(self):
        """Test that expected Anthropic skills are present."""
        expected_skills = [
            "mcp-builder.md",
            "skill-creator.md",
            "webapp-testing.md",
            "algorithmic-art.md",
        ]

        if not ANTHROPIC_SKILLS_DIR.exists():
            self.skipTest("Anthropic skills directory not found")

        actual_skills = [f.name for f in ANTHROPIC_SKILLS_DIR.glob("*.md")]

        for expected in expected_skills:
            self.assertIn(
                expected, actual_skills,
                f"Expected Anthropic skill '{expected}' not found"
            )

    def test_anthropic_skills_have_license_field(self):
        """Test that Anthropic skills include license information."""
        if not ANTHROPIC_SKILLS_DIR.exists():
            self.skipTest("Anthropic skills directory not found")

        for skill_path in ANTHROPIC_SKILLS_DIR.glob("*.md"):
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                self.assertIsNotNone(frontmatter)
                self.assertIn(
                    "license", frontmatter,
                    f"Anthropic skill {skill_path.name} missing 'license' field"
                )


class TestSuperpowersSkills(unittest.TestCase):
    """Test Superpowers community skills specifically."""

    def test_expected_superpowers_skills_present(self):
        """Test that expected Superpowers skills are present."""
        expected_skills = [
            "test-driven-development.md",
            "systematic-debugging.md",
            "brainstorming.md",
        ]

        if not SUPERPOWERS_SKILLS_DIR.exists():
            self.skipTest("Superpowers skills directory not found")

        actual_skills = [f.name for f in SUPERPOWERS_SKILLS_DIR.glob("*.md")]

        for expected in expected_skills:
            self.assertIn(
                expected, actual_skills,
                f"Expected Superpowers skill '{expected}' not found"
            )

    def test_tdd_skill_has_key_concepts(self):
        """Test that TDD skill contains key TDD concepts."""
        skill_path = SUPERPOWERS_SKILLS_DIR / "test-driven-development.md"

        if not skill_path.exists():
            self.skipTest("TDD skill not found")

        content = skill_path.read_text(encoding="utf-8").lower()

        key_concepts = ["red", "green", "refactor", "test"]
        for concept in key_concepts:
            self.assertIn(
                concept, content,
                f"TDD skill missing key concept: {concept}"
            )


class TestSkillLoaderCompatibility(unittest.TestCase):
    """Test compatibility with the actual SkillLoader class."""

    @classmethod
    def setUpClass(cls):
        """Try to import SkillLoader."""
        try:
            from dolphin.lib.skillkits.resource.skill_loader import SkillLoader
            cls.SkillLoader = SkillLoader
            cls.loader_available = True
        except ImportError:
            cls.loader_available = False

    def test_skills_parseable_by_skill_loader(self):
        """Test that skills can be parsed by SkillLoader._parse_frontmatter."""
        if not self.loader_available:
            self.skipTest("SkillLoader not available")

        loader = self.SkillLoader()
        skills = get_all_skill_files()

        for skill_path in skills:
            with self.subTest(skill=skill_path.name):
                content = skill_path.read_text(encoding="utf-8")
                frontmatter, body = loader._parse_frontmatter(content)

                self.assertIsNotNone(
                    frontmatter,
                    f"SkillLoader failed to parse {skill_path.name}"
                )
                self.assertIn("name", frontmatter)
                self.assertIn("description", frontmatter)
                self.assertTrue(len(body.strip()) > 0)


class TestSkillStatistics(unittest.TestCase):
    """Test and report statistics about skill fixtures."""

    def test_total_skill_count(self):
        """Test and report total number of skill fixtures."""
        skills = get_all_skill_files()

        anthropic_count = len(list(ANTHROPIC_SKILLS_DIR.glob("*.md"))) if ANTHROPIC_SKILLS_DIR.exists() else 0
        superpowers_count = len(list(SUPERPOWERS_SKILLS_DIR.glob("*.md"))) if SUPERPOWERS_SKILLS_DIR.exists() else 0

        total = anthropic_count + superpowers_count

        # Expect at least 7 skills total (4 Anthropic + 3 Superpowers)
        self.assertGreaterEqual(
            total, 7,
            f"Expected at least 7 skill fixtures, found {total}"
        )

        # Log statistics (will be visible in verbose test output)
        print(f"\n=== Skill Fixtures Statistics ===")
        print(f"Anthropic Official: {anthropic_count}")
        print(f"Superpowers:        {superpowers_count}")
        print(f"Total:              {total}")

    def test_skill_categories_diverse(self):
        """Test that skills cover diverse categories/tags."""
        skills = get_all_skill_files()

        all_tags = set()
        skills_with_tags = 0

        for skill_path in skills:
            content = skill_path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)

            if frontmatter and "tags" in frontmatter:
                tags = frontmatter["tags"]
                if isinstance(tags, list):
                    all_tags.update(tags)
                    skills_with_tags += 1

        # Print tag statistics
        print(f"\n=== Skill Tags ===")
        print(f"Skills with tags: {skills_with_tags}/{len(skills)}")
        if all_tags:
            print(f"Unique tags: {sorted(all_tags)}")


class TestResourceSkillkitEntryPointLoading(unittest.TestCase):
    """验证 ResourceSkillkit 通过 entry-points 可被 GlobalSkills 发现并加载。

    这用于防止：entry-point 加载成功后 fallback 不触发，从而导致未注册 entry-point 的 skillkit 永远加载不到。
    """

    def test_entrypoint_registered_in_pyproject(self):
        """确保 resource_skillkit 已注册到 dolphin.skillkits entry-points。"""
        pyproject = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        self.assertIn(
            'resource = "dolphin.lib.skillkits.resource_skillkit:ResourceSkillkit"',
            text,
        )

    def test_resource_skillkit_loads_via_entry_points(self):
        """通过模拟 entry_points() 返回值，验证 GlobalSkills 的 entry-point 加载路径可加载 resource_skillkit。"""
        from importlib.metadata import EntryPoint

        from dolphin.core.config.global_config import (
            GlobalConfig,
            SkillConfig,
            MCPConfig,
        )
        from dolphin.sdk.skill.global_skills import GlobalSkills

        def fake_entry_points(*, group: str):
            if group != "dolphin.skillkits":
                return []
            return [
                EntryPoint(
                    name="resource_skillkit",
                    value="dolphin.lib.skillkits.resource_skillkit:ResourceSkillkit",
                    group="dolphin.skillkits",
                )
            ]

        config = GlobalConfig(
            skill_config=SkillConfig(enabled_skills=["resource_skillkit"]),
            mcp_config=MCPConfig(enabled=False),
        )

        with patch(
            "dolphin.sdk.skill.global_skills.importlib.metadata.entry_points",
            new=fake_entry_points,
        ):
            global_skills = GlobalSkills(config)

        skill_names = set(global_skills.installedSkillset.getSkillNames())
        # Note: _list_resource_skills is removed; Level 1 metadata is auto-injected
        self.assertIn("_load_resource_skill", skill_names)
        self.assertIn("_load_skill_resource", skill_names)

    def test_resource_skillkit_reads_global_resource_skills_config(self):
        """验证 ResourceSkillkit 可从 GlobalConfig.resource_skills 读取扫描目录等配置。"""
        from importlib.metadata import EntryPoint

        from dolphin.core.config.global_config import (
            GlobalConfig,
            SkillConfig,
            MCPConfig,
        )
        from dolphin.sdk.skill.global_skills import GlobalSkills

        with tempfile.TemporaryDirectory(prefix="test_resource_skills_") as temp_dir:
            # Create a minimal skill package
            skill_dir = Path(temp_dir) / "test-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: test-skill\ndescription: a test skill\n---\n\n# Test\n\nBody\n",
                encoding="utf-8",
            )

            def fake_entry_points(*, group: str):
                if group != "dolphin.skillkits":
                    return []
                return [
                    EntryPoint(
                        name="resource_skillkit",
                        value="dolphin.lib.skillkits.resource_skillkit:ResourceSkillkit",
                        group="dolphin.skillkits",
                    )
                ]

            config = GlobalConfig(
                skill_config=SkillConfig(enabled_skills=["resource_skillkit"]),
                mcp_config=MCPConfig(enabled=False),
                resource_skills={
                    "enabled": True,
                    "directories": [temp_dir],
                    "limits": {"max_skill_size_mb": 8, "max_content_tokens": 8000},
                },
            )

            with patch(
                "dolphin.sdk.skill.global_skills.importlib.metadata.entry_points",
                new=fake_entry_points,
            ):
                global_skills = GlobalSkills(config)

            # Metadata is now collected via skill.owner_skillkit, not Skillset.get_metadata_prompt()
            # Find skills from ResourceSkillkit and check their owner has metadata
            resource_skills = [
                s for s in global_skills.installedSkillset.getSkills()
                if hasattr(s, 'owner_skillkit') and s.owner_skillkit is not None
                and hasattr(s.owner_skillkit, 'get_metadata_prompt')
            ]
            self.assertTrue(len(resource_skills) > 0, "No ResourceSkillkit skills found")
            
            # Get metadata from owner skillkit
            metadata_prompt = resource_skills[0].owner_skillkit.get_metadata_prompt()
            self.assertTrue(len(metadata_prompt) > 0, "No metadata prompt generated")
            self.assertIn("test-skill", metadata_prompt)


class TestResourceSkillkitIntegration(unittest.TestCase):
    """Test ResourceSkillkit integration with skill fixtures.

    These tests verify the three-level progressive loading:
    - Level 1: Metadata (~100 tokens) - system prompt injection
    - Level 2: Full SKILL.md content (~1500 tokens) - tool response
    - Level 3: Resource files (scripts/references) - on-demand
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for ResourceSkillkit tests."""
        try:
            from dolphin.lib.skillkits.resource import (
                ResourceSkillkit,
            )
            from dolphin.lib.skillkits.resource.models.skill_config import (
                ResourceSkillConfig,
            )
            from dolphin.lib.skillkits.resource.skill_loader import (
                SkillLoader,
            )
            from dolphin.lib.skillkits.resource.models.skill_meta import (
                SkillMeta,
                SkillContent,
            )

            cls.ResourceSkillkit = ResourceSkillkit
            cls.ResourceSkillConfig = ResourceSkillConfig
            cls.SkillLoader = SkillLoader
            cls.SkillMeta = SkillMeta
            cls.SkillContent = SkillContent
            cls.skillkit_available = True
        except ImportError as e:
            cls.skillkit_available = False
            cls.import_error = str(e)

        # Create a temporary directory with proper skill structure
        cls.temp_dir = tempfile.mkdtemp(prefix="test_skills_")
        cls._setup_test_skills()

    @classmethod
    def _setup_test_skills(cls):
        """Set up test skills in temp directory with proper structure."""
        if not cls.skillkit_available:
            return

        # Create skill directories from fixtures
        for fixture_dir, source_name in [
            (SUPERPOWERS_SKILLS_DIR, "test-driven-development"),
            (ANTHROPIC_SKILLS_DIR, "mcp-builder"),
        ]:
            source_file = fixture_dir / f"{source_name}.md"
            if source_file.exists():
                skill_dir = Path(cls.temp_dir) / source_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(source_file, skill_dir / "SKILL.md")

        # Create a synthetic skill with scripts/ directory for Level 3 testing
        # since we removed the project-level data-pipeline skill
        synthetic_skill_dir = Path(cls.temp_dir) / "synthetic-skill"
        synthetic_skill_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SKILL.md
        (synthetic_skill_dir / "SKILL.md").write_text(
            "---\nname: synthetic-skill\ndescription: A test skill with resources\n---\n# Test Skill\nDescription", 
            encoding="utf-8"
        )
        
        # Create scripts directory and a test script
        scripts_dir = synthetic_skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "test.py").write_text("print('hello')", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary directory."""
        if hasattr(cls, 'temp_dir') and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def test_resourceskillkit_initialization(self):
        """Test ResourceSkillkit can be initialized with fixture skills."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Should have found skills
        available = skillkit.get_available_skills()
        self.assertGreater(len(available), 0, "No skills found after initialization")

    def test_level1_metadata_loading(self):
        """Test Level 1 metadata loading (~100 tokens per skill)."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Get metadata prompt for system injection (using renamed method)
        metadata_prompt = skillkit.get_metadata_prompt()

        # Should contain skill information
        self.assertIn("Available Resource Skills", metadata_prompt)
        # Verify at least one skill is listed in the metadata
        available_skills = skillkit.get_available_skills()
        self.assertTrue(
            any(skill in metadata_prompt for skill in available_skills),
            "No skill names found in metadata prompt"
        )

        # Should be reasonably sized for system prompt
        # Rough estimate: ~100 tokens ≈ 400 chars per skill
        max_expected_length = len(skillkit.get_available_skills()) * 500 + 200
        self.assertLess(
            len(metadata_prompt), max_expected_length,
            "Metadata prompt too large for system injection"
        )

    def test_metadata_prompt_when_no_skills(self):
        """Test that metadata prompt always includes section header, even with no skills."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        # Create skillkit with non-existent directory (no skills will be found)
        import tempfile
        empty_dir = tempfile.mkdtemp()

        config = self.ResourceSkillConfig(
            directories=[empty_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Get metadata prompt
        metadata_prompt = skillkit.get_metadata_prompt()

        # Should always include the section header to prevent LLM hallucination
        self.assertIn("## Available Resource Skills", metadata_prompt)
        # Should indicate no skills are available
        self.assertIn("No resource skills", metadata_prompt)
        # Should not be empty
        self.assertTrue(len(metadata_prompt) > 0)

    def test_level2_full_content_loading(self):
        """Test Level 2 full SKILL.md content loading."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        available = skillkit.get_available_skills()
        if not available:
            self.skipTest("No skills available for testing")

        # Load first available skill
        skill_name = available[0]
        content = skillkit.load_skill(skill_name)

        # Should return actual content, not error
        self.assertFalse(
            content.startswith("Error:"),
            f"Failed to load skill: {content}"
        )

        # Content should be substantial
        self.assertGreater(len(content), 100, "Skill content too short")

    def test_level2_skill_not_found_error(self):
        """Test Level 2 loading returns helpful error for unknown skill."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Try to load non-existent skill
        content = skillkit.load_skill("nonexistent-skill")

        # Should return error with available skills
        self.assertTrue(content.startswith("Error:"))
        self.assertIn("not found", content.lower())

    def test_level3_resource_loading(self):
        """Test Level 3 resource file loading (scripts/references)."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        # Check if synthetic skill with scripts exists
        synthetic_skill_dir = Path(self.temp_dir) / "synthetic-skill"
        scripts_dir = synthetic_skill_dir / "scripts"

        if not scripts_dir.exists():
            self.skipTest("Synthetic skill with scripts not available")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Load resource file
        content = skillkit.load_resource("synthetic-skill", "scripts/test.py")

        # Should return file content, not error
        self.assertFalse(
            content.startswith("Error:"),
            f"Failed to load resource: {content}"
        )

    def test_skill_meta_data_class(self):
        """Test SkillMeta data class functionality."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        meta = self.SkillMeta(
            name="test-skill",
            description="A test skill for unit testing",
            base_path="/tmp/test",
            version="1.0.0",
            tags=["test", "unittest"],
        )

        # Test to_prompt_entry
        prompt_entry = meta.to_prompt_entry()
        self.assertIn("test-skill", prompt_entry)
        self.assertIn("test skill", prompt_entry.lower())

        # Test to_dict
        meta_dict = meta.to_dict()
        self.assertEqual(meta_dict["name"], "test-skill")
        self.assertEqual(meta_dict["version"], "1.0.0")
        self.assertEqual(meta_dict["tags"], ["test", "unittest"])

    def test_skill_content_data_class(self):
        """Test SkillContent data class functionality."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        content = self.SkillContent(
            frontmatter={"name": "test", "description": "Test skill"},
            body="# Test Skill\n\nThis is a test.",
            available_scripts=["scripts/test.py"],
            available_references=["references/guide.md"],
        )

        # Test get_name and get_description
        self.assertEqual(content.get_name(), "test")
        self.assertEqual(content.get_description(), "Test skill")

        # Test get_full_content
        full = content.get_full_content()
        self.assertIn("Test Skill", full)
        self.assertIn("Available Resources", full)
        self.assertIn("scripts/test.py", full)
        self.assertIn("references/guide.md", full)

    def test_skillkit_interface_compliance(self):
        """Test ResourceSkillkit implements Skillkit interface."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        # Test getName
        self.assertEqual(skillkit.getName(), "resource_skillkit")

        # Test getSkills returns SkillFunction list
        # Note: _list_resource_skills is removed (Level 1 metadata auto-injected)
        skills = skillkit.getSkills()
        self.assertEqual(len(skills), 2)

        skill_names = [s.func.__name__ for s in skills]
        self.assertIn("_load_resource_skill", skill_names)
        self.assertIn("_load_skill_resource", skill_names)

    def test_cache_functionality(self):
        """Test that caching works correctly."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        available = skillkit.get_available_skills()
        if not available:
            self.skipTest("No skills available for testing")

        skill_name = available[0]

        # Load skill twice
        content1 = skillkit.load_skill(skill_name)
        content2 = skillkit.load_skill(skill_name)

        # Should return same content
        self.assertEqual(content1, content2)

        # Check cache stats
        stats = skillkit.get_stats()
        self.assertIn("content_cache", stats)

    def test_clear_caches(self):
        """Test cache clearing functionality."""
        if not self.skillkit_available:
            self.skipTest(f"ResourceSkillkit not available: {self.import_error}")

        config = self.ResourceSkillConfig(
            directories=[self.temp_dir],
            enabled=True,
        )
        skillkit = self.ResourceSkillkit(config)
        skillkit.initialize()

        available = skillkit.get_available_skills()
        if not available:
            self.skipTest("No skills available for testing")

        # Load a skill to populate cache
        skillkit.load_skill(available[0])

        # Clear caches
        skillkit.clear_caches()

        # Stats should show empty caches
        stats = skillkit.get_stats()
        self.assertEqual(stats["content_cache"]["size"], 0)





if __name__ == "__main__":
    unittest.main(verbosity=2)
