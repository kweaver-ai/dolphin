"""TTL/LRU cache implementation for ResourceSkillkit.

This module provides caching mechanisms for skill metadata (Level 1)
to optimize performance and reduce disk I/O.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar, Optional, Dict, Any

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """A single cache entry with TTL support.

    Attributes:
        value: The cached value
        created_at: Unix timestamp when entry was created
        last_accessed: Unix timestamp when entry was last accessed
    """

    value: T
    created_at: float
    last_accessed: float


class TTLLRUCache(Generic[T]):
    """Thread-safe TTL + LRU cache implementation.

    This cache combines Time-To-Live (TTL) expiration with Least Recently Used (LRU)
    eviction policy. Entries expire after TTL seconds, and when the cache is full,
    the least recently used entries are evicted first.

    Attributes:
        ttl_seconds: Time-to-live for cache entries in seconds
        max_size: Maximum number of entries in cache
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        """Initialize the cache.

        Args:
            ttl_seconds: TTL for entries (default 5 minutes)
            max_size: Maximum cache size (default 100 entries)
        """
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> Optional[T]:
        """Get a value from cache.

        Args:
            key: The cache key

        Returns:
            The cached value, or None if not found or expired
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            # Check TTL expiration
            if self._is_expired(entry):
                del self._cache[key]
                return None

            # Update last accessed time and move to end (most recently used)
            entry.last_accessed = time.time()
            self._cache.move_to_end(key)
            return entry.value

    def set(self, key: str, value: T) -> None:
        """Set a value in cache.

        Args:
            key: The cache key
            value: The value to cache
        """
        with self._lock:
            now = time.time()

            # If key exists, update it
            if key in self._cache:
                self._cache[key] = CacheEntry(
                    value=value, created_at=now, last_accessed=now
                )
                self._cache.move_to_end(key)
            else:
                # Evict if at capacity
                while len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)  # Remove oldest (LRU)

                self._cache[key] = CacheEntry(
                    value=value, created_at=now, last_accessed=now
                )

    def delete(self, key: str) -> bool:
        """Delete an entry from cache.

        Args:
            key: The cache key to delete

        Returns:
            True if entry was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries from cache."""
        with self._lock:
            self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries from cache.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() if self._is_expired(entry)
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    def _is_expired(self, entry: CacheEntry[T]) -> bool:
        """Check if a cache entry is expired.

        Args:
            entry: The cache entry to check

        Returns:
            True if expired, False otherwise
        """
        return time.time() - entry.created_at > self._ttl_seconds

    def __len__(self) -> int:
        """Return the number of entries in cache."""
        with self._lock:
            return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def keys(self) -> list:
        """Return list of all non-expired keys."""
        with self._lock:
            return [key for key, entry in self._cache.items() if not self._is_expired(entry)]

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        with self._lock:
            expired_count = sum(
                1 for entry in self._cache.values() if self._is_expired(entry)
            )
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl_seconds,
                "expired_entries": expired_count,
                "active_entries": len(self._cache) - expired_count,
            }


class SkillMetaCache(TTLLRUCache):
    """Specialized cache for Level 1 skill metadata.

    This cache stores SkillMeta objects for quick access during
    system prompt generation.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        """Initialize the skill metadata cache.

        Args:
            ttl_seconds: TTL for entries (default 5 minutes)
            max_size: Maximum cache size (default 100 skills)
        """
        super().__init__(ttl_seconds=ttl_seconds, max_size=max_size)


class SkillContentCache(TTLLRUCache):
    """Specialized cache for Level 2 skill content.

    This cache stores SkillContent objects for skills that have
    been fully loaded. Note that Level 2 content persistence is
    primarily handled via history bucket, this cache is for
    internal optimization.
    """

    def __init__(self, ttl_seconds: int = 600, max_size: int = 50):
        """Initialize the skill content cache.

        Args:
            ttl_seconds: TTL for entries (default 10 minutes)
            max_size: Maximum cache size (default 50 skills)
        """
        super().__init__(ttl_seconds=ttl_seconds, max_size=max_size)
