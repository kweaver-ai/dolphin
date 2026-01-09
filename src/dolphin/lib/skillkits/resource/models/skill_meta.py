"""Data models for ResourceSkillkit.

This module contains the SkillMeta and SkillContent dataclasses for
representing skill metadata (Level 1) and full content (Level 2).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class SkillMeta:
    """Level 1 metadata - lightweight skill information.

    This represents the minimal metadata loaded for each skill,
    used for system prompt injection (~100 tokens per skill).

    Attributes:
        name: Unique skill identifier
        description: Brief description of what the skill does
        base_path: Absolute path to the skill directory
        version: Optional semantic version string
        tags: Optional list of categorization tags
    """

    name: str
    description: str
    base_path: str
    version: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_prompt_entry(self) -> str:
        """Generate a markdown entry for system prompt injection.

        Returns:
            Formatted markdown string for this skill's metadata
        """
        return f"### {self.name}\n{self.description}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all metadata fields
        """
        return {
            "name": self.name,
            "description": self.description,
            "base_path": self.base_path,
            "version": self.version,
            "tags": self.tags,
        }


@dataclass
class SkillContent:
    """Level 2 full content - complete SKILL.md content.

    This represents the fully loaded skill content including
    the YAML frontmatter and markdown body (~1500 tokens).

    Attributes:
        frontmatter: Parsed YAML frontmatter as dictionary
        body: The markdown content after frontmatter
        available_scripts: List of script file paths in scripts/ directory
        available_references: List of reference file paths in references/ directory
    """

    frontmatter: Dict[str, Any]
    body: str
    available_scripts: List[str] = field(default_factory=list)
    available_references: List[str] = field(default_factory=list)

    def get_name(self) -> str:
        """Get skill name from frontmatter.

        Returns:
            The skill name, or empty string if not found
        """
        return self.frontmatter.get("name", "")

    def get_description(self) -> str:
        """Get skill description from frontmatter.

        Returns:
            The skill description, or empty string if not found
        """
        return self.frontmatter.get("description", "")

    def get_full_content(self) -> str:
        """Get the complete content for Level 2 loading.

        This includes the markdown body plus a list of available
        resources that can be loaded via Level 3.

        Returns:
            Complete formatted content string
        """
        content_parts = [self.body]

        if self.available_scripts or self.available_references:
            content_parts.append("\n\n## Available Resources\n")

            if self.available_scripts:
                content_parts.append("\n**Scripts:**")
                for script in self.available_scripts:
                    content_parts.append(f"\n- `{script}`")

            if self.available_references:
                content_parts.append("\n\n**References:**")
                for ref in self.available_references:
                    content_parts.append(f"\n- `{ref}`")

        return "".join(content_parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all content fields
        """
        return {
            "frontmatter": self.frontmatter,
            "body": self.body,
            "available_scripts": self.available_scripts,
            "available_references": self.available_references,
        }
