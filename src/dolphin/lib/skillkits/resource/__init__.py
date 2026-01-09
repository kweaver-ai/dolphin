"""ResourceSkillkit - Claude Skill format support for Dolphin.

This package provides ResourceSkillkit, a Skillkit type that supports
resource/guidance skills in Claude Skill format (SKILL.md).

Example usage:
    ```python
    from dolphin.lib.skillkits.resource import (
        ResourceSkillkit,
        ResourceSkillConfig,
    )

    config = ResourceSkillConfig(
        directories=["./skills", "~/.dolphin/skills"]
    )
    skillkit = ResourceSkillkit(config)
    skillkit.initialize()

    # Get metadata prompt for system injection (Level 1)
    metadata_prompt = skillkit.get_metadata_prompt()

    # Load full skill content (Level 2)
    content = skillkit.load_skill("data-pipeline")
    ```
"""

from .resource_skillkit import ResourceSkillkit
from .models.skill_config import ResourceSkillConfig
from .models.skill_meta import SkillMeta, SkillContent
from .skill_loader import SkillLoader, SkillLoaderError
from .skill_validator import SkillValidator, ValidationResult
from .skill_cache import SkillMetaCache, SkillContentCache, TTLLRUCache

__all__ = [
    # Main class
    "ResourceSkillkit",
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
