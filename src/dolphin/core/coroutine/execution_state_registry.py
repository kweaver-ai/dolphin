import time
import threading
from typing import Dict, List, Optional, Tuple
from .execution_frame import ExecutionFrame, FrameStatus


class ExecutionStateRegistry:
    """Execution Status Registry - Manage the lifecycle of all execution frames"""

    def __init__(self):
        self._frames: Dict[str, ExecutionFrame] = {}
        self._lock = threading.RLock()  # Using Reentrant Lock

    def register_frame(self, frame: ExecutionFrame) -> bool:
        """Register Execution Frame"""
        with self._lock:
            if frame.frame_id in self._frames:
                return False
            self._frames[frame.frame_id] = frame
            return True

    def get_frame(self, frame_id: str) -> Optional[ExecutionFrame]:
        """Get execution frame"""
        with self._lock:
            return self._frames.get(frame_id)

    def update_frame(self, frame: ExecutionFrame) -> bool:
        """Update execution frame"""
        with self._lock:
            if frame.frame_id not in self._frames:
                return False
            frame.update_timestamp()
            self._frames[frame.frame_id] = frame
            return True

    def compare_and_swap(
        self, frame_id: str, expected_version: int, updates: Dict
    ) -> Tuple[bool, Optional[ExecutionFrame]]:
        """Optimistic Concurrency Control - Compare and Swap"""
        with self._lock:
            frame = self._frames.get(frame_id)
            if not frame:
                return False, None

            # Simplified version control - using update timestamp as version
            current_version = int(frame.updated_at)
            if current_version != expected_version:
                return False, frame

            # Application Update
            for key, value in updates.items():
                if hasattr(frame, key):
                    setattr(frame, key, value)

            frame.update_timestamp()
            self._frames[frame_id] = frame
            return True, frame

    def remove_frame(self, frame_id: str) -> bool:
        """Remove execution frame"""
        with self._lock:
            if frame_id in self._frames:
                del self._frames[frame_id]
                return True
            return False

    def get_child_frames(self, parent_id: str) -> List[ExecutionFrame]:
        """Get the list of child execution frames"""
        with self._lock:
            children = []
            for frame in self._frames.values():
                if frame.parent_id == parent_id:
                    children.append(frame)
            return children

    def get_frame_tree(self, root_id: str) -> Dict:
        """Get the frame tree with the specified frame as root"""
        with self._lock:
            root_frame = self._frames.get(root_id)
            if not root_frame:
                return {}

            def build_tree(frame_id: str) -> Dict:
                frame = self._frames.get(frame_id)
                if not frame:
                    return {}

                tree = {"frame": frame, "children": []}

                for child_id in frame.children:
                    child_tree = build_tree(child_id)
                    if child_tree:
                        tree["children"].append(child_tree)

                return tree

            return build_tree(root_id)

    def list_frames_by_status(self, status: FrameStatus) -> List[ExecutionFrame]:
        """List execution frames by status"""
        with self._lock:
            return [frame for frame in self._frames.values() if frame.status == status]

    def list_all_frames(self) -> List[ExecutionFrame]:
        """List all executed frames"""
        with self._lock:
            return list(self._frames.values())

    def get_frame_count(self) -> int:
        """Get the number of execution frames"""
        with self._lock:
            return len(self._frames)

    def get_stats(self) -> Dict:
        """Get registry statistics"""
        with self._lock:
            stats = {
                "total_frames": len(self._frames),
                "running": 0,
                "paused": 0,
                "completed": 0,
                "failed": 0,
                "waiting_for_intervention": 0,
            }

            for frame in self._frames.values():
                if frame.status == FrameStatus.RUNNING:
                    stats["running"] += 1
                elif frame.status == FrameStatus.PAUSED:
                    stats["paused"] += 1
                elif frame.status == FrameStatus.COMPLETED:
                    stats["completed"] += 1
                elif frame.status == FrameStatus.FAILED:
                    stats["failed"] += 1
                elif frame.status == FrameStatus.WAITING_FOR_INTERVENTION:
                    stats["waiting_for_intervention"] += 1

            return stats

    def cleanup_completed_frames(self, max_age_seconds: int = 3600) -> int:
        """Clean up completed old execution frames"""
        with self._lock:
            current_time = time.time()
            to_remove = []

            for frame_id, frame in self._frames.items():
                if (
                    frame.status in [FrameStatus.COMPLETED, FrameStatus.FAILED]
                    and current_time - frame.updated_at > max_age_seconds
                ):
                    to_remove.append(frame_id)

            for frame_id in to_remove:
                del self._frames[frame_id]

            return len(to_remove)

    def clear(self):
        """Clear all execution frames"""
        with self._lock:
            self._frames.clear()
