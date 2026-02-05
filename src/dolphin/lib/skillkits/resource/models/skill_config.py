"""Configuration models for ResourceSkillkit.

This module contains configuration dataclasses for ResourceSkillkit settings.
"""

from dataclasses import dataclass, field
import os
from typing import List, Optional
from pathlib import Path


# Default values as module constants to avoid duplication
_DEFAULT_DIRECTORIES = ["./skills"]
_DEFAULT_MAX_SKILL_SIZE_MB = 8
_DEFAULT_MAX_CONTENT_TOKENS = 8000
_DEFAULT_CACHE_TTL_SECONDS = 300
_DEFAULT_MAX_CACHE_SIZE = 100
_DEFAULT_MAX_SCAN_DEPTH = 6
_DEFAULT_ALLOWED_EXTENSIONS = [
    ".py", ".sh", ".js", ".ts", ".md", ".txt", ".json", ".yaml", ".yml"
]


@dataclass
class ResourceSkillConfig:
    """Configuration for ResourceSkillkit.

    Attributes:
        enabled: Whether ResourceSkillkit is enabled
        directories: List of directories to scan for skills (in priority order)
        max_skill_size_mb: Maximum size of a single skill package in MB
        max_content_tokens: Maximum tokens to return in a single load
        cache_ttl_seconds: TTL for metadata cache in seconds
        max_cache_size: Maximum number of items in cache
        max_scan_depth: Maximum directory depth when scanning for skills
        allowed_extensions: File extensions allowed for resource files
    """

    enabled: bool = True
    directories: List[str] = field(default_factory=lambda: list(_DEFAULT_DIRECTORIES))
    max_skill_size_mb: int = _DEFAULT_MAX_SKILL_SIZE_MB
    max_content_tokens: int = _DEFAULT_MAX_CONTENT_TOKENS
    cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS
    max_cache_size: int = _DEFAULT_MAX_CACHE_SIZE
    max_scan_depth: int = _DEFAULT_MAX_SCAN_DEPTH
    allowed_extensions: List[str] = field(
        default_factory=lambda: list(_DEFAULT_ALLOWED_EXTENSIONS)
    )

    @classmethod
    def from_dict(cls, config_dict: dict) -> "ResourceSkillConfig":
        """Create config from dictionary (e.g., from YAML config).

        Args:
            config_dict: Dictionary with configuration values

        Returns:
            ResourceSkillConfig instance
        """
        resource_config = config_dict.get("resource_skills", {})

        limits = resource_config.get("limits", {})

        return cls(
            enabled=resource_config.get("enabled", True),
            directories=resource_config.get("directories", _DEFAULT_DIRECTORIES),
            max_skill_size_mb=limits.get("max_skill_size_mb", _DEFAULT_MAX_SKILL_SIZE_MB),
            max_content_tokens=limits.get("max_content_tokens", _DEFAULT_MAX_CONTENT_TOKENS),
            cache_ttl_seconds=resource_config.get("cache_ttl_seconds", _DEFAULT_CACHE_TTL_SECONDS),
            max_cache_size=resource_config.get("max_cache_size", _DEFAULT_MAX_CACHE_SIZE),
            max_scan_depth=resource_config.get("max_scan_depth", _DEFAULT_MAX_SCAN_DEPTH),
            allowed_extensions=resource_config.get("allowed_extensions", _DEFAULT_ALLOWED_EXTENSIONS),
        )

    def get_resolved_directories(self, base_path: Optional[Path] = None) -> List[Path]:
        """Resolve directory paths, expanding ~ and making absolute.

        Args:
            base_path: Optional base path for resolving relative paths

        Returns:
            List of resolved absolute Path objects
        """
        resolved = []
        for dir_str in self.directories:
            raw = "" if dir_str is None else str(dir_str)
            raw = raw.strip()
            while len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"', "`"}:
                raw = raw[1:-1].strip()
            raw = os.path.expandvars(os.path.expanduser(raw))
            path = Path(raw).expanduser()
            if not path.is_absolute():
                if base_path:
                    path = base_path / path
                else:
                    path = Path.cwd() / path
            resolved.append(path.resolve())
        return resolved

    def to_dict(self) -> dict:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all configuration fields
        """
        return {
            "enabled": self.enabled,
            "directories": self.directories,
            "max_skill_size_mb": self.max_skill_size_mb,
            "max_content_tokens": self.max_content_tokens,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "max_cache_size": self.max_cache_size,
            "max_scan_depth": self.max_scan_depth,
            "allowed_extensions": self.allowed_extensions,
        }
