"""Verify that example config files only reference toolkit names
that exist in the registered entry points (after normalization)."""

import importlib.metadata
from pathlib import Path

import yaml
import pytest

from dolphin.core.config.global_config import ToolConfig

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"


def _get_registered_entry_point_names() -> set[str]:
    """Return the set of registered dolphin.toolkits entry point names."""
    eps = importlib.metadata.entry_points(group="dolphin.toolkits")
    return {ep.name for ep in eps}


def _collect_config_files() -> list[Path]:
    """Collect all global.template.yaml files under examples/."""
    return sorted(EXAMPLES_DIR.rglob("global.template.yaml"))


def _extract_enabled_tools(config_path: Path) -> list[str]:
    """Extract enabled_skills list from a config yaml."""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    skill_section = data.get("skill", {})
    enabled = skill_section.get("enabled_skills")
    if not isinstance(enabled, list):
        return []
    return [s for s in enabled if isinstance(s, str)]


@pytest.mark.parametrize("config_path", _collect_config_files(), ids=lambda p: str(p.relative_to(EXAMPLES_DIR)))
def test_enabled_tools_reference_valid_entry_points(config_path: Path):
    """Every tool name in enabled_skills should resolve to a known entry point."""
    registered = _get_registered_entry_point_names()
    tools = _extract_enabled_tools(config_path)

    for tool_name in tools:
        # Namespaced ids like "system_functions._date" are fine — they bypass
        # entry-point loading and are resolved by the tool config.
        if "." in tool_name:
            continue

        normalized = ToolConfig._normalize_tool_name(tool_name)
        assert normalized in registered, (
            f"Config {config_path.name} references tool '{tool_name}' "
            f"(normalized: '{normalized}') which is not in registered entry points: "
            f"{sorted(registered)}"
        )
