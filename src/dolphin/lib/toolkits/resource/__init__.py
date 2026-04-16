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
from .models.tool_config import ResourceSkillConfig
from .models.tool_meta import SkillMeta, SkillContent
from .tool_loader import SkillLoader, SkillLoaderError
from .tool_validator import SkillValidator, ValidationResult
from .tool_cache import SkillMetaCache, SkillContentCache, TTLLRUCache

__all__ = [
    # Main class
    "ResourceToolkit",
    # Configuration
    "ResourceSkillConfig",
    # Data models
    "SkillMeta",
    "SkillContent",
    # Loader
    "SkillLoader",
    "SkillLoaderError",
    # Validator
    "SkillValidator",
    "ValidationResult",
    # Cache
    "SkillMetaCache",
    "SkillContentCache",
    "TTLLRUCache",
]
