from __future__ import annotations

from pathlib import Path


class MemorySandbox:
    """Session-scoped filesystem sandbox for memory persistence.

    - Only allows relative paths under `<storage_base>/memories/<session_id>/`.
    - Only allows `.json` files.
    - Provides simple size checks.
    """

    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_PATH_LENGTH = 512

    def __init__(self, storage_base: str | Path = "data/memory/") -> None:
        self.root = (Path(storage_base) / "memories").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_session_path(self, session_id: str, rel_path: str) -> Path:
        if not session_id:
            raise ValueError("session_id must not be empty")
        if not rel_path or rel_path.startswith("/"):
            raise ValueError("Only relative paths are allowed")
        if len(rel_path) > self.MAX_PATH_LENGTH:
            raise ValueError("Path too long")

        rel = Path(rel_path)
        if ".." in rel.parts:
            raise ValueError("Path escapes sandbox")
        if rel.suffix.lower() != ".json":
            raise ValueError("Only .json is allowed")

        session_dir = (self.root / session_id).resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
        full_path = (session_dir / rel).resolve()
        # Ensure no escape from session_dir
        full_path.relative_to(session_dir)
        # Ensure parent dirs exist
        full_path.parent.mkdir(parents=True, exist_ok=True)
        return full_path

    def check_size_bytes(self, size: int) -> None:
        if size > self.MAX_SIZE:
            raise ValueError("File too large")
