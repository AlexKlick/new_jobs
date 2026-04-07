#!/usr/bin/env python3
"""Unified end-to-end job pipeline for the canonical workspace."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

AGENT_SDK_ROOT = "/home/alexk/documents/agents_sdk"
if AGENT_SDK_ROOT not in sys.path:
    sys.path.insert(0, AGENT_SDK_ROOT)

from agents_sdk.resume_agent.scrapers import JobScraperFactory, ingest_job_url
from agents_sdk.resume_agent.provider_governor import format_provider_status
from agents_sdk.resume_agent.unified_workspace import (
    build_canonical_jobs,
    consolidate_workspace,
    pending_job_indices,
    write_application_status_report,
)

WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")
LEGACY_WORKSPACES = [Path("/home/alexk/documents/new_job")]
VENV_PYTHON = Path(AGENT_SDK_ROOT) / ".venv" / "bin" / "python3"
REGEN_SCRIPT = WORKSPACE / "regen_multi_provider.py"


def _parse_job_csv(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _run_regen(indices: list[int], *, parallel: int, timeout: int) -> int:
    if not indices:
        print("No matching jobs to generate.")
        return 0

    cmd = [
        str(VENV_PYTHON),
        str(REGEN_SCRIPT),
        "--jobs",
        ",".join(str(item) for item in indices),
        "--parallel",
        str(parallel),
        "--timeout",
        str(timeout),
    ]
    return subprocess.run(cmd, cwd=str(WORKSPACE), check=False).returncode


async def _ingest(args: argparse.Namespace) -> int:
    job = await ingest_job_url(
        url=args.url,
        jobs_path=WORKSPACE / "jobs.md",
        factory=JobScraperFactory(),
        provider=args.provider,
        fallback_provider=args.fallback_provider,
        max_turns=args.max_turns,
        cwd=WORKSPACE,
    )
    consolidate_workspace(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES, write_jobs=True, write_report=True)
    print(f"Added canonical job #{job.index}: {job.company} - {job.role}")
    return 0


def _consolidate(_: argparse.Namespace) -> int:
    records = consolidate_workspace(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES, write_jobs=True, write_report=True)
    print(f"Consolidated {len(records)} canonical jobs into {WORKSPACE}")
    return 0


def _report(_: argparse.Namespace) -> int:
    output_path = write_application_status_report(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)
    print(f"Wrote {output_path}")
    return 0


def _provider_status(_: argparse.Namespace) -> int:
    print(format_provider_status(WORKSPACE))
    return 0


def _generate(args: argparse.Namespace) -> int:
    if args.all:
        indices = [record.canonical_index for record in build_canonical_jobs(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)]
    elif args.job is not None:
        indices = [int(args.job)]
    elif args.jobs:
        indices = _parse_job_csv(args.jobs)
    else:
        indices = pending_job_indices(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)

    code = _run_regen(indices, parallel=args.parallel, timeout=args.timeout)
    write_application_status_report(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)
    return code


async def _run(args: argparse.Namespace) -> int:
    job = await ingest_job_url(
        url=args.url,
        jobs_path=WORKSPACE / "jobs.md",
        factory=JobScraperFactory(),
        provider=args.provider,
        fallback_provider=args.fallback_provider,
        max_turns=args.max_turns,
        cwd=WORKSPACE,
    )
    consolidate_workspace(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES, write_jobs=True, write_report=True)
    code = _run_regen([job.index], parallel=args.parallel, timeout=args.timeout)
    write_application_status_report(WORKSPACE, extra_workspaces=LEGACY_WORKSPACES)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified job pipeline for new_job_denjobs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Scrape and add one job URL to the canonical jobs corpus")
    ingest_parser.add_argument("--url", required=True)
    ingest_parser.add_argument("--provider", choices=["zai", "minimax"], default="zai")
    ingest_parser.add_argument("--fallback-provider", choices=["zai", "minimax"], default="minimax")
    ingest_parser.add_argument("--max-turns", type=int, default=6)

    subparsers.add_parser("consolidate", help="Merge jobs and deduplicate application bundles")
    subparsers.add_parser("report", help="Refresh the unified markdown status report")
    subparsers.add_parser("provider-status", help="Show shared provider-governor state")

    generate_parser = subparsers.add_parser("generate", help="Run resume generation for canonical jobs")
    generate_group = generate_parser.add_mutually_exclusive_group()
    generate_group.add_argument("--job", type=int)
    generate_group.add_argument("--jobs")
    generate_group.add_argument("--all", action="store_true")
    generate_parser.add_argument("--parallel", type=int, default=3)
    generate_parser.add_argument("--timeout", type=int, default=1800)

    run_parser = subparsers.add_parser("run", help="Ingest one URL, generate its bundle, and refresh the report")
    run_parser.add_argument("--url", required=True)
    run_parser.add_argument("--provider", choices=["zai", "minimax"], default="zai")
    run_parser.add_argument("--fallback-provider", choices=["zai", "minimax"], default="minimax")
    run_parser.add_argument("--max-turns", type=int, default=6)
    run_parser.add_argument("--parallel", type=int, default=1)
    run_parser.add_argument("--timeout", type=int, default=1800)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "ingest":
        return asyncio.run(_ingest(args))
    if args.command == "consolidate":
        return _consolidate(args)
    if args.command == "report":
        return _report(args)
    if args.command == "provider-status":
        return _provider_status(args)
    if args.command == "generate":
        return _generate(args)
    if args.command == "run":
        return asyncio.run(_run(args))
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
