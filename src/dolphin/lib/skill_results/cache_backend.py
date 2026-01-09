"""Cache backend module
Provides tool result caching functionality, supports multiple storage backends
"""

import os
import json
import pickle
import hashlib
import sqlite3
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from dolphin.core.logging.logger import get_logger

logger = get_logger("skill_results")


@dataclass
class CacheEntry:
    """Cache Entry"""

    reference_id: str
    full_result: Any
    metadata: Dict[str, Any]
    created_at: datetime
    tool_name: str
    size: int = 0
    ttl: Optional[int] = None  # Expiration time (hours)

    def __post_init__(self):
        if self.size == 0:
            self.size = len(str(self.full_result))

    def is_expired(self) -> bool:
        """Check if expired"""
        if self.ttl is None:
            return False
        return datetime.now() > self.created_at + timedelta(hours=self.ttl)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        """Create from dictionary"""
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class CacheBackend(ABC):
    """Cache backend abstract interface"""

    @abstractmethod
    def store(self, entry: CacheEntry) -> bool:
        """Cache entry storage"""
        pass

    @abstractmethod
    def get(self, reference_id: str) -> Optional[CacheEntry]:
        """Get cache entry"""
        pass

    @abstractmethod
    def delete(self, reference_id: str) -> bool:
        """Delete cache entries"""
        pass

    @abstractmethod
    def cleanup(self, max_age_hours: int = 24) -> int:
        """Clean up expired cache and return the number cleaned."""
        pass

    @abstractmethod
    def exists(self, reference_id: str) -> bool:
        """Check if cache entry exists"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        pass


class MemoryCacheBackend(CacheBackend):
    """Memory Cache Backend"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: Dict[str, CacheEntry] = {}
        self.access_times: Dict[str, datetime] = {}

    def store(self, entry: CacheEntry) -> bool:
        """Cache entry storage"""
        try:
            # If the cache is full, remove the oldest entry
            if len(self.cache) >= self.max_size:
                self._evict_oldest()

            self.cache[entry.reference_id] = entry
            self.access_times[entry.reference_id] = datetime.now()
            logger.debug(f"Stored cache entry: {entry.reference_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store cache entry: {e}")
            return False

    def get(self, reference_id: str) -> Optional[CacheEntry]:
        """Get cache entry"""
        try:
            entry = self.cache.get(reference_id)
            if entry and not entry.is_expired():
                self.access_times[reference_id] = datetime.now()
                return entry
            elif entry and entry.is_expired():
                self.delete(reference_id)
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {reference_id}: {e}")
            return None

    def delete(self, reference_id: str) -> bool:
        """Delete cache entries"""
        try:
            if reference_id in self.cache:
                del self.cache[reference_id]
                del self.access_times[reference_id]
                logger.debug(f"Deleted cache entry: {reference_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete cache entry {reference_id}: {e}")
            return False

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Clean up expired cache"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            expired_keys = []

            for ref_id, entry in self.cache.items():
                if entry.is_expired() or entry.created_at < cutoff_time:
                    expired_keys.append(ref_id)

            for ref_id in expired_keys:
                self.delete(ref_id)

            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
            return len(expired_keys)
        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")
            return 0

    def exists(self, reference_id: str) -> bool:
        """Check if cache entry exists"""
        entry = self.get(reference_id)
        return entry is not None

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "total_entries": len(self.cache),
            "max_size": self.max_size,
            "usage_percent": (
                (len(self.cache) / self.max_size) * 100 if self.max_size > 0 else 0
            ),
        }

    def _evict_oldest(self):
        """Delete the oldest cache entry"""
        if not self.access_times:
            return

        oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        self.delete(oldest_key)


