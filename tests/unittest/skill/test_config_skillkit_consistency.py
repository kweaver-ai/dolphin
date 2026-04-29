"""Verify that example config files only reference skillkit names
that exist in the registered entry points (after normalization)."""

import importlib.metadata
from pathlib import Path

import yaml
import pytest

from dolphin.core.config.global_config import SkillConfig

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"


def _get_registered_entry_point_names() -> set[str]:
    """Return the set of registered dolphin.skillkits entry point names."""
    eps = importlib.metadata.entry_points(group="dolphin.skillkits")
    return {ep.name for ep in eps}


def _collect_config_files() -> list[Path]:
    """Collect all global.template.yaml files under examples/."""
    return sorted(EXAMPLES_DIR.rglob("global.template.yaml"))


def _extract_enabled_skills(config_path: Path) -> list[str]:
    """Extract enabled_skills list from a config yaml."""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    skill_section = data.get("skill", {})
    enabled = skill_section.get("enabled_skills")
    if not isinstance(enabled, list):
        return []
    return [s for s in enabled if isinstance(s, str)]


@pytest.mark.parametrize("config_path", _collect_config_files(), ids=lambda p: str(p.relative_to(EXAMPLES_DIR)))
def test_enabled_skills_reference_valid_entry_points(config_path: Path):
    """Every skill name in enabled_skills should resolve to a known entry point."""
    registered = _get_registered_entry_point_names()
    skills = _extract_enabled_skills(config_path)

    for skill_name in skills:
        # Namespaced ids like "system_functions._date" are fine — they bypass
        # entry-point loading and are resolved by the skill config.
        if "." in skill_name:
            continue

        normalized = SkillConfig._normalize_skill_name(skill_name)
        assert normalized in registered, (
            f"Config {config_path.name} references skill '{skill_name}' "
            f"(normalized: '{normalized}') which is not in registered entry points: "
            f"{sorted(registered)}"
        )
