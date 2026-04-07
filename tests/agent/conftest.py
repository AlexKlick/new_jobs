"""Shared fixtures for agent tests."""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory with allowed subdirs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        # Create allowed directories per AGNT-02
        (base / "applications").mkdir()
        (base / "applications" / "job_01").mkdir()
        (base / "facts").mkdir()
        (base / "skills").mkdir()
        yield base


@pytest.fixture
def mock_claude_cli(monkeypatch):
    """Mock subprocess.run for claude CLI calls."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Claude agent response"
    mock_result.stderr = ""

    def mock_run(cmd, **kwargs):
        return mock_result

    import subprocess
    monkeypatch.setattr(subprocess, "run", mock_run)
    return mock_result


@pytest.fixture
def mock_checkpoint_dir(temp_project_dir):
    """Create a temporary checkpoint directory."""
    checkpoint = temp_project_dir / ".agent_checkpoints"
    checkpoint.mkdir(exist_ok=True)
    return checkpoint
