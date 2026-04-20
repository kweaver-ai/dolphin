"""ResourceToolkit - Claude Skill format support for Dolphin.

This package provides ResourceToolkit, a Toolkit type that supports
resource/guidance skills in Claude Skill format (SKILL.md).

Example usage:
    ```python
    from dolphin.lib.toolkits.resource import (
        ResourceToolkit,
        ResourceSkillConfig,
    )

    config = ResourceSkillConfig(
        directories=["./skills", "~/.dolphin/skills"]
    )
    toolkit = ResourceToolkit(config)
    toolkit.initialize()

    # Get metadata prompt for system injection (Level 1)
    metadata_prompt = toolkit.get_metadata_prompt()

    # Load full skill content (Level 2)
    content = toolkit.load_skill("data-pipeline")
    ```
"""

from .resource_toolkit import ResourceToolkit
from .models.skill_config import ResourceSkillConfig, ResourceToolConfig
from .models.skill_meta import SkillMeta, SkillContent, ToolMeta, ToolContent
from .skill_loader import SkillLoader, SkillLoaderError, ToolLoader, ToolLoaderError
from .skill_validator import SkillValidator, ValidationResult, ToolValidator
from .skill_cache import SkillMetaCache, SkillContentCache, ToolMetaCache, ToolContentCache, TTLLRUCache

__all__ = [
    # Main class
    "ResourceToolkit",
    # Configuration (主用名)
    "ResourceSkillConfig",
    # Configuration (向后兼容别名，deprecated)
    "ResourceToolConfig",
    # Data models (主用名)
    "SkillMeta",
    "SkillContent",
    # Data models (向后兼容别名，deprecated)
    "ToolMeta",
    "ToolContent",
    # Loader (主用名)
    "SkillLoader",
    "SkillLoaderError",
    # Loader (向后兼容别名，deprecated)
    "ToolLoader",
    "ToolLoaderError",
    # Validator (主用名)
    "SkillValidator",
    "ValidationResult",
    # Validator (向后兼容别名，deprecated)
    "ToolValidator",
    # Cache (主用名)
    "SkillMetaCache",
    "SkillContentCache",
    # Cache (向后兼容别名，deprecated)
    "ToolMetaCache",
    "ToolContentCache",
    "TTLLRUCache",
]
