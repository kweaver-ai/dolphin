"""Compatibility wrapper for ResourceToolkit.

GlobalTools' file-based loader scans only top-level `tool/installed/*.py`.
This module re-exports the package implementation so ResourceToolkit can be
discovered in both entry-point and fallback modes.
"""

from dolphin.lib.toolkits.resource import ResourceToolkit

__all__ = ["ResourceToolkit"]

