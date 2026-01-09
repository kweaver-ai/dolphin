"""SKILL.md loader for ResourceSkillkit.

This module provides the SkillLoader class for loading and parsing
SKILL.md files with support for the three-level progressive loading:
- Level 1: Metadata (name, description)
- Level 2: Full SKILL.md content
- Level 3: Resource files (scripts/, references/)
"""

import re
import os
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import yaml

from .models.skill_meta import SkillMeta, SkillContent
from .models.skill_config import ResourceSkillConfig
from .skill_validator import SkillValidator, ValidationResult, resolve_safe_path
from dolphin.core.logging.logger import get_logger

logger = get_logger("resource_skillkit")


class SkillLoaderError(Exception):
    """Exception raised for skill loading errors."""

    pass


class SkillLoader:
    """Loader for SKILL.md files supporting progressive loading.

    This loader handles:
    - Scanning directories for skill packages
    - Parsing YAML frontmatter and markdown body
    - Level 1/2/3 content loading
    - Validation and error handling
    """

    # Regex pattern for YAML frontmatter
    FRONTMATTER_PATTERN = re.compile(
        r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$",
        re.DOTALL
    )

    def __init__(self, config: Optional[ResourceSkillConfig] = None):
        """Initialize the loader.

        Args:
            config: Optional configuration, uses defaults if not provided
        """
        self.config = config or ResourceSkillConfig()
        self.validator = SkillValidator(self.config)

    def scan_directories(self, base_path: Optional[Path] = None) -> List[SkillMeta]:
        """Scan configured directories for skill packages.

        Scans all configured directories and returns Level 1 metadata
        for each valid skill found. Higher priority directories take
        precedence for duplicate skill names.

        Args:
            base_path: Optional base path for resolving relative directories

        Returns:
            List of SkillMeta objects for found skills
        """
        skills: Dict[str, SkillMeta] = {}  # name -> meta, for deduplication
        directories = self.config.get_resolved_directories(base_path)

        for directory in directories:
            if not directory.exists():
                logger.debug(f"Skill directory does not exist: {directory}")
                continue

            if not directory.is_dir():
                logger.warning(f"Skill path is not a directory: {directory}")
                continue

            max_depth = max(1, int(self.config.max_scan_depth))
            for item in self._iter_skill_dirs(directory, max_depth=max_depth):
                try:
                    meta = self.load_metadata(item)
                    if meta and meta.name not in skills:
                        # First occurrence wins (higher priority directory)
                        skills[meta.name] = meta
                        logger.debug(f"Found skill: {meta.name} at {item}")
                except Exception as e:
                    logger.warning(f"Failed to load skill from {item}: {e}")

        return list(skills.values())

    def _iter_skill_dirs(self, root: Path, max_depth: int) -> List[Path]:
        """Iterate directories that contain SKILL.md under root, up to max_depth."""
        found: List[Path] = []
        stack: List[Tuple[Path, int]] = [(root, 0)]

        while stack:
            current, depth = stack.pop()
            skill_md = current / "SKILL.md"
            if skill_md.is_file():
                found.append(current)
                continue

            if depth >= max_depth:
                continue

            try:
                subdirs = [
                    p
                    for p in current.iterdir()
                    if p.is_dir()
                    and not p.name.startswith(".")
                    and p.name not in {"__pycache__", "scripts", "references"}
                ]
            except PermissionError:
                continue

            for sub in sorted(subdirs, key=lambda p: p.name, reverse=True):
                stack.append((sub, depth + 1))

        return sorted(found, key=lambda p: str(p))

    def load_metadata(self, skill_dir: Path) -> Optional[SkillMeta]:
        """Load Level 1 metadata from a skill directory.

        Args:
            skill_dir: Path to the skill directory

        Returns:
            SkillMeta if successful, None if failed
        """
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.is_file():
            logger.warning(f"SKILL.md not found in {skill_dir}")
            return None

        # Security: reject symlinks to prevent path traversal
        if skill_md.is_symlink():
            logger.warning(f"SKILL.md is a symlink, skipping: {skill_md}")
            return None

        try:
            size_validation = self.validator.validate_size(skill_md)
            if not size_validation.is_valid:
                logger.warning(
                    f"SKILL.md too large in {skill_dir}: {size_validation.errors}"
                )
                return None

            content = skill_md.read_text(encoding="utf-8")
            frontmatter, _ = self._parse_frontmatter(content)

            if not frontmatter:
                logger.warning(f"No frontmatter found in {skill_md}")
                return None

            # Validate frontmatter
            validation = self.validator.validate_frontmatter(frontmatter)
            if not validation.is_valid:
                logger.warning(
                    f"Invalid frontmatter in {skill_md}: {validation.errors}"
                )
                return None

            for warning in validation.warnings:
                logger.debug(f"Frontmatter warning for {skill_md}: {warning}")

            return SkillMeta(
                name=frontmatter.get("name", ""),
                description=frontmatter.get("description", ""),
                base_path=str(skill_dir.resolve()),
                version=frontmatter.get("version"),
                tags=frontmatter.get("tags", []),
            )

        except Exception as e:
            logger.error(f"Error loading metadata from {skill_md}: {e}")
            return None

    def load_content(self, skill_dir: Path) -> Optional[SkillContent]:
        """Load Level 2 full content from a skill directory.

        Args:
            skill_dir: Path to the skill directory

        Returns:
            SkillContent if successful, None if failed
        """
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.is_file():
            logger.warning(f"SKILL.md not found in {skill_dir}")
            return None

        # Security: reject symlinks to prevent path traversal
        if skill_md.is_symlink():
            logger.warning(f"SKILL.md is a symlink, skipping: {skill_md}")
            return None

        try:
            size_validation = self.validator.validate_size(skill_dir)
            if not size_validation.is_valid:
                logger.warning(
                    f"Skill package too large in {skill_dir}: {size_validation.errors}"
                )
                return None

            content = skill_md.read_text(encoding="utf-8")
            frontmatter, body = self._parse_frontmatter(content)

            if frontmatter is None:
                # No frontmatter, treat entire content as body
                frontmatter = {}
                body = content

            # List available scripts and references
            scripts = self._list_directory_files(skill_dir / "scripts")
            references = self._list_directory_files(skill_dir / "references")

            return SkillContent(
                frontmatter=frontmatter,
                body=body.strip(),
                available_scripts=scripts,
                available_references=references,
            )

        except Exception as e:
            logger.error(f"Error loading content from {skill_md}: {e}")
            return None

    def load_resource(
        self, skill_dir: Path, resource_path: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Load Level 3 resource file content.

        Args:
            skill_dir: Path to the skill directory
            resource_path: Relative path to resource file (e.g., "scripts/etl.py")

        Returns:
            Tuple of (content, error_message). Content is None if error.
        """
        full_path, error = resolve_safe_path(resource_path, skill_dir)
        if error:
            return None, error
        if full_path is None:
            return None, f"Invalid path: '{resource_path}'"

        # Validate file type
        validation = self.validator.validate_file_type(full_path)
        if not validation.is_valid:
            return None, validation.errors[0]

        # Validate size
        size_validation = self.validator.validate_size(full_path)
        if not size_validation.is_valid:
            return None, size_validation.errors[0]

        try:
            flags = os.O_RDONLY
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if nofollow:
                flags |= nofollow
            fd = os.open(str(full_path), flags)
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                return f.read(), None
        except UnicodeDecodeError:
            return None, f"Cannot read '{resource_path}': not a text file"
        except OSError as e:
            return None, f"Error reading '{resource_path}': {e}"
        except Exception as e:
            return None, f"Error reading '{resource_path}': {e}"

    def _parse_frontmatter(self, content: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Parse YAML frontmatter from SKILL.md content.

        Args:
            content: The full SKILL.md file content

        Returns:
            Tuple of (frontmatter_dict, body_content)
            frontmatter_dict is None if no valid frontmatter found
        """
        match = self.FRONTMATTER_PATTERN.match(content)

        if not match:
            return None, content

        yaml_content = match.group(1)
        body = match.group(2)

        try:
            frontmatter = yaml.safe_load(yaml_content)
            if not isinstance(frontmatter, dict):
                logger.warning("Frontmatter is not a valid YAML dictionary")
                return None, content
            return frontmatter, body
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            return None, content

    def _list_directory_files(
        self, directory: Path, max_depth: int = 2
    ) -> List[str]:
        """List files in a directory recursively.

        Args:
            directory: Directory to list
            max_depth: Maximum recursion depth

        Returns:
            List of relative file paths
        """
        if not directory.is_dir():
            return []

        files = []
        base_name = directory.name

        def _scan(current_dir: Path, depth: int, prefix: str):
            if depth > max_depth:
                return

            try:
                for item in sorted(current_dir.iterdir()):
                    rel_path = f"{prefix}/{item.name}" if prefix else item.name

                    if item.is_file():
                        # Validate file type
                        if self.validator.validate_file_type(item).is_valid:
                            files.append(f"{base_name}/{rel_path}")
                    elif item.is_dir() and not item.name.startswith("."):
                        _scan(item, depth + 1, rel_path)
            except PermissionError:
                logger.debug(f"Permission denied accessing {current_dir}")

        _scan(directory, 1, "")
        return files

    def find_skill_by_name(
        self, name: str, base_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Find a skill directory by name.

        Args:
            name: The skill name to find
            base_path: Optional base path for resolving directories

        Returns:
            Path to skill directory if found, None otherwise
        """
        directories = self.config.get_resolved_directories(base_path)

        for directory in directories:
            if not directory.is_dir():
                continue

            skill_dir = directory / name
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                return skill_dir

        return None


def truncate_content(content: str, max_tokens: int, chars_per_token: int = 4) -> str:
    """Truncate content to approximately max_tokens.

    Args:
        content: The content to truncate
        max_tokens: Maximum number of tokens
        chars_per_token: Estimated characters per token

    Returns:
        Truncated content with notice if truncated
    """
    max_chars = max_tokens * chars_per_token

    if len(content) <= max_chars:
        return content

    # Find a good break point (end of line near limit)
    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n")

    if last_newline > max_chars * 0.8:  # If newline is in last 20%
        truncated = truncated[:last_newline]

    return (
        truncated
        + "\n\n---\n"
        + "*[Content truncated. Use `_load_skill_resource()` to load specific files.]*"
    )
