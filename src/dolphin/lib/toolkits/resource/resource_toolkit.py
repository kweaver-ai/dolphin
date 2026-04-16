"""ResourceToolkit - Claude Skill format support for Dolphin.

This module implements ResourceToolkit, a Toolkit type that supports
resource/guidance skills in Claude Skill format (SKILL.md).

Key features:
- Progressive loading (Level 1/2/3)
- Prefix Cache optimization
- History bucket persistence
- Local-first design
- Unified builtin skill contracts for local testing mode:
  builtin_skill_load / builtin_skill_read_file / builtin_skill_execute_script
"""

from pathlib import Path
from typing import List, Optional, Dict, Any

from dolphin.core.common.constants import PIN_MARKER
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.toolkit import Toolkit
from dolphin.core.logging.logger import get_logger

from .models.tool_meta import SkillMeta, SkillContent
from .models.tool_config import ResourceSkillConfig
from .tool_loader import SkillLoader, truncate_content
from .tool_cache import SkillMetaCache, SkillContentCache
from .tool_validator import (
    validate_skill_name,
    validate_skill_file_path,
)
from .local_script_executor import execute_skill_script
from dolphin.sdk.skill.skill_contracts import (
    BUILTIN_SKILL_LOAD,
    BUILTIN_SKILL_READ_FILE,
    BUILTIN_SKILL_EXECUTE_SCRIPT,
    SKILL_LOAD_DESCRIPTION,
    SKILL_READ_FILE_DESCRIPTION,
    SKILL_EXECUTE_SCRIPT_DESCRIPTION,
    SKILL_LOAD_INPUTS_SCHEMA,
    SKILL_READ_FILE_INPUTS_SCHEMA,
    SKILL_EXECUTE_SCRIPT_INPUTS_SCHEMA,
    SKILL_LOAD_OPENAI_SCHEMA,
    SKILL_READ_FILE_OPENAI_SCHEMA,
    SKILL_EXECUTE_SCRIPT_OPENAI_SCHEMA,
)

logger = get_logger("resource_toolkit")


