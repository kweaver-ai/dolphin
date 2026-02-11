"""ResourceSkillkit - Claude Skill format support for Dolphin.

This module implements ResourceSkillkit, a Skillkit type that supports
resource/guidance skills in Claude Skill format (SKILL.md).

Key features:
- Progressive loading (Level 1/2/3)
- Prefix Cache optimization
- History bucket persistence
- Local-first design
"""

from pathlib import Path
from typing import List, Optional, Dict, Any

from dolphin.core.common.constants import PIN_MARKER
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.logging.logger import get_logger

from .models.skill_meta import SkillMeta, SkillContent
from .models.skill_config import ResourceSkillConfig
from .skill_loader import SkillLoader, truncate_content
from .skill_cache import SkillMetaCache, SkillContentCache
from .skill_validator import validate_skill_name

logger = get_logger("resource_skillkit")


class ResourceSkillkit(Skillkit):
    """ResourceSkillkit - Support for Claude Skill format resources.

    This Skillkit type provides support for resource/guidance skills
    that teach LLMs how to solve complex problems. Unlike execution
    skillkits (SQL, Python, MCP), ResourceSkillkit loads knowledge
    resources in Claude Skill format (SKILL.md).

    Progressive Loading:
    - Level 1: Metadata (~100 tokens) - auto-injected to system prompt
    - Level 2: Full SKILL.md content (~1500 tokens) - via tool call
    - Level 3: Resource files (scripts/references) - on-demand

    Prefix Cache Optimization:
    - Level 1 metadata is fixed in system prompt
    - Level 2 content enters _history bucket via tool response
    - System prompt remains stable for cache hits

    Example usage:
        ```python
        config = ResourceSkillConfig(
            directories=["./skills", "~/.dolphin/skills"]
        )
        skillkit = ResourceSkillkit(config)
        skillkit.initialize()

        # Get metadata prompt for system injection
        metadata_prompt = skillkit.getMetadataPrompt()

        # Load full skill content (returns tool response)
        content = skillkit.load_skill("data-pipeline")
        ```
    """

    def __init__(self, config: Optional[ResourceSkillConfig] = None):
        """Initialize ResourceSkillkit.

        Args:
            config: Optional configuration, uses defaults if not provided
        """
        super().__init__()
        self.config = config or ResourceSkillConfig()
        self.loader = SkillLoader(self.config)
        self._meta_cache = SkillMetaCache(
            ttl_seconds=self.config.cache_ttl_seconds,
            max_size=self.config.max_cache_size,
        )
        self._content_cache = SkillContentCache(
            ttl_seconds=self.config.cache_ttl_seconds * 2,
            max_size=max(1, self.config.max_cache_size // 2),
        )
        self._initialized = False
        self._skills_meta: Dict[str, SkillMeta] = {}
        self._base_path: Optional[Path] = None

    def setGlobalConfig(self, globalConfig) -> None:
        super().setGlobalConfig(globalConfig)
        resource_skills_cfg = getattr(globalConfig, "resource_skills", None)
        if not isinstance(resource_skills_cfg, dict):
            return

        try:
            new_config = ResourceSkillConfig.from_dict(
                {"resource_skills": resource_skills_cfg}
            )
        except Exception as e:
            logger.warning(f"Failed to parse resource_skills config: {e}")
            return

        self.config = new_config
        self.loader = SkillLoader(self.config)
        self._meta_cache = SkillMetaCache(
            ttl_seconds=self.config.cache_ttl_seconds,
            max_size=self.config.max_cache_size,
        )
        self._content_cache = SkillContentCache(
            ttl_seconds=self.config.cache_ttl_seconds * 2,
            max_size=max(1, self.config.max_cache_size // 2),
        )
        # Clear old state to avoid stale data
        self._skills_meta.clear()
        self._initialized = False

        # Get base_dir from GlobalConfig to resolve relative paths
        base_dir = getattr(globalConfig, "base_dir", None)
        if base_dir:
            from pathlib import Path
            self._base_path = Path(base_dir)

    def _ensure_initialized(self) -> None:
        """Ensure the skillkit has scanned and loaded Level 1 metadata."""
        if self._initialized:
            return
        self.initialize(self._base_path)

    def getName(self) -> str:
        """Get the name of this skillkit.

        Returns:
            The skillkit name
        """
        return "resource_skillkit"

    def initialize(self, base_path: Optional[Path] = None) -> None:
        """Initialize the skillkit by scanning for available skills.

        This scans all configured directories and loads Level 1 metadata
        for each valid skill found.

        Args:
            base_path: Optional base path for resolving relative directories
        """
        self._base_path = base_path
        self._skills_meta.clear()
        self._meta_cache.clear()

        if not self.config.enabled:
            logger.info("ResourceSkillkit is disabled")
            self._initialized = True
            return

        # Scan directories and load metadata
        metas = self.loader.scan_directories(base_path)

        for meta in metas:
            self._skills_meta[meta.name] = meta
            self._meta_cache.set(meta.name, meta)

        logger.info(f"Initialized ResourceSkillkit with {len(self._skills_meta)} skills")
        self._initialized = True

    def _createSkills(self) -> List[SkillFunction]:
        """Create the list of skill functions provided by this skillkit.

        Note: _list_resource_skills is NOT exposed as a tool because
        Level 1 metadata is auto-injected into system prompt via
        get_metadata_prompt(). LLM sees available skills upfront.

        Returns:
            List of SkillFunction objects for Level 2/3 loading
        """
        return [
            SkillFunction(self._load_resource_skill),
            SkillFunction(self._load_skill_resource),
        ]

    def get_metadata_prompt(self) -> str:
        """Generate fixed metadata prompt for system injection (Level 1).

        This generates the Level 1 metadata content that is automatically
        injected into the system prompt. The content is stable and
        sorted alphabetically to ensure Prefix Cache compatibility.

        This overrides the base Skillkit.get_metadata_prompt() method.

        Returns:
            Markdown-formatted metadata prompt with available resource skills.
            Always includes the section header, even when no skills are available.
        """
        self._ensure_initialized()

        parts = ["## Available Resource Skills\n"]

        if not self._skills_meta:
            # Always include the section header to prevent hallucination
            # when user's system prompt references this section
            parts.append("\n_No resource skills are currently available._\n")
            return "".join(parts)

        # Sort by name for stable ordering (Prefix Cache)
        for name in sorted(self._skills_meta.keys()):
            meta = self._skills_meta[name]
            parts.append(f"\n{meta.to_prompt_entry()}\n")

        return "".join(parts)

    def load_skill(self, name: str) -> str:
        """Load Level 2 full content for a skill.

        This is the internal method called by _load_resource_skill.
        The returned content enters _history bucket as tool response.

        Args:
            name: The skill name to load

        Returns:
            Full SKILL.md content or error message
        """
        self._ensure_initialized()

        # Validate name
        is_valid, error = validate_skill_name(name)
        if not is_valid:
            return f"Error: {error}"

        # Check if skill exists
        if name not in self._skills_meta:
            available = sorted(self._skills_meta.keys())
            return (
                f"Error: Skill '{name}' not found.\n"
                f"Available skills: {', '.join(available) if available else 'none'}"
            )

        # Check content cache
        cached_content = self._content_cache.get(name)
        meta = self._skills_meta[name]
        skill_dir = Path(meta.base_path)
        
        # Build path info header to help Agent know where to execute commands
        path_info = f"**Skill Root Directory:** `{skill_dir}`\n\n---\n\n"
        
        if cached_content:
            full_content = path_info + cached_content.get_full_content()
            return truncate_content(full_content, self.config.max_content_tokens)

        # Load from disk
        content = self.loader.load_content(skill_dir)
        if content is None:
            return f"Error: Failed to load content for skill '{name}'"

        # Cache the content
        self._content_cache.set(name, content)

        # Truncate if necessary - include path info at the beginning
        full_content = path_info + content.get_full_content()
        return truncate_content(full_content, self.config.max_content_tokens)

    def load_skill_short(self, name: str) -> str:
        """Load a compact summary for a skill.

        This is intended as the default lightweight view for multi-turn sessions.

        Args:
            name: The skill name to load

        Returns:
            Short summary text or error message
        """
        self._ensure_initialized()

        is_valid, error = validate_skill_name(name)
        if not is_valid:
            return f"Error: {error}"

        meta = self._skills_meta.get(name)
        if meta is None:
            available = sorted(self._skills_meta.keys())
            return (
                f"Error: Skill '{name}' not found.\n"
                f"Available skills: {', '.join(available) if available else 'none'}"
            )

        return (
            f"{meta.to_prompt_entry()}\n\n"
            f"To load full instructions, call: "
            f"_load_resource_skill(skill_name=\"{name}\", mode=\"full\")"
        )

    def load_resource(self, skill_name: str, resource_path: str) -> str:
        """Load Level 3 resource file content.

        This is the internal method called by _load_skill_resource.
        The returned content is temporary (scratchpad).

        Args:
            skill_name: The skill name
            resource_path: Relative path to resource file

        Returns:
            Resource file content or error message
        """
        self._ensure_initialized()

        # Validate skill name
        is_valid, error = validate_skill_name(skill_name)
        if not is_valid:
            return f"Error: {error}"

        # Check if skill exists
        if skill_name not in self._skills_meta:
            available = sorted(self._skills_meta.keys())
            return (
                f"Error: Skill '{skill_name}' not found.\n"
                f"Available skills: {', '.join(available) if available else 'none'}"
            )

        # Load resource
        meta = self._skills_meta[skill_name]
        skill_dir = Path(meta.base_path)

        content, error = self.loader.load_resource(skill_dir, resource_path)
        if error:
            return f"Error: {error}"

        # Format with file info header
        return f"# {resource_path}\n\n```\n{content}\n```"

    def clear_caches(self) -> None:
        """Clear all internal caches.

        This forces a reload from disk on next access.
        """
        self._meta_cache.clear()
        self._content_cache.clear()

    def get_available_skills(self) -> List[str]:
        """Get list of available skill names.

        Returns:
            Sorted list of skill names
        """
        self._ensure_initialized()
        return sorted(self._skills_meta.keys())

    def get_skill_meta(self, name: str) -> Optional[SkillMeta]:
        """Get metadata for a specific skill.

        Args:
            name: The skill name

        Returns:
            SkillMeta if found, None otherwise
        """
        return self._skills_meta.get(name)

    # =====================================
    # Tool Functions (exposed to LLM)
    # =====================================

    def _load_resource_skill(self, skill_name: str, mode: str = "short", **kwargs) -> str:
        """Load a resource skill in short or full mode.

        Default behavior is short mode for lower context overhead.
        Use mode="full" to load complete SKILL.md instructions.

        Args:
            skill_name (str): Name of the skill to load
            mode (str): "short" (default) or "full"

        Returns:
            str: Short summary or full skill content
        """
        normalized_mode = (mode or "short").strip().lower()
        if normalized_mode != "full":
            return self.load_skill_short(skill_name)

        content = self.load_skill(skill_name)
        if content.startswith(PIN_MARKER):
            return content
        return f"{PIN_MARKER}\n{content}"

    def _load_skill_resource(self, skill_name: str, resource_path: str, **kwargs) -> str:
        """Load a specific resource file from a skill package.

        Loads content from scripts/ or references/ directories within
        a skill package. The resource path should be relative to the
        skill directory (e.g., "scripts/etl.py").

        Note: Level 3 resources are designed to be ephemeral (single-turn only).
        Unlike Level 2 SKILL.md content, these resources do NOT use PIN_MARKER
        and will not be persisted to history. They can be reloaded on-demand.

        Args:
            skill_name (str): Name of the skill
            resource_path (str): Relative path to the resource file

        Returns:
            str: Resource file content
        """
        # Level 3: No PIN_MARKER - content goes to scratchpad, discarded after turn
        return self.load_resource(skill_name, resource_path)

    # =====================================
    # Utility Methods
    # =====================================

    def refresh(self) -> int:
        """Refresh the skill list by rescanning directories.

        Returns:
            Number of skills found
        """
        self.initialize(self._base_path)
        return len(self._skills_meta)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the skillkit.

        Returns:
            Dictionary with statistics
        """
        return {
            "enabled": self.config.enabled,
            "initialized": self._initialized,
            "skill_count": len(self._skills_meta),
            "meta_cache": self._meta_cache.stats(),
            "content_cache": self._content_cache.stats(),
            "directories": self.config.directories,
        }
