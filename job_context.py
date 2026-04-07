"""
Job Context Module

Provides retrieval of resume.md and cover_letter.md content for job applications.

Usage:
    context = get_job_context(5)  # Returns {"resume": "...", "cover_letter": "..."}
    bundle = get_bundle_dir(5)     # Returns Path to bundle dir or None
    jobs = get_job_list()         # Returns [(0, "job_name"), ...]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.resolve()
APPLICATIONS_DIR = PROJECT_ROOT / "applications" / "all_jobs"


def get_bundle_dir(index: int) -> Optional[Path]:
    """Find the bundle directory for a job index.

    Args:
        index: Job index (e.g., 5 for "05_...")

    Returns:
        Path to bundle directory or None if not found
    """
    if not APPLICATIONS_DIR.exists():
        _logger.warning(f"Applications directory not found: {APPLICATIONS_DIR}")
        return None

    # Match directory names like "05_remesh__..." for index 5
    prefix = f"{index:02d}_"
    for entry in APPLICATIONS_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith(prefix):
            return entry

    _logger.debug(f"No bundle found for index {index} (prefix: {prefix})")
    return None


def get_job_context(index: int) -> dict[str, str]:
    """Get job context (resume.md and cover_letter.md content).

    Args:
        index: Job index

    Returns:
        dict with "resume" and "cover_letter" keys containing file content.
        Returns empty strings for missing files.
    """
    result: dict[str, str] = {"resume": "", "cover_letter": ""}

    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        _logger.warning(f"No bundle directory for job index {index}")
        return result

    # Load resume.md
    resume_path = bundle_dir / "resume.md"
    if resume_path.exists():
        try:
            result["resume"] = resume_path.read_text(encoding="utf-8")
        except Exception as exc:
            _logger.warning(f"Could not read resume.md for index {index}: {exc}")

    # Load cover_letter.md
    cover_path = bundle_dir / "cover_letter.md"
    if cover_path.exists():
        try:
            result["cover_letter"] = cover_path.read_text(encoding="utf-8")
        except Exception as exc:
            _logger.warning(f"Could not read cover_letter.md for index {index}: {exc}")

    return result


def get_job_list() -> list[tuple[int, str]]:
    """Get all job indices with their display names.

    Returns:
        List of (index, display_name) tuples sorted by index
    """
    if not APPLICATIONS_DIR.exists():
        _logger.warning(f"Applications directory not found: {APPLICATIONS_DIR}")
        return []

    jobs: list[tuple[int, str]] = []
    for entry in APPLICATIONS_DIR.iterdir():
        if not entry.is_dir():
            continue

        # Parse index from directory name (e.g., "05_remesh__software_engineer_ai-first")
        name = entry.name
        if name and name[0].isdigit():
            try:
                # Extract first two digits as index
                index = int(name[:2])
                # Use full directory name as display name
                display_name = name[3:] if len(name) > 3 else name  # Remove "XX_" prefix
                jobs.append((index, display_name))
            except ValueError:
                continue

    jobs.sort(key=lambda x: x[0])
    return jobs


def get_job_name(index: int) -> str:
    """Get the display name for a job index.

    Args:
        index: Job index

    Returns:
        Display name string or empty string if not found
    """
    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        return ""

    name = bundle_dir.name
    # Remove "XX_" prefix if present
    if len(name) > 3 and name[2] == "_":
        return name[3:]
    return name
