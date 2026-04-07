#!/usr/bin/env python3
"""CLI entrypoint for ingesting one job posting into jobs.md."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

AGENT_SDK_ROOT = "/home/alexk/documents/agents_sdk"
if AGENT_SDK_ROOT not in sys.path:
    sys.path.insert(0, AGENT_SDK_ROOT)

from agents_sdk.resume_agent.scrapers import JobScraperFactory, ingest_job_url

WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest one job posting into jobs.md")
    parser.add_argument("--url", required=True, help="Job posting URL to ingest")
    parser.add_argument(
        "--jobs-file",
        default=str(WORKSPACE / "jobs.md"),
        help="Target jobs.md file to append to",
    )
    parser.add_argument(
        "--provider",
        choices=["zai", "minimax"],
        default="zai",
        help="Primary provider for the LLM fallback scraper",
    )
    parser.add_argument(
        "--fallback-provider",
        choices=["zai", "minimax"],
        default="minimax",
        help="Fallback provider for the LLM fallback scraper",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=6,
        help="Maximum turns for the LLM fallback scraper",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    jobs_path = Path(args.jobs_file).expanduser().resolve()
    factory = JobScraperFactory()
    job = await ingest_job_url(
        url=args.url,
        jobs_path=jobs_path,
        factory=factory,
        provider=args.provider,
        fallback_provider=args.fallback_provider,
        max_turns=args.max_turns,
        cwd=WORKSPACE,
    )

    print(f"Added job #{job.index}: {job.company} - {job.role}")
    print(f"jobs.md: {jobs_path}")
    print(f"Apply URL: {job.apply_url or args.url}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