class FileCacheBackend(CacheBackend):
    """File Cache Backend"""

    def __init__(
        self, cache_dir: str = "./cache", max_file_size: int = 100 * 1024 * 1024
    ):  # 100MB
        self.cache_dir = cache_dir
        self.max_file_size = max_file_size
        self._ensure_cache_dir()

    def store(self, entry: CacheEntry) -> bool:
        """Store cache entry to file"""
        try:
            file_path = self._get_file_path(entry.reference_id)

            # Check file size limit
            if (
                os.path.exists(file_path)
                and os.path.getsize(file_path) > self.max_file_size
            ):
                logger.warning(f"Cache file too large, skipping: {entry.reference_id}")
                return False

            # Serialized data
            data = {
                "reference_id": entry.reference_id,
                "full_result": entry.full_result,
                "metadata": entry.metadata,
                "created_at": entry.created_at.isoformat(),
                "tool_name": entry.tool_name,
                "size": entry.size,
                "ttl": entry.ttl,
            }

            # Write to file
            with open(file_path, "wb") as f:
                pickle.dump(data, f)

            logger.debug(f"Stored cache entry to file: {entry.reference_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store cache entry to file: {e}")
            return False

    def get(self, reference_id: str) -> Optional[CacheEntry]:
        """Read cache entries from file"""
        try:
            file_path = self._get_file_path(reference_id)

            if not os.path.exists(file_path):
                return None

            # Read file
            with open(file_path, "rb") as f:
                data = pickle.load(f)

            # Create cache entry
            entry = CacheEntry(
                reference_id=data["reference_id"],
                full_result=data["full_result"],
                metadata=data["metadata"],
                created_at=datetime.fromisoformat(data["created_at"]),
                tool_name=data["tool_name"],
                size=data.get("size", 0),
                ttl=data.get("ttl"),
            )

            # Check if expired
            if entry.is_expired():
                self.delete(reference_id)
                return None

            logger.debug(f"Retrieved cache entry from file: {reference_id}")
            return entry
        except Exception as e:
            logger.error(f"Failed to get cache entry from file {reference_id}: {e}")
            return None

    def delete(self, reference_id: str) -> bool:
        """Delete cache files"""
        try:
            file_path = self._get_file_path(reference_id)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Deleted cache file: {reference_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete cache file {reference_id}: {e}")
            return False

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Clean up expired cache files"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            deleted_count = 0

            for filename in os.listdir(self.cache_dir):
                if filename.endswith(".cache"):
                    file_path = os.path.join(self.cache_dir, filename)
                    try:
                        # Check file modification time
                        if os.path.getmtime(file_path) < cutoff_time.timestamp():
                            os.remove(file_path)
                            deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to process cache file {filename}: {e}")

            logger.debug(f"Cleaned up {deleted_count} expired cache files")
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup cache files: {e}")
            return 0

    def exists(self, reference_id: str) -> bool:
        """Check if the cache file exists"""
        file_path = self._get_file_path(reference_id)
        return os.path.exists(file_path)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            total_files = 0
            total_size = 0

            for filename in os.listdir(self.cache_dir):
                if filename.endswith(".cache"):
                    file_path = os.path.join(self.cache_dir, filename)
                    total_files += 1
                    total_size += os.path.getsize(file_path)

            return {
                "total_entries": total_files,
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "cache_dir": self.cache_dir,
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}

    def _ensure_cache_dir(self):
        """Ensure the cache directory exists"""
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_file_path(self, reference_id: str) -> str:
        """Get cache file path"""
        # Use hashing to avoid excessively long filenames
        hash_id = hashlib.md5(reference_id.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{hash_id}.cache")


class DatabaseCacheBackend(CacheBackend):
    """Database Cache Backend"""

    def __init__(self, db_path: str = "./cache.db"):
        self.db_path = db_path
        self._init_database()

    def store(self, entry: CacheEntry) -> bool:
        """Store cache entry to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Serialized result data
                result_data = pickle.dumps(entry.full_result)

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO cache_entries 
                    (reference_id, full_result, metadata, created_at, tool_name, size, ttl)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        entry.reference_id,
                        result_data,
                        json.dumps(entry.metadata),
                        entry.created_at.isoformat(),
                        entry.tool_name,
                        entry.size,
                        entry.ttl,
                    ),
                )

                conn.commit()
                logger.debug(f"Stored cache entry to database: {entry.reference_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to store cache entry to database: {e}")
            return False

    def get(self, reference_id: str) -> Optional[CacheEntry]:
        """Read cache entries from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT full_result, metadata, created_at, tool_name, size, ttl
                    FROM cache_entries WHERE reference_id = ?
                """,
                    (reference_id,),
                )

                row = cursor.fetchone()
                if not row:
                    return None

                result_data, metadata_json, created_at_str, tool_name, size, ttl = row

                # Deserialized result data
                full_result = pickle.loads(result_data)
                metadata = json.loads(metadata_json)
                created_at = datetime.fromisoformat(created_at_str)

                entry = CacheEntry(
                    reference_id=reference_id,
                    full_result=full_result,
                    metadata=metadata,
                    created_at=created_at,
                    tool_name=tool_name,
                    size=size or 0,
                    ttl=ttl,
                )

                # Check if expired
                if entry.is_expired():
                    self.delete(reference_id)
                    return None

                logger.debug(f"Retrieved cache entry from database: {reference_id}")
                return entry
        except Exception as e:
            logger.error(f"Failed to get cache entry from database {reference_id}: {e}")
            return None

    def delete(self, reference_id: str) -> bool:
        """Delete database cache entries"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM cache_entries WHERE reference_id = ?", (reference_id,)
                )
                conn.commit()

                deleted = cursor.rowcount > 0
                if deleted:
                    logger.debug(f"Deleted cache entry from database: {reference_id}")
                return deleted
        except Exception as e:
            logger.error(
                f"Failed to delete cache entry from database {reference_id}: {e}"
            )
            return False

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Clean up expired cache entries"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Delete expired entries
                cursor.execute(
                    """
                    DELETE FROM cache_entries 
                    WHERE created_at < ? OR 
                          (ttl IS NOT NULL AND datetime(created_at, '+' || ttl || ' hours') < datetime('now'))
                """,
                    (cutoff_time.isoformat(),),
                )

                deleted_count = cursor.rowcount
                conn.commit()

                logger.debug(
                    f"Cleaned up {deleted_count} expired cache entries from database"
                )
                return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup database cache: {e}")
            return 0

    def exists(self, reference_id: str) -> bool:
        """Check if database cache entry exists"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM cache_entries WHERE reference_id = ?",
                    (reference_id,),
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check cache entry existence {reference_id}: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get database cache statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Total number of entries
                cursor.execute("SELECT COUNT(*) FROM cache_entries")
                total_entries = cursor.fetchone()[0]

                # Total size
                cursor.execute("SELECT COALESCE(SUM(size), 0) FROM cache_entries")
                total_size = cursor.fetchone()[0]

                # Group by tool type
                cursor.execute(
                    """
                    SELECT tool_name, COUNT(*) as count 
                    FROM cache_entries 
                    GROUP BY tool_name
                """
                )
                tool_stats = dict(cursor.fetchall())

                return {
                    "total_entries": total_entries,
                    "total_size_bytes": total_size,
                    "total_size_mb": (
                        total_size / (1024 * 1024) if total_size > 0 else 0
                    ),
                    "tool_stats": tool_stats,
                    "db_path": self.db_path,
                }
        except Exception as e:
            logger.error(f"Failed to get database cache stats: {e}")
            return {}

    def _init_database(self):
        """Initialize database tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        reference_id TEXT PRIMARY KEY,
                        full_result BLOB NOT NULL,
                        metadata TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        size INTEGER DEFAULT 0,
                        ttl INTEGER,
                        created_at_index TEXT GENERATED ALWAYS AS (created_at) VIRTUAL
                    )
                """
                )

                # Create index
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cache_entries_created_at 
                    ON cache_entries(created_at)
                """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cache_entries_tool_name 
                    ON cache_entries(tool_name)
                """
                )

                conn.commit()
                logger.debug("Database cache initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database cache: {e}")
            raise
