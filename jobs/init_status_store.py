#!/usr/bin/env python3
"""
Initialize or migrate the job_posting_status.json file.

This script:
1. Creates the status file if it doesn't exist
2. Adds new jobs from manifest that aren't in the status file yet
3. Preserves existing status data

Run: python init_status_store.py [--force]
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from jobs import job_status_checker as jsc

MANIFEST_PATH = PROJECT_ROOT / "jobs_manifest.json"
STATUS_FILE = PROJECT_ROOT / "job_posting_status.json"


def load_jobs_manifest() -> list[dict]:
    """Load jobs from manifest file."""
    if not MANIFEST_PATH.exists():
        print(f"ERROR: Manifest file not found: {MANIFEST_PATH}")
        sys.exit(1)

    with open(MANIFEST_PATH, 'r') as f:
        data = json.load(f)
    return data.get('jobs', [])


def load_status_store() -> dict[int, dict]:
    """Load cached status from file."""
    if not STATUS_FILE.exists():
        return {}

    try:
        with open(STATUS_FILE, 'r') as f:
            data = json.load(f)
        return {entry['index']: entry for entry in data.get('statuses', [])}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load status store: {e}")
        return {}


def save_status_store(statuses: list[dict]) -> None:
    """Save status to file atomically."""
    data = {
        'updated_at': datetime.utcnow().isoformat() + 'Z',
        'updated_by': 'init_status_store.py',
        'statuses': statuses,
    }
    tmp_path = STATUS_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    tmp_path.rename(STATUS_FILE)
    print(f"Saved {len(statuses)} statuses to {STATUS_FILE}")


def get_all_jobs() -> list[tuple[int, str]]:
    """Get all (index, url) pairs from manifest."""
    jobs = load_jobs_manifest()
    result = []
    for job_entry in jobs:
        canonical_index = job_entry.get('canonical_index')
        job_data = job_entry.get('job', {})
        url = job_data.get('apply_url') or job_data.get('apply')
        if canonical_index and url:
            result.append((canonical_index, url))
    return result


def initialize_status_file(force: bool = False) -> None:
    """
    Initialize or migrate the status file.
    - Creates new entries for jobs not yet in the status store
    - Marks them as UNKNOWN with a note about not yet checked
    """
    jobs = get_all_jobs()
    print(f"Found {len(jobs)} jobs in manifest")

    existing_store = load_status_store()
    print(f"Found {len(existing_store)} existing status entries")

    # Merge: start with existing, add new jobs as UNKNOWN
    merged: dict[int, dict] = dict(existing_store)
    new_entries = 0

    for index, url in jobs:
        if index not in merged:
            source = jsc.detect_job_board(url)
            merged[index] = {
                'index': index,
                'url': url,
                'status': 'UNKNOWN',
                'lastChecked': None,
                'error': 'Not yet checked',
                'source': source,
                'httpStatusCode': None,
                'responseTimeMs': None,
            }
            new_entries += 1

    if new_entries > 0:
        print(f"Adding {new_entries} new entries as UNKNOWN")
    else:
        print("No new entries needed")

    # Sort by index for consistent output
    sorted_statuses = sorted(merged.values(), key=lambda x: x['index'])
    save_status_store(sorted_statuses)

    print(f"\nMigration complete!")
    print(f"  Total jobs: {len(jobs)}")
    print(f"  Existing entries: {len(existing_store)}")
    print(f"  New entries: {new_entries}")
    print(f"  Total in store: {len(merged)}")


def main():
    parser = argparse.ArgumentParser(description='Initialize job status store')
    parser.add_argument('--force', action='store_true', help='Force re-initialization')
    args = parser.parse_args()

    if STATUS_FILE.exists() and not args.force:
        print(f"Status file already exists: {STATUS_FILE}")
        print("Use --force to re-initialize")
        print("\nTo add new jobs from manifest, run without --force:")
        initialize_status_file(force=False)
    else:
        initialize_status_file(force=args.force)


if __name__ == '__main__':
    main()
