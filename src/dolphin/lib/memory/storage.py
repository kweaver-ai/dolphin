"""
Storage layer for the memory management system.
"""

import abc
import json
import os
import glob
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timedelta


class MemoryStorage(abc.ABC):
    """Simple memory storage abstract interface - for basic memory read and write operations"""

    @abc.abstractmethod
    def write_memory(
        self, agent_name: str, user_id: str, memory_items: List[Dict[str, Any]]
    ) -> bool:
        """Write memory items

        Args:
            agent_name: Agent name
            user_id: User ID, empty string indicates agent memory
            memory_items: List of memory items

        Returns:
            bool: Whether successful
        """
        raise NotImplementedError

    @abc.abstractmethod
    def read_memory(
        self, agent_name: str, user_id: str, days_back: int = 7
    ) -> List[Dict[str, Any]]:
        """Read memory items

        Args:
            agent_name: Agent name
            user_id: User ID, empty string indicates agent memory
            days_back: Read memories from the last N days

        Returns:
            List[Dict[str, Any]]: List of memory items
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_dialog_logs(
        self, agent_name: str, user_id: str = "", count: int = 30
    ) -> List[Dict[str, Any]]:
        """Get conversation logs

        Args:
            agent_name: Agent name
            user_id: User ID, empty string to get logs for all users
            count: Number of entries to return

        Returns:
            List[Dict[str, Any]]: List of conversation logs
        """
        raise NotImplementedError


class MemoryFileSys(MemoryStorage):
    """A simple memory storage for filesystem implementation - for MemorySkillkit"""

    TimeFormat = "%Y%m%d%H%M"

    def __init__(self, base_path: str):
        """
        Initialize the simple memory storage.

        :param base_path: Base directory path for storing memory data
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def write_memory(
        self, agent_name: str, user_id: str, memory_items: List[Dict[str, Any]]
    ) -> bool:
        """Write memory items to date-organized files

        Args:
            agent_name: Agent name
            user_id: User ID, empty string indicates agent memory (using "_agent")
            memory_items: List of memory items

        Returns:
            bool: Whether successful
        """
        try:
            # If user_id is empty, use "_agent" for agent memory
            actual_user_id = user_id if user_id else "_agent"

            current_date = datetime.now().strftime(self.TimeFormat)
            memory_dir = self.base_path / agent_name / f"user_{actual_user_id}"
            memory_file = memory_dir / f"memory_{current_date}.jsonl"

            # Create directory if not exists
            memory_dir.mkdir(parents=True, exist_ok=True)

            # Write memory items to JSONL file
            with open(memory_file, "a", encoding="utf-8") as f:
                for item in memory_items:
                    if isinstance(item, dict):
                        # Add timestamp if not present
                        if "timestamp" not in item:
                            item["timestamp"] = datetime.now().isoformat()
                        f.write(json.dumps(item, ensure_ascii=False) + "\n")

            return True

        except Exception:
            return False

    def read_memory(
        self, agent_name: str, user_id: str, days_back: int = 7
    ) -> List[Dict[str, Any]]:
        """Read memory items from the past few days

        Args:
            agent_name: Agent name
            user_id: User ID, empty string indicates agent memory
            days_back: Number of days to look back

        Returns:
            List[Dict[str, Any]]: List of memory items
        """
        try:
            # If user_id is empty, use "_agent" for agent memory
            actual_user_id = user_id if user_id else "_agent"

            memory_dir = self.base_path / agent_name / f"user_{actual_user_id}"

            if not memory_dir.exists():
                return []

            # Find memory files from recent days
            memory_items = []
            for file in memory_dir.iterdir():
                if not file.is_file() or not file.name.startswith("memory_"):
                    continue

                date_str = file.name.split("_")[1].split(".")[0]
                date = datetime.strptime(date_str, self.TimeFormat)
                if date < (datetime.now() - timedelta(days=days_back)):
                    continue

                with open(file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                item = json.loads(line.strip())
                                memory_items.append(item)
                            except json.JSONDecodeError:
                                continue

            # Sort by timestamp if available
            memory_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return memory_items

        except Exception:
            return []

    def get_dialog_logs(
        self, agent_name: str, user_id: str = "", count: int = 30
    ) -> List[Dict[str, Any]]:
        """Get conversation log information

        Args:
            agent_name: Agent name
            user_id: User ID, empty string to get logs for all users
            count: Number of entries to return

        Returns:
            List[Dict[str, Any]]: List of conversation logs
        """
        try:
            logs = []

            # Dialog path structure: dialog_base_path/{agent_name}/user_{user_id}/dialog_*.jsonl
            dialog_base_path = self.base_path.parent / "dialog"

            if user_id:
                # Get logs for a specific user
                dialog_dir = dialog_base_path / agent_name / f"user_{user_id}"
                if dialog_dir.exists():
                    # Get the latest dialog file
                    dialog_files = sorted(
                        glob.glob(str(dialog_dir / "dialog_*.jsonl")), reverse=True
                    )
                    for file_path in dialog_files:
                        with open(file_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    try:
                                        msg = json.loads(line.strip())
                                        # Filter out system messages
                                        if msg.get("role") != "system":
                                            logs.append(msg)
                                        if len(logs) >= count:
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        if len(logs) >= count:
                            break
            else:
                # Get logs for all users
                dialog_base_dir = dialog_base_path / agent_name
                if dialog_base_dir.exists():
                    all_files = []
                    for user_dir in dialog_base_dir.iterdir():
                        if user_dir.is_dir():
                            dialog_files = glob.glob(str(user_dir / "dialog_*.jsonl"))
                            for file_path in dialog_files:
                                # Get file modification time for sorting
                                mtime = os.path.getmtime(file_path)
                                all_files.append((mtime, file_path))

                    # Sort by modification time (newest first)
                    all_files.sort(reverse=True)

                    for _, file_path in all_files:
                        with open(file_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    try:
                                        msg = json.loads(line.strip())
                                        # Filter out system messages
                                        if msg.get("role") != "system":
                                            logs.append(msg)
                                        if len(logs) >= count:
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        if len(logs) >= count:
                            break

            # Return the most recent count messages
            return logs[:count]

        except Exception:
            return []
