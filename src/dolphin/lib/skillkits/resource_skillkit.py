"""Compatibility wrapper for ResourceSkillkit.

GlobalSkills' file-based loader scans only top-level `skill/installed/*.py`.
This module re-exports the package implementation so ResourceSkillkit can be
discovered in both entry-point and fallback modes.
"""

from dolphin.lib.skillkits.resource import ResourceSkillkit

__all__ = ["ResourceSkillkit"]

