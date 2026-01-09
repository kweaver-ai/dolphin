import os
import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from dolphin.core.logging.logger import get_logger
from .context_snapshot import ContextSnapshot

logger = get_logger()


class ContextSnapshotStore(ABC):
    """Abstract interface for context snapshot storage"""

    @abstractmethod
    def save_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Save snapshot, return snapshot ID"""
        pass

    @abstractmethod
    def load_snapshot(self, snapshot_id: str) -> Optional[ContextSnapshot]:
        """Load snapshot"""
        pass

    @abstractmethod
    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete snapshot"""
        pass

    @abstractmethod
    def list_snapshots(self, frame_id: Optional[str] = None) -> List[str]:
        """List snapshots"""
        pass

    @abstractmethod
    def save_pending_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Save pending snapshot (for transactional)"""
        pass

    @abstractmethod
    def finalize_snapshot(self, snapshot_id: str) -> bool:
        """Confirm Snapshot (Atomic Rename)"""
        pass


class FileContextSnapshotStore(ContextSnapshotStore):
    """Filesystem-based context snapshot storage"""

    def __init__(self, base_path: str = "./data/snapshots"):
        self.base_path = base_path
        self._lock = threading.RLock()
        self._ensure_directory()

    def _ensure_directory(self):
        """Ensure the storage directory exists"""
        os.makedirs(self.base_path, exist_ok=True)

    def _get_snapshot_path(self, snapshot_id: str) -> str:
        """Get snapshot file path"""
        return os.path.join(self.base_path, f"{snapshot_id}.json")

    def _get_pending_path(self, snapshot_id: str) -> str:
        """Get pending snapshot file path"""
        return os.path.join(self.base_path, f"{snapshot_id}.pending.json")

    def save_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Save snapshot"""
        with self._lock:
            file_path = self._get_snapshot_path(snapshot.snapshot_id)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot.encode(), f, ensure_ascii=False, indent=2)
                return snapshot.snapshot_id
            except Exception as e:
                raise RuntimeError(
                    f"Failed to save snapshot {snapshot.snapshot_id}: {e}"
                )

    def load_snapshot(self, snapshot_id: str) -> Optional[ContextSnapshot]:
        """Load snapshot"""
        with self._lock:
            file_path = self._get_snapshot_path(snapshot_id)
            if not os.path.exists(file_path):
                return None

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ContextSnapshot.decode(data)
            except Exception as e:
                raise RuntimeError(f"Failed to load snapshot {snapshot_id}: {e}")

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete snapshot"""
        with self._lock:
            file_path = self._get_snapshot_path(snapshot_id)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    return True
                except Exception:
                    return False
            return False

    def list_snapshots(self, frame_id: Optional[str] = None) -> List[str]:
        """List snapshots"""
        with self._lock:
            snapshots = []
            if not os.path.exists(self.base_path):
                return snapshots

            for filename in os.listdir(self.base_path):
                if filename.endswith(".json") and not filename.endswith(
                    ".pending.json"
                ):
                    snapshot_id = filename[:-5]  # Remove .json suffix

                    # If frame_id is specified, filter it.
                    if frame_id:
                        try:
                            snapshot = self.load_snapshot(snapshot_id)
                            if snapshot and snapshot.frame_id == frame_id:
                                snapshots.append(snapshot_id)
                        except Exception:
                            continue
                    else:
                        snapshots.append(snapshot_id)

            return sorted(snapshots)

    def save_pending_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Pending snapshot"""
        with self._lock:
            pending_path = self._get_pending_path(snapshot.snapshot_id)
            try:
                with open(pending_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot.encode(), f, ensure_ascii=False, indent=2)
                return snapshot.snapshot_id
            except Exception as e:
                raise RuntimeError(
                    f"Failed to save pending snapshot {snapshot.snapshot_id}: {e}"
                )

    def finalize_snapshot(self, snapshot_id: str) -> bool:
        """Confirm Snapshot (Atomic Rename)"""
        with self._lock:
            pending_path = self._get_pending_path(snapshot_id)
            final_path = self._get_snapshot_path(snapshot_id)

            if not os.path.exists(pending_path):
                return False

            try:
                os.rename(pending_path, final_path)
                return True
            except Exception:
                return False

    def cleanup_pending_snapshots(self, max_age_seconds: int = 3600) -> int:
        """Clean up expired pending snapshots"""
        with self._lock:
            cleaned = 0
            current_time = time.time()

            if not os.path.exists(self.base_path):
                return cleaned

            for filename in os.listdir(self.base_path):
                if filename.endswith(".pending.json"):
                    file_path = os.path.join(self.base_path, filename)
                    try:
                        file_mtime = os.path.getmtime(file_path)
                        if current_time - file_mtime > max_age_seconds:
                            os.remove(file_path)
                            cleaned += 1
                    except Exception:
                        continue

            return cleaned

    def get_snapshot_stats(self) -> Dict:
        """Get snapshot storage statistics"""
        with self._lock:
            stats = {
                "total_snapshots": 0,
                "pending_snapshots": 0,
                "total_size_bytes": 0,
            }

            if not os.path.exists(self.base_path):
                return stats

            for filename in os.listdir(self.base_path):
                file_path = os.path.join(self.base_path, filename)
                try:
                    file_size = os.path.getsize(file_path)
                    stats["total_size_bytes"] += file_size

                    if filename.endswith(".pending.json"):
                        stats["pending_snapshots"] += 1
                    elif filename.endswith(".json"):
                        stats["total_snapshots"] += 1
                except Exception:
                    continue

            return stats


class MemoryContextSnapshotStore(ContextSnapshotStore):
    """In-memory context snapshot storage (for testing)"""

    def __init__(self):
        self._snapshots: Dict[str, ContextSnapshot] = {}
        self._pending: Dict[str, ContextSnapshot] = {}
        self._lock = threading.RLock()

    def save_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Save snapshot"""
        with self._lock:
            self._snapshots[snapshot.snapshot_id] = snapshot
            return snapshot.snapshot_id

    def load_snapshot(self, snapshot_id: str) -> Optional[ContextSnapshot]:
        """Load snapshot"""
        with self._lock:
            return self._snapshots.get(snapshot_id)

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete snapshot"""
        with self._lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]
                return True
            return False

    def list_snapshots(self, frame_id: Optional[str] = None) -> List[str]:
        """List snapshots"""
        with self._lock:
            if frame_id:
                return [
                    sid
                    for sid, snapshot in self._snapshots.items()
                    if snapshot.frame_id == frame_id
                ]
            return list(self._snapshots.keys())

    def save_pending_snapshot(self, snapshot: ContextSnapshot) -> str:
        """Pending snapshot"""
        with self._lock:
            self._pending[snapshot.snapshot_id] = snapshot
            return snapshot.snapshot_id

    def finalize_snapshot(self, snapshot_id: str) -> bool:
        """Confirm Snapshot"""
        with self._lock:
            if snapshot_id in self._pending:
                snapshot = self._pending.pop(snapshot_id)
                self._snapshots[snapshot_id] = snapshot
                return True
            return False

    def clear(self):
        """Clear all snapshots"""
        with self._lock:
            self._snapshots.clear()
            self._pending.clear()
