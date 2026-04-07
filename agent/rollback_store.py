"""
Rollback Store - deterministic per-run snapshots for agent edits.

Each agent execution creates a single checkpoint id representing the full state
of all allowed directories before the run. Rolling back that checkpoint restores
the entire scoped workspace state and removes any files that were created later.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

CHECKPOINT_METADATA_FILE = "checkpoints.json"


@dataclass
class CheckpointInfo:
    """Information about a checkpoint."""

    checkpoint_id: str
    original_path: str
    checkpoint_path: str
    timestamp: float
    file_content: str | None = None
    file_count: int = 0
    files: list[str] = field(default_factory=list)
    allowed_dirs: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)


class RollbackStore:
    """Manages checkpoints for agent file operations."""

    def __init__(self, checkpoint_dir: Path | str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.checkpoint_dir / CHECKPOINT_METADATA_FILE

    def _load_metadata(self) -> dict[str, dict]:
        if not self.metadata_file.exists():
            return {}
        try:
            return json.loads(self.metadata_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load checkpoint metadata: %s", exc)
            return {}

    def _save_metadata(self, metadata: dict[str, dict]) -> None:
        self.metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def create_checkpoint(self, file_path: Path, original_content: str | None = None) -> str:
        """Create a single-file checkpoint."""
        file_path = file_path.resolve()
        checkpoint_id = f"cp-{uuid.uuid4().hex[:12]}"
        timestamp = time.time()
        snapshot_root = self.checkpoint_dir / checkpoint_id
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_root / "snapshot.txt"

        if original_content is None:
            original_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        snapshot_path.write_text(original_content, encoding="utf-8")

        metadata = self._load_metadata()
        metadata[checkpoint_id] = {
            "checkpoint_id": checkpoint_id,
            "original_path": str(file_path),
            "checkpoint_path": str(snapshot_root),
            "timestamp": timestamp,
            "file_content": None,
            "file_count": 1,
            "files": [str(file_path)],
            "allowed_dirs": [str(file_path.parent)],
            "deleted_paths": [],
            "entries": [
                {
                    "original_path": str(file_path),
                    "snapshot_rel": "snapshot.txt",
                }
            ],
        }
        self._save_metadata(metadata)
        return checkpoint_id

    def create_run_checkpoint(self, allowed_dirs: list[Path]) -> str:
        """Snapshot the full state of all allowed directories for one agent run."""
        checkpoint_id = f"run-{uuid.uuid4().hex[:12]}"
        timestamp = time.time()
        snapshot_root = self.checkpoint_dir / checkpoint_id
        snapshot_root.mkdir(parents=True, exist_ok=True)

        entries: list[dict[str, str]] = []
        original_paths: list[str] = []
        normalized_dirs = [path.resolve() for path in allowed_dirs]

        for dir_index, allowed_dir in enumerate(normalized_dirs):
            if not allowed_dir.exists():
                continue
            for file_path in sorted(p for p in allowed_dir.rglob("*") if p.is_file()):
                rel_path = file_path.relative_to(allowed_dir)
                snapshot_rel = Path(f"dir_{dir_index}") / rel_path
                snapshot_path = snapshot_root / snapshot_rel
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_bytes(file_path.read_bytes())
                entries.append(
                    {
                        "original_path": str(file_path.resolve()),
                        "snapshot_rel": str(snapshot_rel),
                    }
                )
                original_paths.append(str(file_path.resolve()))

        metadata = self._load_metadata()
        metadata[checkpoint_id] = {
            "checkpoint_id": checkpoint_id,
            "original_path": "",
            "checkpoint_path": str(snapshot_root),
            "timestamp": timestamp,
            "file_content": None,
            "file_count": len(entries),
            "files": original_paths,
            "allowed_dirs": [str(path) for path in normalized_dirs],
            "deleted_paths": [],
            "entries": entries,
        }
        self._save_metadata(metadata)
        _logger.info("Created run checkpoint %s with %d files", checkpoint_id, len(entries))
        return checkpoint_id

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointInfo | None:
        metadata = self._load_metadata()
        info = metadata.get(checkpoint_id)
        if not info:
            return None
        return CheckpointInfo(
            checkpoint_id=info["checkpoint_id"],
            original_path=info.get("original_path", ""),
            checkpoint_path=info["checkpoint_path"],
            timestamp=info["timestamp"],
            file_content=info.get("file_content"),
            file_count=info.get("file_count", len(info.get("files", []))),
            files=info.get("files", []),
            allowed_dirs=info.get("allowed_dirs", []),
            deleted_paths=info.get("deleted_paths", []),
        )

    def rollback(self, checkpoint_id: str) -> str | None:
        """Restore the entire checkpointed state for a run."""
        metadata = self._load_metadata()
        info = metadata.get(checkpoint_id)
        if not info:
            _logger.warning("Checkpoint %s not found", checkpoint_id)
            return None

        snapshot_root = Path(info["checkpoint_path"])
        if not snapshot_root.exists():
            raise FileNotFoundError(f"Checkpoint directory not found: {snapshot_root}")

        restored_paths: list[str] = []
        entries = info.get("entries", [])
        original_path_set = {entry["original_path"] for entry in entries}

        for entry in entries:
            original_path = Path(entry["original_path"])
            snapshot_path = snapshot_root / entry["snapshot_rel"]
            if not snapshot_path.exists():
                raise FileNotFoundError(f"Checkpoint file not found: {snapshot_path}")
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(snapshot_path.read_bytes())
            restored_paths.append(str(original_path))

        deleted_paths: list[str] = []
        for allowed_dir_str in info.get("allowed_dirs", []):
            allowed_dir = Path(allowed_dir_str)
            if not allowed_dir.exists():
                continue
            for file_path in sorted(p for p in allowed_dir.rglob("*") if p.is_file()):
                resolved = str(file_path.resolve())
                if resolved not in original_path_set:
                    file_path.unlink()
                    deleted_paths.append(resolved)

        info["deleted_paths"] = deleted_paths
        metadata[checkpoint_id] = info
        self._save_metadata(metadata)

        _logger.info(
            "Rolled back checkpoint %s: restored %d files, removed %d new files",
            checkpoint_id,
            len(restored_paths),
            len(deleted_paths),
        )
        if len(restored_paths) == 1 and not deleted_paths:
            return Path(restored_paths[0]).read_text(encoding="utf-8")
        return (
            f"Restored {len(restored_paths)} file(s)"
            + (f" and removed {len(deleted_paths)} new file(s)" if deleted_paths else "")
        )

    def list_checkpoints(self, original_path: Path | None = None) -> list[CheckpointInfo]:
        """List checkpoints, optionally filtered by original file path."""
        target = str(original_path.resolve()) if original_path is not None else None
        checkpoints: list[CheckpointInfo] = []
        for checkpoint_id, info in self._load_metadata().items():
            files = info.get("files", [])
            if target is not None and target not in files and info.get("original_path") != target:
                continue
            checkpoints.append(
                CheckpointInfo(
                    checkpoint_id=checkpoint_id,
                    original_path=info.get("original_path", ""),
                    checkpoint_path=info["checkpoint_path"],
                    timestamp=info["timestamp"],
                    file_content=info.get("file_content"),
                    file_count=info.get("file_count", len(files)),
                    files=files,
                    allowed_dirs=info.get("allowed_dirs", []),
                    deleted_paths=info.get("deleted_paths", []),
                )
            )
        checkpoints.sort(key=lambda checkpoint: checkpoint.timestamp, reverse=True)
        return checkpoints

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        metadata = self._load_metadata()
        info = metadata.get(checkpoint_id)
        if not info:
            return False

        snapshot_root = Path(info["checkpoint_path"])
        if snapshot_root.exists():
            for child in sorted(snapshot_root.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            snapshot_root.rmdir()

        del metadata[checkpoint_id]
        self._save_metadata(metadata)
        return True

    def get_latest_checkpoint(self, original_path: Path) -> CheckpointInfo | None:
        checkpoints = self.list_checkpoints(original_path)
        return checkpoints[0] if checkpoints else None
