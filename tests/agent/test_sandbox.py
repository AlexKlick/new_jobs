"""Tests for Agent Sandbox - AGNT-02 (directory allowlisting)."""
import pytest


def test_claude_cli_restricted_to_allowed_dirs(temp_project_dir, mock_claude_cli):
    """Claude CLI is invoked with --add-dir restricted to allowed paths."""
    # TODO: implement after agent_runner.py is created
    pass


def test_allowed_dirs_include_applications(temp_project_dir):
    """Allowed directories include applications/{job_id}/."""
    # TODO: implement after agent_runner.py is created
    pass


def test_allowed_dirs_include_facts(temp_project_dir):
    """Allowed directories include facts/."""
    # TODO: implement after agent_runner.py is created
    pass


def test_allowed_dirs_include_skills(temp_project_dir):
    """Allowed directories include skills/."""
    # TODO: implement after agent_runner.py is created
    pass
