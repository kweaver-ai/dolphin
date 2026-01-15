"""Unified skill invocation deduplication interface and implementation

This module provides an abstract base class and default implementation for skill invocation deduplication,
used to detect and handle duplicate tool calls, preventing infinite loops.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, Tuple


class SkillCallDeduplicator(ABC):
    """Base class for skill call deduplicator

        Provides a unified interface for detecting duplicate tool calls.
        Different exploration strategies can use different implementations.
    """
    MAX_DUPLICATE_COUNT = 5

    @abstractmethod
    def add(self, skill_call: Any, result: Optional[str] = None):
        """Add call record

        Args:
            skill_call: Skill call information, which can be a dict or tuple
            result: Optional call result, used for intelligent retry judgment
        """
        pass

    @abstractmethod
    def is_duplicate(self, skill_call: Any) -> bool:
        """Check if it's a repeated call (exceeding the maximum number of repetitions)

        Args:
            skill_call: Skill call information

        Returns:
            bool: Returns True if the number of repetitions exceeds the threshold
        """
        pass

    @abstractmethod
    def clear(self):
        """Clear all records"""
        pass

    @abstractmethod
    def get_call_key(self, skill_call: Any) -> str:
        """Get the unique identifier of the call, used to determine whether two calls are equivalent.

        Args:
            skill_call: Information about the skill call

        Returns:
            str: A normalized call identifier string
        """
        pass

    @abstractmethod
    def get_history(self) -> list:
        """Get the history of all recorded skill calls.

        Returns:
            List of skill call dictionaries
        """
        pass


class NoOpSkillCallDeduplicator(SkillCallDeduplicator):
    """Empty implementation of skill call deduplicator

        Use when deduplication logic needs to be disabled. This implementation:
        - Never marks calls as duplicates
        - Records no call information
    """

    def add(self, skill_call: Any, result: Optional[str] = None):
        """Do not record anything"""
        return

    def is_duplicate(self, skill_call: Any) -> bool:
        """Never consider it a repeated call"""
        return False

    def clear(self):
        """Do nothing"""
        return

    def get_call_key(self, skill_call: Any) -> str:
        """Return an empty string as a placeholder"""
        return ""

    def get_history(self) -> list:
        """Return empty list as no history is recorded"""
        return []


class DefaultSkillCallDeduplicator(SkillCallDeduplicator):
    """Default skill call deduplication implementation

        Supports two skill_call formats:
        1. dict format: {"name": "skill_name", "arguments": {...}}  (used by ToolCallStrategy)
        2. tuple format: (skill_name, params_dict)  (used by PromptStrategy)

        Features:
        - Uses normalized JSON as unique identifier
        - Supports intelligent retry logic (some tools like snapshot allow retries when results are invalid)
        - Caches call results for retry determination
    """

    def __init__(self):
        self.skillcalls: Dict[str, int] = {}
        self.call_results: Dict[str, str] = {}
        # Cache call_key to avoid duplicate serialization
        self._call_key_cache: Dict[int, str] = {}

    def clear(self):
        """Clear all records"""
        self.skillcalls.clear()
        self.call_results.clear()
        self._call_key_cache.clear()

    def get_history(self) -> list:
        """Get the history of all recorded skill calls.

        Returns:
            List of skill call dictionaries with name and arguments
        """
        history = []
        for call_key in self.skillcalls.keys():
            try:
                # Parse the call_key format: "skill_name:json_args"
                if ':' in call_key:
                    name, args_str = call_key.split(':', 1)
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = args_str
                    history.append({"name": name, "arguments": args})
                else:
                    history.append({"name": call_key, "arguments": {}})
            except Exception:
                # If parsing fails, add as-is
                history.append({"raw": call_key})
        return history

    def get_call_key(self, skill_call: Any) -> str:
        """Get the standardized string representation of a skill call.

                Supports two formats:
                - dict: {"name": "xxx", "arguments": {...}}
                - tuple: ("xxx", {...})

                Uses the normalized JSON string of the skill name and arguments as the unique identifier.
        """
        # Use object id as cache key
        cache_key = id(skill_call)
        if cache_key in self._call_key_cache:
            return self._call_key_cache[cache_key]

        skill_name, arguments = self._extract_skill_info(skill_call)

        # Normalized parameters: sorting keys, ensuring consistency
        try:
            if isinstance(arguments, dict):
                normalized_args = json.dumps(
                    arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                )
            else:
                normalized_args = json.dumps(
                    arguments, ensure_ascii=False, separators=(",", ":")
                )
        except (TypeError, ValueError):
            # Fallback to string representation when serialization fails
            normalized_args = str(arguments).strip()

        call_key = f"{skill_name}:{normalized_args}"
        self._call_key_cache[cache_key] = call_key
        return call_key

    def _extract_skill_info(self, skill_call: Any) -> Tuple[str, Any]:
        """Extract skill name and parameters from skill_call

        Args:
            skill_call: skill call information

        Returns:
            Tuple[str, Any]: (skill name, parameters)
        """
        if isinstance(skill_call, dict):
            # dict format: {"name": "xxx", "arguments": {...}}
            skill_name = skill_call.get("name", "")
            arguments = skill_call.get("arguments", {})
        elif isinstance(skill_call, (list, tuple)) and len(skill_call) >= 2:
            # tuple/list format: ("xxx", {...})
            skill_name = skill_call[0]
            arguments = skill_call[1]
        else:
            # Other formats, try stringifying
            skill_name = str(skill_call)
            arguments = {}

        return skill_name, arguments

    def add(self, skill_call: Any, result: Optional[str] = None):
        """Add skill call record

        Args:
            skill_call: skill call information
            result: optional call result
        """
        key = self.get_call_key(skill_call)
        self.skillcalls[key] = self.skillcalls.get(key, 0) + 1
        if result is not None:
            self.call_results[key] = result

    def is_duplicate(self, skill_call: Any) -> bool:
        """Check if it's a repeated call (exceeding the maximum number of repetitions)

                Features:
                - For certain tools (e.g., snapshot), re-calling is allowed if the previous call result is invalid

        Args:
            skill_call: Skill call information

        Returns:
            bool: Returns True if the repetition count exceeds the threshold
        """
        key = self.get_call_key(skill_call)

        # Smart retry: Certain tools allow retries when the result is invalid
        if self._should_allow_retry(skill_call, key):
            return False

        return self.skillcalls.get(key, 0) >= self.MAX_DUPLICATE_COUNT

    def _should_allow_retry(self, skill_call: Any, call_key: str) -> bool:
        """Determine whether retrying a skill call should be allowed.

        For certain tools (e.g., browser_snapshot), retries are allowed if previous results were invalid.

        Args:
            skill_call: Information about the skill call
            call_key: Standardized key for the call

        Returns:
            bool: Whether retrying is allowed
        """
        skill_name, arguments = self._extract_skill_info(skill_call)

        # Calls without arguments are not specially handled
        if not arguments:
            return False

        # For snapshot tools, check whether previous results are valid
        if "snapshot" in skill_name.lower():
            previous_result = self.call_results.get(call_key)
            if previous_result is not None:
                result_str = str(previous_result).strip().lower()
                # If the previous result is very short or contains error messages, retries are allowed
                return (
                    len(result_str) < 50
                    or "about:blank" in result_str
                    or "error" in result_str
                    or "empty" in result_str
                )

        return False

    def get_duplicate_count(self, skill_call: Any) -> int:
        """Get the number of repetitions for a skill call

        Args:
            skill_call: Information about the skill call

        Returns:
            int: Number of repetitions
        """
        key = self.get_call_key(skill_call)
        return self.skillcalls.get(key, 0)

    def repr_skill_call(self, skill_call: Any) -> str:
        """Get the string representation of a skill call (for logging)

        Args:
            skill_call: Information about the skill call

        Returns:
            str: String representation of the call
        """
        return self.get_call_key(skill_call)
