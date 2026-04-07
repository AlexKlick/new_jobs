"""Tests for AgentRunner - AGNT-01 (natural language file operations)."""
import pytest
from pathlib import Path


def test_agent_runner_initialization(temp_project_dir, mock_checkpoint_dir):
    """AgentRunner initializes with allowed directories."""
    # TODO: implement after agent_runner.py is created
    pass


def test_agent_runner_runs_claude_cli(temp_project_dir, mock_checkpoint_dir, mock_claude_cli):
    """AgentRunner executes claude CLI subprocess with instruction."""
    # TODO: implement after agent_runner.py is created
    pass


def test_agent_runner_returns_response(temp_project_dir, mock_checkpoint_dir, mock_claude_cli):
    """AgentRunner returns Claude CLI stdout as response."""
    # TODO: implement after agent_runner.py is created
    pass


def test_agent_runner_handles_error(temp_project_dir, mock_checkpoint_dir, mock_claude_cli):
    """AgentRunner raises on non-zero return code."""
    # TODO: implement after agent_runner.py is created
    pass
