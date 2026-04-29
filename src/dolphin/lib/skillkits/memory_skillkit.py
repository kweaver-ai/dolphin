import json
import threading
import time
import re
from typing import Dict, List, Optional, Tuple, Any

from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.lib.memory.sandbox import MemorySandbox


# -----------------------------
# Read-Write Lock
# -----------------------------


class RWLock:
    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self) -> None:
        with self._cond:
            while self._writer or self._readers > 0:
                self._cond.wait()
            self._writer = True

    def release_write(self) -> None:
        with self._cond:
            self._writer = False
            self._cond.notify_all()

    def rlocked(self):
        class _Ctx:
            def __enter__(_self):
                self.acquire_read()
                return _self

            def __exit__(_self, exc_type, exc, tb):
                self.release_read()

        return _Ctx()

    def wlocked(self):
        class _Ctx:
            def __enter__(_self):
                self.acquire_write()
                return _self

            def __exit__(_self, exc_type, exc, tb):
                self.release_write()

        return _Ctx()


# -----------------------------
# Memory bucket per session
# -----------------------------


# Doc class no longer needed - using direct tree storage


class MemoryBucket:
    def __init__(self) -> None:
        # Hierarchical store: nested dicts; leaves are dict with keys: _value, _ts
        self.root: Dict[str, Any] = {}
        self.lock = RWLock()

    def _ensure_path(self, path: str) -> Tuple[Dict[str, Any], str]:
        parts = [p for p in path.split(".") if p]
        if not parts:
            raise ValueError("path must not be empty")
        node = self.root
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                node[p] = {}
            node = node[p]
        return node, parts[-1]

    def _node_to_text(self, path: str, value: str) -> str:
        # Index both key path and value
        return f"{path}\n{value or ''}"

    def set_value(self, path: str, value: str) -> None:
        with self.lock.wlocked():
            parent, leaf = self._ensure_path(path)
            ts = time.time()
            # update tree
            parent[leaf] = {"_value": value, "_ts": ts}

            # No index needed - direct storage only

    def set_dict(self, value_dict: Dict[str, Any], prefix: str = "") -> int:
        """Set values from nested dict. Returns number of leaves set."""
        count = 0
        # Use a stack to avoid recursion depth issues on deep trees
        stack: List[Tuple[str, Any]] = [(prefix, value_dict)]
        while stack:
            cur_prefix, obj = stack.pop()
            if isinstance(obj, dict):
                for k, v in obj.items():
                    new_prefix = f"{cur_prefix}.{k}" if cur_prefix else str(k)
                    if isinstance(v, dict):
                        stack.append((new_prefix, v))
                    else:
                        # Convert leaves to string as required
                        if not isinstance(v, str):
                            try:
                                v = json.dumps(v, ensure_ascii=False)
                            except Exception:
                                v = str(v)
                        self.set_value(new_prefix, v)
                        count += 1
            else:
                # Prefix points directly to non-dict leaf
                v = obj
                if not isinstance(v, str):
                    try:
                        v = json.dumps(v, ensure_ascii=False)
                    except Exception:
                        v = str(v)
                if cur_prefix:
                    self.set_value(cur_prefix, v)
                    count += 1
        return count

    def get_value(self, path: str) -> Optional[str]:
        with self.lock.rlocked():
            parts = [p for p in path.split(".") if p]
            node = self.root
            for p in parts:
                if not isinstance(node, dict) or p not in node:
                    return None
                node = node[p]
            if isinstance(node, dict) and "_value" in node:
                return node.get("_value")
            return None

    def _collect_doc_ids_under(self, path: str) -> set:
        if not path:
            return {doc.doc_id for doc in self.docs_by_path.values()}
        prefix = path + "."
        ids = set()
        for p, d in self.docs_by_path.items():
            if p == path or p.startswith(prefix):
                ids.add(d.doc_id)
        return ids

    def grep(self, path: str, pattern: str, topk: int = 10) -> List[Dict[str, Any]]:
        """Search for pattern in paths and values using simple string/regex matching"""
        with self.lock.rlocked():
            results = []

            # Determine search strategy
            if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
                # Regex pattern
                try:
                    regex_pattern = pattern[1:-1]  # strip / /
                    compiled_regex = re.compile(regex_pattern, re.IGNORECASE)
                    use_regex = True
                except re.error:
                    # Invalid regex, fall back to substring
                    use_regex = False
                    pattern = pattern.lower()
            else:
                # Simple substring matching
                use_regex = False
                pattern = pattern.lower()

            # Scan all entries under the specified path
            for entry_path, entry_data in self._iter_leaves_under_path(path):
                if "_value" not in entry_data or "_ts" not in entry_data:
                    continue

                entry_value = str(entry_data["_value"])
                entry_ts = entry_data["_ts"]

                # Search in both path and value
                search_text = f"{entry_path}\n{entry_value}"

                matched = False
                if use_regex:
                    if compiled_regex.search(search_text):
                        matched = True
                else:
                    if pattern in search_text.lower():
                        matched = True

                if matched:
                    # Calculate simple relevance score
                    score = self._calculate_simple_score(
                        entry_path, entry_value, pattern, use_regex
                    )
                    results.append(
                        {
                            "path": entry_path,
                            "value": entry_value,
                            "score": score,
                            "ts": entry_ts,
                        }
                    )

            # Sort by score (descending) and limit results
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:topk]

    def _iter_leaves_under_path(self, path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Iterate over all leaf nodes under a given path"""

        def _traverse(
            node: Dict[str, Any], current_path: str
        ) -> List[Tuple[str, Dict[str, Any]]]:
            leaves = []
            for key, value in node.items():
                if key.startswith("_"):  # Skip metadata keys like _value, _ts
                    continue

                new_path = f"{current_path}.{key}" if current_path else key

                if isinstance(value, dict):
                    if "_value" in value and "_ts" in value:
                        # This is a leaf node
                        leaves.append((new_path, value))
                    else:
                        # This is an intermediate node, recurse
                        leaves.extend(_traverse(value, new_path))
            return leaves

        if path:
            # Start from a specific subtree
            parts = [p for p in path.split(".") if p]
            node = self.root
            try:
                for part in parts:
                    node = node[part]
                return _traverse(node, path)
            except (KeyError, TypeError):
                return []
        else:
            # Start from root
            return _traverse(self.root, "")

    def _calculate_simple_score(
        self, entry_path: str, entry_value: str, pattern: str, use_regex: bool
    ) -> float:
        """Calculate a simple relevance score for string matching"""
        if use_regex:
            # For regex, just return 1.0 (binary match)
            return 1.0

        # For substring matching, prefer exact matches and path matches
        pattern_lower = pattern.lower()
        path_lower = entry_path.lower()
        value_lower = entry_value.lower()

        score = 0.0

        # Exact value match gets highest score
        if pattern_lower == value_lower:
            score += 10.0
        elif pattern_lower in value_lower:
            # Substring in value
            score += 5.0 * (len(pattern) / len(entry_value))

        # Path matching gets medium score
        if pattern_lower == path_lower:
            score += 8.0
        elif pattern_lower in path_lower:
            score += 3.0 * (len(pattern) / len(entry_path))

        # Bonus for shorter paths (more specific)
        score += max(0, 2.0 - len(entry_path.split(".")) * 0.1)

        return round(score, 6)

    def remove_path(self, path: str) -> bool:
        """Remove a specific path from the tree structure."""
        with self.lock.wlocked():
            parts = [p for p in path.split(".") if p]
            if not parts:
                return False

            # Navigate to parent and remove leaf
            try:
                node = self.root
                for p in parts[:-1]:
                    if not isinstance(node, dict) or p not in node:
                        return False
                    node = node[p]

                if isinstance(node, dict) and parts[-1] in node:
                    node.pop(parts[-1], None)
                    return True
            except (KeyError, TypeError):
                pass

            return False

    def expire_old_entries(self, max_age_seconds: float) -> int:
        """Remove entries older than max_age_seconds. Returns number of removed entries."""
        cutoff_time = time.time() - max_age_seconds
        expired_paths = []

        # Find expired entries
        with self.lock.rlocked():
            for entry_path, entry_data in self._iter_leaves_under_path(""):
                if "_ts" in entry_data and entry_data["_ts"] < cutoff_time:
                    expired_paths.append(entry_path)

        # Remove expired entries (acquire write lock separately to avoid deadlock)
        removed_count = 0
        for path in expired_paths:
            if self.remove_path(path):
                removed_count += 1

        return removed_count

    def get_stats(self) -> Dict[str, Any]:
        """Get bucket statistics."""
        with self.lock.rlocked():
            entries = list(self._iter_leaves_under_path(""))
            return {
                "total_entries": len(entries),
                "storage_type": "simple_tree",
                "search_method": "string_matching",
            }

    def export_dict(self) -> Dict[str, Any]:
        # Export the hierarchical dict including timestamps
        with self.lock.rlocked():
            return json.loads(json.dumps(self.root, ensure_ascii=False))


class MemoryStore:
    """Singleton-like in-process memory store keyed by session_id."""

    def __init__(self) -> None:
        self._buckets: Dict[str, MemoryBucket] = {}
        self._lock = threading.Lock()

    def get_bucket(self, session_id: str) -> MemoryBucket:
        if not session_id:
            raise ValueError("session_id must not be empty")
        # Double-checked locking to minimize contention
        bucket = self._buckets.get(session_id)
        if bucket is not None:
            return bucket
        with self._lock:
            bucket = self._buckets.get(session_id)
            if bucket is None:
                bucket = MemoryBucket()
                self._buckets[session_id] = bucket
        return bucket


_GLOBAL_STORE = MemoryStore()


class MemorySkillkit(Skillkit):
    """In-memory key-value store per session with hierarchical paths and intelligent string matching.

        Data structure:
        - Bucketed by session_id, with a tree structure (dot-separated paths) inside each bucket.
        - Each leaf node stores {'_value': str, '_ts': float} for easy expiration strategy later.
        - Uses efficient string matching and regular expressions, optimized for small data scenarios, supports intelligent scoring.
        - Each session bucket uses RWLock, read-shared and write-exclusive, ensuring concurrent safety and high read performance.
    """

    def getName(self) -> str:
        return "memory_skillkit"

    # -----------------------------
    # Private helpers
    # -----------------------------

    def _get_storage_base(self) -> str:
        """Get storage base path from config or use default."""
        memory_config = getattr(
            getattr(self, "globalConfig", None), "memory_config", None
        )
        return memory_config.storage_path if memory_config else "data/memory/"

    # -----------------------------
    # Core APIs
    # -----------------------------

    def _mem_set(self, path: str, value: str, **kwargs) -> str:
        """Set the string value at the specified path in mem.

        Args:
            path (str): The path separated by dots, for example "user.profile.name".
            value (str): The string value to set.

        Returns:
            str: A JSON string, for example {"success": true}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        bucket.set_value(path, value)
        return json.dumps({"success": True}, ensure_ascii=False)

    def _mem_set_dict(self, value_dict: Dict[str, Any], **kwargs) -> str:
        """Batch set multiple path values in mem, supporting nested dictionaries; leaf values will be converted to strings.

        Args:
            value_dict (dict): Nested dictionary structure, leaves are of any type (will be automatically converted to strings).

        Returns:
            str: JSON string, for example {"success": true, "updated": 3}
        """
        if not isinstance(value_dict, dict):
            raise ValueError("value_dict must be a dict")
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        updated = bucket.set_dict(value_dict)
        return json.dumps({"success": True, "updated": updated}, ensure_ascii=False)

    def _mem_get(self, path: str, **kwargs) -> str:
        """Get the string value at the specified path from mem.

        Args:
            path (str): Path separated by dots.

        Returns:
            str: JSON string, for example {"success": true, "found": true, "value": "..."}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        val = bucket.get_value(path)
        return json.dumps(
            {"success": True, "found": val is not None, "value": val or ""},
            ensure_ascii=False,
        )

    def _mem_grep(self, path: str, pattern: str, **kwargs) -> str:
        """Perform intelligent pattern matching and recall under the specified path (subtree) in mem.

        Args:
            path (str): The root path of the search scope; an empty string indicates the entire session bucket.
            pattern (str): The retrieval pattern. Plain strings perform substring matching, while patterns wrapped in /.../ are matched as regular expressions.

        Returns:
            str: A JSON string in the format {"success": true, "results": [{path, value, score, ts}]}
            Results are sorted by intelligent scoring: exact match > path match > value contains > path contains.
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        results = bucket.grep(path or "", pattern, topk=10)
        return json.dumps({"success": True, "results": results}, ensure_ascii=False)

    def _mem_save(self, local_filepath: str, **kwargs) -> str:
        """Save the mem dictionary of the current session to a JSON file in the session sandbox.

        Args:
            local_filepath (str): File path relative to the session sandbox (must be .json).

        Returns:
            str: JSON string, for example {"success": true, "path": "..."}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        try:
            bucket = _GLOBAL_STORE.get_bucket(session_id)
            data = bucket.export_dict()

            # Resolve sandbox path
            storage_base = self._get_storage_base()
            sandbox = MemorySandbox(storage_base)
            safe_path = sandbox.resolve_session_path(session_id, local_filepath)

            payload = json.dumps(data, ensure_ascii=False, indent=2)
            sandbox.check_size_bytes(len(payload.encode("utf-8")))

            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(payload)
            return json.dumps(
                {"success": True, "path": str(safe_path)}, ensure_ascii=False
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    def _mem_remove(self, path: str, **kwargs) -> str:
        """Remove data at the specified path from mem.

        Args:
            path (str): Dot-separated path to be removed.

        Returns:
            str: Operation result as a JSON string, for example {"success": true, "removed": true}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        removed = bucket.remove_path(path)
        return json.dumps({"success": True, "removed": removed}, ensure_ascii=False)

    def _mem_expire(self, max_age_seconds: float, **kwargs) -> str:
        """Clean up expired data in mem for a specified session that exceeds a specified time.

        Args:
            max_age_seconds (float): Maximum age (in seconds), data older than this will be deleted.

        Returns:
            str: Operation result, JSON string, e.g., {"success": true, "expired_count": 5}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        expired_count = bucket.expire_old_entries(max_age_seconds)
        return json.dumps(
            {"success": True, "expired_count": expired_count}, ensure_ascii=False
        )

    def _mem_stats(self, **kwargs) -> str:
        """Get the storage statistics for a specified session in mem.

        Args:
            None

        Returns:
            str: Statistics in JSON format, containing {success, total_entries, storage_type, search_method}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)
        stats = bucket.get_stats()
        stats_out = {"success": True}
        stats_out.update(stats)
        return json.dumps(stats_out, ensure_ascii=False)

    def _mem_view(self, path: str = "", **kwargs) -> str:
        """View the contents or directory structure at the specified path.

        Args:
            path: Dot-separated path, empty string represents the root directory

        Returns:
            str: JSON string
                - File: {"success": true, "type": "file", "value": "..."}
                - Directory: {"success": true, "type": "directory", "children": ["name", "age", "profile"]}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        bucket = _GLOBAL_STORE.get_bucket(session_id)

        if not path:
            keys = [k for k in bucket.root.keys() if not str(k).startswith("_")]
            return json.dumps(
                {"success": True, "type": "directory", "children": keys},
                ensure_ascii=False,
            )

        parts = [p for p in path.split(".") if p]
        node = bucket.root
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                return json.dumps(
                    {"success": False, "error": "path not found"}, ensure_ascii=False
                )
            node = node[p]

        if isinstance(node, dict) and "_value" in node:
            return json.dumps(
                {"success": True, "type": "file", "value": node.get("_value", "")},
                ensure_ascii=False,
            )
        if isinstance(node, dict):
            keys = [k for k in node.keys() if not str(k).startswith("_")]
            return json.dumps(
                {"success": True, "type": "directory", "children": keys},
                ensure_ascii=False,
            )
        return json.dumps(
            {"success": False, "error": "invalid node"}, ensure_ascii=False
        )

    def _mem_load(self, local_filepath: str, **kwargs) -> str:
        """Load data from a JSON file in the session sandbox into memory (overwriting import).

        Args:
            local_filepath: Relative JSON file path to the session sandbox

        Returns:
            str: JSON string, for example {"success": true, "entries_loaded": 10}
        """
        session_id = self.getSessionId(
            session_id=kwargs.get("session_id"), props=kwargs.get("props")
        )
        try:
            bucket = _GLOBAL_STORE.get_bucket(session_id)
            storage_base = self._get_storage_base()
            sandbox = MemorySandbox(storage_base)
            safe_path = sandbox.resolve_session_path(session_id, local_filepath)
            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read()
            sandbox.check_size_bytes(len(content.encode("utf-8")))
            data = json.loads(content)
            # IMPORTANT: Complete overwrite (not merge) - this replaces all existing data
            bucket.root = data if isinstance(data, dict) else {}
            entries_loaded = len(bucket._iter_leaves_under_path(""))
            return json.dumps(
                {"success": True, "entries_loaded": entries_loaded}, ensure_ascii=False
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    # -----------------------------
    # Skill exports
    # -----------------------------

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self._mem_set),
            SkillFunction(self._mem_set_dict),
            SkillFunction(self._mem_get),
            SkillFunction(self._mem_grep),
            SkillFunction(self._mem_view),
            SkillFunction(self._mem_load),
            SkillFunction(self._mem_save),
            SkillFunction(self._mem_remove),
            SkillFunction(self._mem_expire),
            SkillFunction(self._mem_stats),
        ]
