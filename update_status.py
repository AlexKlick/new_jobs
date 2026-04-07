#!/usr/bin/env python3
"""Refresh the canonical markdown report for the unified job workspace."""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_SDK_ROOT = "/home/alexk/documents/agents_sdk"
if AGENT_SDK_ROOT not in sys.path:
    sys.path.insert(0, AGENT_SDK_ROOT)

from agents_sdk.resume_agent.unified_workspace import write_application_status_report

WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")
LEGACY_WORKSPACES = [Path("/home/alexk/documents/new_job")]


def generate_markdown() -> Path:
    """Rebuild the canonical markdown report in the active workspace."""

    return write_application_status_report(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)


if __name__ == "__main__":
    output_path = generate_markdown()
    print(f"Updated {output_path}")
