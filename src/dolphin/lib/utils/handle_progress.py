import json
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional
from dolphin.core.logging.logger import console


# Thread-safe global variables
class ProgressManager:
    def __init__(self, max_size=1000, expire_seconds=3600):
        self.progress_map: Dict[str, List[Dict]] = OrderedDict()
        self.progress_set: Dict[str, Dict[str, bool]] = {}
        self.lock = threading.RLock()
        self.max_size = max_size
        self.expire_seconds = expire_seconds
        self.last_access: Dict[str, float] = {}

    def _cleanup_expired(self):
        """Clean up expired progress data"""
        current_time = time.time()
        expired_keys = []

        for key, last_time in self.last_access.items():
            if current_time - last_time > self.expire_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            self._remove_key(key)

    def _remove_key(self, key: str):
        """Remove data for the specified key"""
        if key in self.progress_map:
            del self.progress_map[key]
        if key in self.progress_set:
            del self.progress_set[key]
        if key in self.last_access:
            del self.last_access[key]

    def _enforce_max_size(self):
        """Enforce maximum size limit"""
        while len(self.progress_map) > self.max_size:
            # Remove the oldest entry
            oldest_key = next(iter(self.progress_map))
            self._remove_key(oldest_key)


# Global progress manager instance
_progress_manager = ProgressManager()


def handle_progress(assistant_message_id: str, progresses: List[Dict]) -> List[Dict]:
    """Thread-safe version for processing progress information

        Args:
            assistant_message_id: Assistant message ID
            progresses: List of progress information (in dictionary format)

        Returns:
            Processed list of progress information
    """
    with _progress_manager.lock:
        # Clean up expired data
        _progress_manager._cleanup_expired()

        # Update access time
        _progress_manager.last_access[assistant_message_id] = time.time()

        # Get the progress collection of the current message
        progress_set_for_message = _progress_manager.progress_set.get(
            assistant_message_id, {}
        )
        current_progress: Optional[Dict] = None

        # Traverse all progress information
        for progress in progresses:
            status = progress.get("status", "")

            if status in ["completed", "failed"]:
                # Use more efficient hash values for deduplication
                progress_hash = hash(json.dumps(progress, sort_keys=True))

                # Check if already exists to avoid duplication
                if progress_hash not in progress_set_for_message:
                    # Ensure that there is a corresponding list in progress_map.
                    if assistant_message_id not in _progress_manager.progress_map:
                        _progress_manager.progress_map[assistant_message_id] = []

                    # Add to history progress list
                    _progress_manager.progress_map[assistant_message_id].append(
                        progress
                    )
                    # Marked as existing
                    progress_set_for_message[progress_hash] = True

            elif status == "processing":
                # Record the current progress being processed
                current_progress = progress

        # Update progress_set
        _progress_manager.progress_set[assistant_message_id] = progress_set_for_message

        # Enforce size limits
        _progress_manager._enforce_max_size()

        # Build return result
        result = []

        # Add historical progress (completed and failed)
        if assistant_message_id in _progress_manager.progress_map:
            result.extend(_progress_manager.progress_map[assistant_message_id])

        # Add the progress of the currently processed item (if any)
        if current_progress is not None:
            result.append(current_progress)

        return result


def cleanup_progress(assistant_message_id: str) -> None:
    """Thread-safe version to clear progress data for the specified message ID"""
    with _progress_manager.lock:
        _progress_manager._remove_key(assistant_message_id)


def initialize_progress(assistant_message_id: str) -> None:
    """Initialize progress data for the specified message ID (thread-safe version)"""
    with _progress_manager.lock:
        _progress_manager.progress_map[assistant_message_id] = []
        _progress_manager.progress_set[assistant_message_id] = {}
        _progress_manager.last_access[assistant_message_id] = time.time()


def get_progress_stats() -> Dict:
    """Get progress manager statistics (for monitoring)"""
    with _progress_manager.lock:
        return {
            "total_sessions": len(_progress_manager.progress_map),
            "total_progress_items": sum(
                len(items) for items in _progress_manager.progress_map.values()
            ),
            "max_size": _progress_manager.max_size,
            "expire_seconds": _progress_manager.expire_seconds,
        }


# Usage Examples
if __name__ == "__main__":
    # Initialize
    message_id = "msg_123"
    initialize_progress(message_id)

    # Example data
    progresses = [
        {
            "agent_name": "agent1",
            "stage": "thinking",
            "status": "completed",
            "answer": "Thinking completed",
        },
        {
            "agent_name": "agent1",
            "stage": "executing",
            "status": "processing",
            "answer": "正在执行",
        },
    ]

    # Processing Progress
    result = handle_progress(message_id, progresses)
    console(f"处理结果: {len(result)} 个进度")

    # Cleanup
    cleanup_progress(message_id)

    # Get statistical information
    stats = get_progress_stats()
    console(f"统计信息: {stats}")
