"""Tests for Search/List runtime settings resolution."""

import os
from pathlib import Path


def test_runtime_settings_autodiscovers_sibling_repos(tmp_path, monkeypatch):
    import runtime_settings as rs

    project_root = tmp_path / "new_job_denjobs"
    project_root.mkdir()
    (tmp_path / "agents_sdk").mkdir()
    (tmp_path / "new_job").mkdir()

    monkeypatch.setattr(rs, "PROJECT_ROOT", project_root)
    monkeypatch.delenv("CANONICAL_INGEST_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_SDK_ROOT", raising=False)
    monkeypatch.delenv("LEGACY_WORKSPACES", raising=False)
    monkeypatch.delenv("CANONICAL_WORKSPACE_ROOT", raising=False)
    rs.reset_runtime_settings_cache()

    settings = rs.get_runtime_settings()

    assert settings.canonical_ingest_provider == "agents_sdk"
    assert settings.canonical_workspace_root == project_root
    assert settings.agent_sdk_root == (tmp_path / "agents_sdk").resolve()
    assert settings.legacy_workspaces == ((tmp_path / "new_job").resolve(),)


def test_runtime_settings_prefers_env_over_autodiscovery(tmp_path, monkeypatch):
    import runtime_settings as rs

    project_root = tmp_path / "new_job_denjobs"
    project_root.mkdir()
    env_sdk = tmp_path / "vendor" / "agents_sdk"
    env_sdk.mkdir(parents=True)
    env_legacy_one = tmp_path / "legacy-one"
    env_legacy_two = tmp_path / "legacy-two"
    env_legacy_one.mkdir()
    env_legacy_two.mkdir()
    env_workspace = tmp_path / "workspace-root"
    env_workspace.mkdir()

    monkeypatch.setattr(rs, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("CANONICAL_INGEST_PROVIDER", "agents_sdk")
    monkeypatch.setenv("AGENT_SDK_ROOT", str(env_sdk))
    monkeypatch.setenv(
        "LEGACY_WORKSPACES",
        f"{env_legacy_one}{os.pathsep}{env_legacy_two}",
    )
    monkeypatch.setenv("CANONICAL_WORKSPACE_ROOT", str(env_workspace))
    rs.reset_runtime_settings_cache()

    settings = rs.get_runtime_settings()

    assert settings.agent_sdk_root == env_sdk.resolve()
    assert settings.legacy_workspaces == (
        env_legacy_one.resolve(),
        env_legacy_two.resolve(),
    )
    assert settings.canonical_workspace_root == env_workspace.resolve()
