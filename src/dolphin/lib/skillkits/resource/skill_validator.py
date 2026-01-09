"""Validation utilities for ResourceSkillkit.

This module provides validation for skill packages, including:
- SKILL.md format validation
- Path security validation (prevent path traversal)
- Size limit validation
- File type validation
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple, Set, Union
from dataclasses import dataclass

from .models.skill_config import ResourceSkillConfig


@dataclass
class ValidationResult:
    """Result of a validation check.

    Attributes:
        is_valid: Whether validation passed
        errors: List of error messages
        warnings: List of warning messages
    """

    is_valid: bool
    errors: List[str]
    warnings: List[str]

    @classmethod
    def success(cls, warnings: Optional[List[str]] = None) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True, errors=[], warnings=warnings or [])

    @classmethod
    def failure(cls, errors: List[str], warnings: Optional[List[str]] = None) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(is_valid=False, errors=errors, warnings=warnings or [])

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge two validation results."""
        return ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


class SkillValidator:
    """Validator for skill packages and content.

    Performs various validation checks including:
    - Frontmatter validation (required fields, format)
    - Path security validation (no traversal attacks)
    - Size limit validation
    - File type whitelisting
    """

    # Required fields in SKILL.md frontmatter
    REQUIRED_FRONTMATTER_FIELDS = {"name", "description"}

    # Optional but recognized frontmatter fields
    OPTIONAL_FRONTMATTER_FIELDS = {"version", "tags", "author", "license"}

    # Pattern for valid skill names (alphanumeric, hyphens, underscores)
    SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

    def __init__(self, config: Optional[ResourceSkillConfig] = None):
        """Initialize the validator.

        Args:
            config: Optional configuration, uses defaults if not provided
        """
        self.config = config or ResourceSkillConfig()
        self._allowed_extensions: Set[str] = set(self.config.allowed_extensions)

    def validate_frontmatter(self, frontmatter: dict) -> ValidationResult:
        """Validate SKILL.md frontmatter.

        Args:
            frontmatter: Parsed YAML frontmatter dictionary

        Returns:
            ValidationResult with any errors/warnings
        """
        errors = []
        warnings = []

        # Check required fields
        for field in self.REQUIRED_FRONTMATTER_FIELDS:
            if field not in frontmatter:
                errors.append(f"Missing required field in frontmatter: '{field}'")
            elif not frontmatter[field]:
                errors.append(f"Empty required field in frontmatter: '{field}'")

        # Validate skill name format
        name = frontmatter.get("name", "")
        if name and not self.SKILL_NAME_PATTERN.match(name):
            errors.append(
                f"Invalid skill name '{name}': must start with letter and contain only "
                "alphanumeric characters, hyphens, and underscores"
            )

        # Check description length
        description = frontmatter.get("description", "")
        if description and len(description) > 500:
            warnings.append(
                f"Description is {len(description)} characters, "
                "consider keeping it under 500 for better system prompt efficiency"
            )

        # Validate tags if present
        tags = frontmatter.get("tags", [])
        if tags and not isinstance(tags, list):
            errors.append("'tags' field must be a list")

        # Validate version format if present
        version = frontmatter.get("version")
        if version and not self._is_valid_version(version):
            warnings.append(
                f"Version '{version}' doesn't follow semantic versioning (x.y.z)"
            )

        # Check for unknown fields
        known_fields = self.REQUIRED_FRONTMATTER_FIELDS | self.OPTIONAL_FRONTMATTER_FIELDS
        unknown_fields = set(frontmatter.keys()) - known_fields
        if unknown_fields:
            warnings.append(f"Unknown frontmatter fields: {unknown_fields}")

        if errors:
            return ValidationResult.failure(errors, warnings)
        return ValidationResult.success(warnings)

    def validate_path_security(
        self, requested_path: str, skill_base_path: Path
    ) -> ValidationResult:
        """Validate that a requested path is safe (no path traversal).

        Args:
            requested_path: The path requested (e.g., "scripts/etl.py")
            skill_base_path: The base path of the skill directory

        Returns:
            ValidationResult with any security errors
        """
        errors = []

        skill_base = skill_base_path.resolve()
        full_path, error = resolve_safe_path(requested_path, skill_base)
        if error:
            return ValidationResult.failure([error])

        # Check that resolved path is under skill base
        try:
            full_path.relative_to(skill_base)
        except ValueError:
            errors.append(
                f"Path traversal detected: '{requested_path}' "
                f"resolves outside skill directory"
            )
            return ValidationResult.failure(errors)

        return ValidationResult.success()

    def validate_file_type(self, file_path: Path) -> ValidationResult:
        """Validate that a file type is allowed.

        Args:
            file_path: Path to the file to check

        Returns:
            ValidationResult with any errors
        """
        suffix = file_path.suffix.lower()

        if suffix not in self._allowed_extensions:
            return ValidationResult.failure(
                [
                    f"File type '{suffix}' is not allowed. "
                    f"Allowed types: {sorted(self._allowed_extensions)}"
                ]
            )

        return ValidationResult.success()

    # Directories to exclude from size calculation
    SIZE_EXCLUDE_DIRS = {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".cache",
        "tmp",
        "temp",
        "profiles",
        "build",
        "dist",
        ".next",
    }

    def validate_size(self, path: Path) -> ValidationResult:
        """Validate that a file or directory doesn't exceed size limits.

        Args:
            path: Path to file or directory to check

        Returns:
            ValidationResult with any size errors
        """
        max_bytes = self.config.max_skill_size_mb * 1024 * 1024

        if path.is_file():
            size = path.stat().st_size
            if size > max_bytes:
                return ValidationResult.failure(
                    [
                        f"File '{path.name}' is {size / 1024 / 1024:.2f}MB, "
                        f"exceeds limit of {self.config.max_skill_size_mb}MB"
                    ]
                )
        elif path.is_dir():
            # Calculate size excluding common large directories
            total_size = 0
            for f in path.rglob("*"):
                if f.is_file():
                    # Check if any parent directory is in exclude list
                    parts = f.relative_to(path).parts
                    if any(part in self.SIZE_EXCLUDE_DIRS for part in parts):
                        continue
                    total_size += f.stat().st_size
            
            if total_size > max_bytes:
                return ValidationResult.failure(
                    [
                        f"Skill package is {total_size / 1024 / 1024:.2f}MB, "
                        f"exceeds limit of {self.config.max_skill_size_mb}MB"
                    ]
                )

        return ValidationResult.success()

    def validate_skill_directory(self, skill_dir: Path) -> ValidationResult:
        """Validate an entire skill directory structure.

        Args:
            skill_dir: Path to the skill directory

        Returns:
            ValidationResult with any errors/warnings
        """
        errors = []
        warnings = []

        # Check directory exists
        if not skill_dir.is_dir():
            return ValidationResult.failure(
                [f"Skill directory does not exist: {skill_dir}"]
            )

        # Check SKILL.md exists
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return ValidationResult.failure(
                [f"SKILL.md not found in {skill_dir}"]
            )

        # Validate size
        size_result = self.validate_size(skill_dir)
        if not size_result.is_valid:
            errors.extend(size_result.errors)
        warnings.extend(size_result.warnings)

        # Check for optional directories
        scripts_dir = skill_dir / "scripts"
        refs_dir = skill_dir / "references"

        if scripts_dir.exists() and not scripts_dir.is_dir():
            errors.append("'scripts' exists but is not a directory")

        if refs_dir.exists() and not refs_dir.is_dir():
            errors.append("'references' exists but is not a directory")

        # Check for AGENTS.md (Codex compatibility)
        agents_md = skill_dir / "AGENTS.md"
        if agents_md.is_file():
            warnings.append("AGENTS.md found - Codex compatibility mode available")

        if errors:
            return ValidationResult.failure(errors, warnings)
        return ValidationResult.success(warnings)

    def _is_valid_version(self, version: str) -> bool:
        """Check if version string follows semantic versioning.

        Args:
            version: Version string to check

        Returns:
            True if valid semver format
        """
        semver_pattern = re.compile(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
            r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
            r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
        )
        return bool(semver_pattern.match(version))


