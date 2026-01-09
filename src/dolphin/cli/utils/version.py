"""
Version management for Dolphin CLI

Reads version from VERSION file to avoid hardcoding.
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def getVersion() -> str:
    """
    Get version from VERSION file.
    
    Returns:
        Version string (e.g., "0.3.3")
    """
    # Try multiple paths to find VERSION file
    possiblePaths = [
        # When running from project root
        os.path.join(os.getcwd(), "VERSION"),
        # When running from bin/
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "VERSION"),
        # Fallback: relative to this file
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "VERSION"),
    ]
    
    for versionPath in possiblePaths:
        normalizedPath = os.path.normpath(versionPath)
        if os.path.exists(normalizedPath):
            try:
                with open(normalizedPath, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                continue
    
    return "unknown"


def getFullVersion() -> str:
    """
    Get full version string for display.
    
    Returns:
        Full version string (e.g., "Dolphin Language v0.3.3")
    """
    return f"Dolphin Language v{getVersion()}"

