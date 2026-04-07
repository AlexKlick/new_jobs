"""Runtime settings for portable Search/List integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()


@dataclass(frozen=True)
class RuntimeSettings:
    """Runtime configuration resolved from env vars and local workspace layout."""

    canonical_ingest_provider: str
    canonical_workspace_root: Path
    agent_sdk_root: Path | None
    legacy_workspaces: tuple[Path, ...]


def _resolve_path(raw_value: str, *, base_dir: Path) -> Path:
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _split_paths(raw_value: str, *, base_dir: Path) -> tuple[Path, ...]:
    parts = [part.strip() for part in raw_value.split(os.pathsep)]
    resolved: list[Path] = []
    for part in parts:
        if not part:
            continue
        path = _resolve_path(part, base_dir=base_dir)
        if path.exists():
            resolved.append(path)
    return tuple(resolved)


def _discover_agent_sdk_root(project_root: Path) -> Path | None:
    explicit = os.environ.get("AGENT_SDK_ROOT")
    if explicit:
        path = _resolve_path(explicit, base_dir=project_root)
        return path if path.exists() else path

    sibling = (project_root.parent / "agents_sdk").resolve()
    if sibling.exists():
        return sibling
    return None


def _discover_legacy_workspaces(project_root: Path) -> tuple[Path, ...]:
    explicit = os.environ.get("LEGACY_WORKSPACES")
    if explicit is not None:
        return _split_paths(explicit, base_dir=project_root)

    sibling = (project_root.parent / "new_job").resolve()
    if sibling.exists():
        return (sibling,)
    return ()


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    """Resolve Search/List runtime settings once per process."""
    canonical_ingest_provider = os.environ.get("CANONICAL_INGEST_PROVIDER", "agents_sdk").strip() or "agents_sdk"

    workspace_root_raw = os.environ.get("CANONICAL_WORKSPACE_ROOT")
    if workspace_root_raw:
        canonical_workspace_root = _resolve_path(workspace_root_raw, base_dir=PROJECT_ROOT)
    else:
        canonical_workspace_root = PROJECT_ROOT

    return RuntimeSettings(
        canonical_ingest_provider=canonical_ingest_provider,
        canonical_workspace_root=canonical_workspace_root,
        agent_sdk_root=_discover_agent_sdk_root(PROJECT_ROOT),
        legacy_workspaces=_discover_legacy_workspaces(PROJECT_ROOT),
    )


def reset_runtime_settings_cache() -> None:
    """Clear cached settings for tests."""
    get_runtime_settings.cache_clear()
