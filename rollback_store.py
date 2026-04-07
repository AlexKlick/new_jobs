"""
Rollback Store - Agent Checkpoint Management

Provides checkpoint tracking for agent-performed file operations, enabling rollback capability.

Usage:
    store = RollbackStore(checkpoint_dir=Path(".agent_checkpoints"))
    checkpoint_id = store.create_checkpoint(file_path=Path("resume.txt"), original_content="old content")
    # ... file is modified ...
    content = store.rollback(checkpoint_id)  # Returns original_content
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

CHECKPOINT_METADATA_FILE = "checkpoints.json"


@dataclass
class CheckpointInfo:
    """Information about a checkpoint."""
    checkpoint_id: str
    original_path: str
    checkpoint_path: str
    timestamp: float
    file_content: str | None = None  # Optional: store content directly for simplicity


class RollbackStore:
    """Manages checkpoints for agent file operations."""

    def __init__(self, checkpoint_dir: Path | str):
        """Initialize RollbackStore.

        Args:
            checkpoint_dir: Directory to store checkpoint files and metadata
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.metadata_file = self.checkpoint_dir / CHECKPOINT_METADATA_FILE

    def _load_metadata(self) -> dict[str, dict]:
        """Load checkpoint metadata from JSON file."""
        if not self.metadata_file.exists():
            return {}
        try:
            return json.loads(self.metadata_file.read_text())
        except (json.JSONDecodeError, IOError) as e:
            _logger.warning(f"Failed to load checkpoint metadata: {e}")
            return {}

    def _save_metadata(self, metadata: dict[str, dict]) -> None:
        """Save checkpoint metadata to JSON file."""
        try:
            self.metadata_file.write_text(json.dumps(metadata, indent=2))
        except IOError as e:
            _logger.error(f"Failed to save checkpoint metadata: {e}")
            raise

    def create_checkpoint(self, file_path: Path, original_content: str | None = None) -> str:
        """Create a checkpoint before a file modification.

        Args:
            file_path: Path to the file to checkpoint
            original_content: Original file content (if None, reads from file_path)

        Returns:
            Checkpoint ID (timestamp-based)
        """
        checkpoint_id = str(int(time.time() * 1000))
        timestamp = time.time()

        # Get original content if not provided
        if original_content is None:
            if file_path.exists():
                original_content = file_path.read_text(encoding="utf-8")
            else:
                original_content = ""

        # Create checkpoint file
        checkpoint_name = f"{file_path.name}.{checkpoint_id}.bak"
        checkpoint_path = self.checkpoint_dir / checkpoint_name

        # Store content directly in checkpoint file
        checkpoint_path.write_text(original_content, encoding="utf-8")

        # Update metadata
        metadata = self._load_metadata()
        metadata[checkpoint_id] = {
            "checkpoint_id": checkpoint_id,
            "original_path": str(file_path),
            "checkpoint_path": str(checkpoint_path),
            "timestamp": timestamp,
            "file_content": None,  # Content is in the .bak file
        }
        self._save_metadata(metadata)

        _logger.info(f"Created checkpoint {checkpoint_id} for {file_path}")
        return checkpoint_id

    def create_checkpoint_all(self, allowed_dirs: list[Path]) -> str:
        """Create checkpoints for all existing files in allowed directories.

        Since we don't know which files the agent will modify, we create
        a blanket checkpoint of all allowed directory contents before running.

        Args:
            allowed_dirs: List of directories to checkpoint

        Returns:
            Checkpoint ID for the batch operation
        """
        checkpoint_id = str(int(time.time() * 1000))
        timestamp = time.time()
        batch_checkpoints = []

        for allowed_dir in allowed_dirs:
            if not allowed_dir.exists():
                continue
            for file_path in allowed_dir.rglob("*"):
                if file_path.is_file() and not file_path.name.endswith(".bak"):
                    try:
                        cp_id = self.create_checkpoint(file_path)
                        batch_checkpoints.append(cp_id)
                    except Exception as e:
                        _logger.warning(f"Failed to checkpoint {file_path}: {e}")

        _logger.info(f"Created {len(batch_checkpoints)} checkpoints for batch {checkpoint_id}")
        return checkpoint_id

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointInfo | None:
        """Get checkpoint information.

        Args:
            checkpoint_id: ID of the checkpoint

        Returns:
            CheckpointInfo or None if not found
        """
        metadata = self._load_metadata()
        if checkpoint_id not in metadata:
            return None

        info = metadata[checkpoint_id]
        return CheckpointInfo(
            checkpoint_id=info["checkpoint_id"],
            original_path=info["original_path"],
            checkpoint_path=info["checkpoint_path"],
            timestamp=info["timestamp"],
            file_content=info.get("file_content"),
        )

    def rollback(self, checkpoint_id: str) -> str | None:
        """Rollback a file to its checkpoint state.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            The original file content, or None if checkpoint not found

        Raises:
            FileNotFoundError: If checkpoint file does not exist
        """
        metadata = self._load_metadata()
        if checkpoint_id not in metadata:
            _logger.warning(f"Checkpoint {checkpoint_id} not found")
            return None

        info = metadata[checkpoint_id]
        original_path = Path(info["original_path"])
        checkpoint_path = Path(info["checkpoint_path"])

        if not checkpoint_path.exists():
            _logger.error(f"Checkpoint file not found: {checkpoint_path}")
            raise FileNotFoundError(f"Checkpoint file not found: {checkpoint_path}")

        # Read content from checkpoint
        content = checkpoint_path.read_text(encoding="utf-8")

        # Restore file to original path
        original_path.write_text(content, encoding="utf-8")

        _logger.info(f"Rolled back {original_path} to checkpoint {checkpoint_id}")
        return content

    def list_checkpoints(self, original_path: Path | None = None) -> list[CheckpointInfo]:
        """List all checkpoints, optionally filtered by original path.

        Args:
            original_path: If provided, only return checkpoints for this path

        Returns:
            List of CheckpointInfo objects
        """
        metadata = self._load_metadata()
        checkpoints = []

        for cid, info in metadata.items():
            checkpoint = CheckpointInfo(
                checkpoint_id=info["checkpoint_id"],
                original_path=info["original_path"],
                checkpoint_path=info["checkpoint_path"],
                timestamp=info["timestamp"],
                file_content=info.get("file_content"),
            )

            if original_path is None or Path(info["original_path"]) == original_path:
                checkpoints.append(checkpoint)

        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda c: c.timestamp, reverse=True)
        return checkpoints

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to delete

        Returns:
            True if deleted, False if not found
        """
        metadata = self._load_metadata()
        if checkpoint_id not in metadata:
            return False

        info = metadata[checkpoint_id]
        checkpoint_path = Path(info["checkpoint_path"])

        # Delete checkpoint file
        if checkpoint_path.exists():
            checkpoint_path.unlink()

        # Remove from metadata
        del metadata[checkpoint_id]
        self._save_metadata(metadata)

        _logger.info(f"Deleted checkpoint {checkpoint_id}")
        return True

    def get_latest_checkpoint(self, original_path: Path) -> CheckpointInfo | None:
        """Get the most recent checkpoint for a file.

        Args:
            original_path: Path to the original file

        Returns:
            Most recent CheckpointInfo or None
        """
        checkpoints = self.list_checkpoints(original_path)
        return checkpoints[0] if checkpoints else None