class ResourceToolkit(Toolkit):
    """ResourceToolkit - Support for Claude Skill format resources.

    This Toolkit type provides support for resource/guidance skills
    that teach LLMs how to solve complex problems. Unlike execution
    toolkits (SQL, Python, MCP), ResourceToolkit loads knowledge
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
        toolkit = ResourceToolkit(config)
        toolkit.initialize()

        # Get metadata prompt for system injection
        metadata_prompt = toolkit.getMetadataPrompt()

        # Load full skill content (returns tool response)
        content = toolkit.load_skill("data-pipeline")
        ```
    """

    def __init__(self, config: Optional[ResourceSkillConfig] = None):
        """Initialize ResourceToolkit.

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
        """Ensure the toolkit has scanned and loaded Level 1 metadata."""
        if self._initialized:
            return
        self.initialize(self._base_path)

    def getName(self) -> str:
        """Get the name of this toolkit.

        Returns:
            The toolkit name
        """
        return "resource_toolkit"

    def initialize(self, base_path: Optional[Path] = None) -> None:
        """Initialize the toolkit by scanning for available skills.

        This scans all configured directories and loads Level 1 metadata
        for each valid skill found.

        Args:
            base_path: Optional base path for resolving relative directories
        """
        self._base_path = base_path
        self._skills_meta.clear()
        self._meta_cache.clear()

        if not self.config.enabled:
            logger.info("ResourceToolkit is disabled")
            self._initialized = True
            return

        # Scan directories and load metadata
        metas = self.loader.scan_directories(base_path)

        for meta in metas:
            self._skills_meta[meta.name] = meta
            self._meta_cache.set(meta.name, meta)

        # Apply include/exclude filter
        if self.config.include is not None:
            include_set = set(self.config.include)
            to_remove = [k for k in self._skills_meta if k not in include_set]
            for k in to_remove:
                del self._skills_meta[k]
                self._meta_cache.delete(k)
            logger.info(f"Applied include filter: {len(self._skills_meta)} skills remaining")
        elif self.config.exclude is not None:
            exclude_set = set(self.config.exclude)
            to_remove = [k for k in self._skills_meta if k in exclude_set]
            for k in to_remove:
                del self._skills_meta[k]
                self._meta_cache.delete(k)
            logger.info(f"Applied exclude filter: {len(self._skills_meta)} skills remaining")

        logger.info(f"Initialized ResourceToolkit with {len(self._skills_meta)} skills")
        self._initialized = True

    def _createTools(self) -> List[ToolFunction]:
        """Create the list of tool functions provided by this toolkit.

        Note: _list_resource_skills is NOT exposed as a tool because
        Level 1 metadata is auto-injected into system prompt via
        get_metadata_prompt(). LLM sees available skills upfront.

        Legacy entries (_load_resource_skill / _read_skill_asset) are kept for
        backwards compatibility.  The three unified contract handlers are added
        for local testing mode:
        - builtin_skill_load
        - builtin_skill_read_file
        - builtin_skill_execute_script

        Returns:
            List of ToolFunction objects for Level 2/3 loading
        """
        return [
            # Legacy interface (kept for backwards compatibility)
            ToolFunction(self._load_resource_skill),
            ToolFunction(self._read_skill_asset),
            # Unified contract interface (local testing mode)
            ToolFunction(
                self._builtin_skill_load_handler,
                openai_tool_schema=SKILL_LOAD_OPENAI_SCHEMA,
            ),
            ToolFunction(
                self._builtin_skill_read_file_handler,
                openai_tool_schema=SKILL_READ_FILE_OPENAI_SCHEMA,
            ),
            ToolFunction(
                self._builtin_skill_execute_script_handler,
                openai_tool_schema=SKILL_EXECUTE_SCRIPT_OPENAI_SCHEMA,
            ),
        ]

    def get_metadata_prompt(self) -> str:
        """Generate fixed metadata prompt for system injection (Level 1).

        This generates the Level 1 metadata content that is automatically
        injected into the system prompt. The content is stable and
        sorted alphabetically to ensure Prefix Cache compatibility.

        This overrides the base Toolkit.get_metadata_prompt() method.

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
            full_content = self._substitute_variables(full_content, extra_vars={"SKILL_DIR": str(skill_dir)})
            return truncate_content(full_content, self.config.max_content_tokens)

        # Load from disk
        content = self.loader.load_content(skill_dir)
        if content is None:
            return f"Error: Failed to load content for skill '{name}'"

        # Cache the content
        self._content_cache.set(name, content)

        # Truncate if necessary - include path info at the beginning
        full_content = path_info + content.get_full_content()
        full_content = self._substitute_variables(full_content, extra_vars={"SKILL_DIR": str(skill_dir)})
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

    def load_resource(self, skill_name: str, asset_path: str) -> str:
        """Load Level 3 asset file content.

        This is the internal method called by _read_skill_asset.
        The returned content is temporary (scratchpad).

        Args:
            skill_name: The skill name
            asset_path: Relative path to asset file

        Returns:
            Asset file content or error message
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

        content, error = self.loader.load_resource(skill_dir, asset_path)
        if error:
            return f"Error: {error}"

        # Format with file info header
        return f"# {asset_path}\n\n```\n{content}\n```"

    def _substitute_variables(self, content: str, extra_vars: dict = None) -> str:
        """Replace $VAR_NAME placeholders with values from config.variables and extra_vars."""
        variables = dict(self.config.variables) if self.config.variables else {}
        if extra_vars:
            variables.update(extra_vars)
        if not variables:
            return content
        for key, value in variables.items():
            content = content.replace(f"${key}", str(value))
        return content

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

        Legacy interface kept for backwards compatibility.  Delegates to the
        same underlying SkillLoader.load_content() path used by
        _builtin_skill_load_handler — no independent logic.

        Default is short mode to reduce context overhead — when many skills
        are registered, preloading full content for each would consume
        significant context budget.  The LLM can request mode="full" for
        skills it actually needs.

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

    def _read_skill_asset(
        self,
        skill_name: str,
        asset_path: str,
        **kwargs,
    ) -> str:
        """Read a specific asset file from a skill package.

        Legacy interface kept for backwards compatibility.  Delegates to the
        same underlying SkillLoader.load_resource() path used by
        _builtin_skill_read_file_handler — no independent logic.

        Loads content from scripts/ or references/ directories within
        a skill package. The asset path should be relative to the
        skill directory (e.g., "scripts/etl.py").

        Note: Level 3 resources are designed to be ephemeral (single-turn only).
        Unlike Level 2 SKILL.md content, these resources do NOT use PIN_MARKER
        and will not be persisted to history. They can be reloaded on-demand.

        Args:
            skill_name (str): Name of the skill
            asset_path (str): Relative path to the asset file

        Returns:
            str: Asset file content
        """
        # Level 3: No PIN_MARKER - content goes to scratchpad, discarded after turn
        return self.load_resource(skill_name, asset_path)

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
        """Get statistics about the toolkit.

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

    # =====================================================================
    # Unified contract handlers (local testing mode)
    # Names must match the constants in skill_contracts.py exactly.
    # =====================================================================

    def _builtin_skill_load_handler(self, skill_id: str, **kwargs) -> Dict[str, Any]:
        """Handler for builtin_skill_load contract (local testing mode).

        Loads the full SKILL.md content plus available script / reference path
        lists for a skill identified by its frontmatter name.

        Args:
            skill_id: Skill name matching SKILL.md frontmatter 'name' field

        Returns:
            Unified response dict with skill_md_content, available_scripts,
            available_references, and source='local'
        """
        self._ensure_initialized()

        is_valid, error = validate_skill_name(skill_id)
        if not is_valid:
            return self._contract_error(skill_id, f"Invalid skill_id: {error}")

        if skill_id not in self._skills_meta:
            available = sorted(self._skills_meta.keys())
            return self._contract_error(
                skill_id,
                f"Skill '{skill_id}' not found. Available: {available or 'none'}",
            )

        meta = self._skills_meta[skill_id]
        skill_dir = Path(meta.base_path)

        content = self.loader.load_content(skill_dir)
        if content is None:
            return self._contract_error(
                skill_id, f"Failed to load content for skill '{skill_id}'"
            )

        result = {
            "skill_id": skill_id,
            # Return the authoritative full SKILL.md text (frontmatter + body)
            # so the LLM sees exactly what is on disk, including metadata fields.
            "skill_md_content": content.raw_skill_md,
            "available_scripts": content.available_scripts,
            "available_references": content.available_references,
            "source": "local",
        }
        return {"answer": result, "block_answer": result}

    def _builtin_skill_read_file_handler(
        self, skill_id: str, file_path: str, **kwargs
    ) -> Dict[str, Any]:
        """Handler for builtin_skill_read_file contract (local testing mode).

        Reads the full text content of a single file inside the skill package.

        Args:
            skill_id: Skill name matching SKILL.md frontmatter 'name' field
            file_path: Relative file path inside the skill directory

        Returns:
            Unified response dict with file content and source='local'
        """
        self._ensure_initialized()

        is_valid, error = validate_skill_name(skill_id)
        if not is_valid:
            return self._contract_error(skill_id, f"Invalid skill_id: {error}")

        path_valid, path_error = validate_skill_file_path(file_path)
        if not path_valid:
            return self._contract_error(skill_id, path_error)

        if skill_id not in self._skills_meta:
            return self._contract_error(skill_id, f"Skill '{skill_id}' not found")

        meta = self._skills_meta[skill_id]
        skill_dir = Path(meta.base_path)

        content_text, read_error = self.loader.load_resource(skill_dir, file_path)
        if read_error:
            return self._contract_error(skill_id, read_error)

        result = {
            "skill_id": skill_id,
            "file_path": file_path,
            "content": content_text,
            "source": "local",
        }
        return {"answer": result, "block_answer": result}

    def _builtin_skill_execute_script_handler(
        self, skill_id: str, entry_shell: str, **kwargs
    ) -> Dict[str, Any]:
        """Handler for builtin_skill_execute_script contract (local testing mode).

        Executes a script inside the skill's scripts/ directory using the local
        runtime environment. Matches the online factory execution behavior.

        Args:
            skill_id: Skill name matching SKILL.md frontmatter 'name' field
            entry_shell: Shell command to execute (e.g., 'python scripts/analyze.py')

        Returns:
            Unified response dict with stdout, stderr, exit_code, duration_ms,
            artifacts, and source='local'
        """
        self._ensure_initialized()

        is_valid, error = validate_skill_name(skill_id)
        if not is_valid:
            return self._exec_error_result(skill_id, entry_shell, f"Invalid skill_id: {error}")

        if skill_id not in self._skills_meta:
            return self._exec_error_result(
                skill_id, entry_shell, f"Skill '{skill_id}' not found"
            )

        meta = self._skills_meta[skill_id]
        skill_dir = Path(meta.base_path)

        exec_result = execute_skill_script(skill_dir, entry_shell)

        result = {
            "skill_id": skill_id,
            "entry_shell": entry_shell,
            **exec_result,
        }
        return {"answer": result, "block_answer": result}

    # =====================================================================
    # Private helpers
    # =====================================================================

    def _contract_error(self, skill_id: str, message: str) -> Dict[str, Any]:
        """Build a unified error response for load / read_file failures."""
        result = {"skill_id": skill_id, "error": message, "source": "local"}
        return {"answer": result, "block_answer": result}

    def _exec_error_result(
        self, skill_id: str, entry_shell: str, message: str
    ) -> Dict[str, Any]:
        """Build a unified error response for execute_script failures."""
        result = {
            "skill_id": skill_id,
            "entry_shell": entry_shell,
            "stdout": "",
            "stderr": message,
            "exit_code": -1,
            "duration_ms": 0,
            "artifacts": [],
            "source": "local",
        }
        return {"answer": result, "block_answer": result}