def validate_skill_name(name: str) -> Tuple[bool, Optional[str]]:
    """Validate a skill name.

    Args:
        name: The skill name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Skill name cannot be empty"

    if not SkillValidator.SKILL_NAME_PATTERN.match(name):
        return False, (
            f"Invalid skill name '{name}': must start with letter and contain only "
            "alphanumeric characters, hyphens, and underscores"
        )

    return True, None


def is_safe_path(requested_path: str, base_path: Path) -> bool:
    """Quick check if a path is safe (no traversal).

    Args:
        requested_path: The relative path requested
        base_path: The base directory path

    Returns:
        True if path is safe, False otherwise
    """
    resolved, error = resolve_safe_path(requested_path, base_path)
    return resolved is not None and error is None


def resolve_safe_path(
    requested_path: str, base_path: Union[Path, str]
) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a requested path under a base directory safely.

    This helper prevents path traversal and rejects any symlink in the path.

    Returns:
        (resolved_path, error_message)
    """
    try:
        base = Path(base_path).resolve()
    except (OSError, ValueError) as e:
        return None, f"Invalid base path: {e}"

    if not requested_path:
        return None, "Invalid path: empty"

    try:
        rel = Path(requested_path)
    except Exception as e:
        return None, f"Invalid path: {e}"

    if rel.is_absolute():
        return None, f"Invalid path: '{requested_path}' - absolute paths not allowed"

    candidate = base / rel

    # Reject any symlink in the path components (including the final file)
    current = base
    for part in rel.parts:
        if part in (".", ""):
            continue
        if part == "..":
            return None, f"Invalid path: '{requested_path}' - path traversal not allowed"
        current = current / part
        try:
            if current.exists() and current.is_symlink():
                return (
                    None,
                    f"Invalid path: '{requested_path}' - symlinks are not allowed",
                )
        except OSError as e:
            return None, f"Invalid path: {e}"

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None, f"Resource file not found: '{requested_path}'"
    except (OSError, ValueError) as e:
        return None, f"Invalid path: {e}"

    try:
        resolved.relative_to(base)
    except ValueError:
        return None, f"Invalid path: '{requested_path}' - path traversal not allowed"

    return resolved, None
