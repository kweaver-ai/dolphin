"""Unified skill invocation contract definitions.

This file is the single source of truth for the three built-in skill contracts:
- builtin_skill_load
- builtin_skill_read_file
- builtin_skill_execute_script

All schemas (description / inputs_schema / outputs) are defined here.
Both the executor's Tool subclasses and the local resource_skillkit can
import directly from this module without duplicating schema definitions.
"""

from typing import Any, Dict

# =====================================================================
# Contract name constants (reserved names — executor overrides any
# user-defined tool with the same name)
# =====================================================================

BUILTIN_SKILL_LOAD = "builtin_skill_load"
BUILTIN_SKILL_READ_FILE = "builtin_skill_read_file"
BUILTIN_SKILL_EXECUTE_SCRIPT = "builtin_skill_execute_script"

# =====================================================================
# builtin_skill_load contract
# =====================================================================

SKILL_LOAD_DESCRIPTION = (
    "Load the entry information for a skill (Phase 1 — must be called first). "
    "Returns the full SKILL.md content, a list of available script paths, "
    "and a list of available reference file paths. "
    "Whenever you have a skill_id, always call this function first before "
    "deciding any follow-up actions."
)

SKILL_LOAD_INPUTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill_id": {
            "type": "string",
            "description": (
                "Unique identifier of the skill. "
                "In online mode this is the real skill_id from the execution factory; "
                "in local testing mode this is the 'name' field from SKILL.md frontmatter."
            ),
        }
    },
    "required": ["skill_id"],
}

SKILL_LOAD_OUTPUTS: Dict[str, Any] = {
    "skill_id": {"type": "string", "description": "Unique skill identifier"},
    "skill_md_content": {"type": "string", "description": "Full SKILL.md Markdown content"},
    "available_scripts": {
        "type": "array",
        "description": "List of executable script paths (relative, e.g. scripts/foo.py)",
    },
    "available_references": {
        "type": "array",
        "description": "List of readable reference file paths (relative, e.g. references/bar.md)",
    },
    "source": {
        "type": "string",
        "description": "Data source: 'factory' (online) or 'local' (local testing)",
    },
}

# =====================================================================
# builtin_skill_read_file contract
# =====================================================================

SKILL_READ_FILE_DESCRIPTION = (
    "Read the full content of a specific file inside a skill package (Phase 2 — optional). "
    "Only call this after builtin_skill_load has returned a path list or "
    "SKILL.md has referenced a file path. "
    "Reads one file at a time; batch reads are not supported. "
    "Supported text formats: .md .txt .json .yaml .yml .py .sh .js .ts"
)

SKILL_READ_FILE_INPUTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill_id": {
            "type": "string",
            "description": "Unique skill identifier",
        },
        "file_path": {
            "type": "string",
            "description": (
                "Relative path of the file to read, e.g. references/engineering_metrics.md "
                "or scripts/foo.py. "
                "Only SKILL.md, references/... and scripts/... paths are allowed. "
                "Absolute paths and paths containing '..' are forbidden."
            ),
        },
    },
    "required": ["skill_id", "file_path"],
}

SKILL_READ_FILE_OUTPUTS: Dict[str, Any] = {
    "skill_id": {"type": "string", "description": "Unique skill identifier"},
    "file_path": {"type": "string", "description": "Relative path of the file that was read"},
    "content": {"type": "string", "description": "Full text content of the file"},
    "source": {
        "type": "string",
        "description": "Data source: 'factory' (online) or 'local' (local testing)",
    },
}

# =====================================================================
# builtin_skill_execute_script contract
# =====================================================================

SKILL_EXECUTE_SCRIPT_DESCRIPTION = (
    "Execute a script inside the skill's runtime environment (Phase 3 — optional). "
    "Must first call builtin_skill_load and read SKILL.md before deciding to call this. "
    "The entry_shell command is specified in SKILL.md (e.g. 'python scripts/analyze.py'). "
    "Use the exact entry_shell value from SKILL.md — do not construct the command yourself. "
    "Not every skill requires script execution; some only need SKILL.md or reference files. "
    "In online mode the script runs in the execution factory sandbox; "
    "in local testing mode it runs directly in the current environment."
)

SKILL_EXECUTE_SCRIPT_INPUTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill_id": {
            "type": "string",
            "description": "Unique skill identifier",
        },
        "entry_shell": {
            "type": "string",
            "description": (
                "The shell command to execute, as specified in SKILL.md. "
                "e.g. 'python scripts/analyze.py' or 'bash scripts/run.sh'. "
                "Copy this value directly from the 'Entry shell' field in SKILL.md."
            ),
        },
    },
    "required": ["skill_id", "entry_shell"],
}

SKILL_EXECUTE_SCRIPT_OUTPUTS: Dict[str, Any] = {
    "skill_id": {"type": "string", "description": "Unique skill identifier"},
    "entry_shell": {"type": "string", "description": "The shell command that was executed"},
    "stdout": {"type": "string", "description": "Script standard output"},
    "stderr": {"type": "string", "description": "Script standard error output"},
    "exit_code": {"type": "integer", "description": "Script exit code (0 = success)"},
    "duration_ms": {"type": "integer", "description": "Script execution time in milliseconds"},
    "artifacts": {
        "type": "array",
        "description": "List of artifacts produced by the script (currently empty in most cases)",
    },
    "source": {
        "type": "string",
        "description": "Execution source: 'factory' (online sandbox) or 'local' (local exec)",
    },
}

# =====================================================================
# Helper: build OpenAI function calling schema (reusable by executor Tools)
# =====================================================================


def build_openai_tool_schema(
    name: str,
    description: str,
    inputs_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an OpenAI function calling tool schema from contract definitions.

    Executor Tool subclasses (FactorySkillLoadTool etc.) and resource_skillkit
    can call this to obtain the inputs_schema for TriditionalToolkit.

    Args:
        name: Function name (one of the contract name constants)
        description: Function description shown to the model
        inputs_schema: JSON Schema for the input parameters

    Returns:
        OpenAI tool schema dict
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": inputs_schema,
        },
    }


# Pre-built OpenAI schemas — executor Tools can reference these directly
SKILL_LOAD_OPENAI_SCHEMA = build_openai_tool_schema(
    BUILTIN_SKILL_LOAD,
    SKILL_LOAD_DESCRIPTION,
    SKILL_LOAD_INPUTS_SCHEMA,
)

SKILL_READ_FILE_OPENAI_SCHEMA = build_openai_tool_schema(
    BUILTIN_SKILL_READ_FILE,
    SKILL_READ_FILE_DESCRIPTION,
    SKILL_READ_FILE_INPUTS_SCHEMA,
)

SKILL_EXECUTE_SCRIPT_OPENAI_SCHEMA = build_openai_tool_schema(
    BUILTIN_SKILL_EXECUTE_SCRIPT,
    SKILL_EXECUTE_SCRIPT_DESCRIPTION,
    SKILL_EXECUTE_SCRIPT_INPUTS_SCHEMA,
)
