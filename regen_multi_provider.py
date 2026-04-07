#!/usr/bin/env python3
"""
Multi-provider batch resume generation with MiniMax + Z.AI load balancing.

Runs each job in a SUBPROCESS for true OS-level isolation and timeout.
This prevents the claude_agent_sdk async generator from blocking the event loop.

Features:
  - Each job runs in its own Python subprocess (real OS timeout via SIGKILL)
  - Detects job state: COMPLETE / PARTIAL / MARKDOWN / EMPTY / MISSING
  - Routes jobs to least-loaded provider (round-robin + capacity)
  - Retry on alternate provider after failure
  - Real-time provider slot status display

Usage:
    python3 regen_multi_provider.py [--jobs 5,7,8,...] [--parallel 3] [--timeout 1800]
    python3 regen_multi_provider.py --status   # just show current state
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
AGENTS_SDK_ROOT = "/home/alexk/documents/agents_sdk"
WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")
VENV_PYTHON = Path(AGENTS_SDK_ROOT) / ".venv" / "bin" / "python3"
SINGLE_JOB_RUNNER = WORKSPACE / "run_single_job.py"
LEGACY_WORKSPACES = [Path("/home/alexk/documents/new_job")]
if AGENTS_SDK_ROOT not in sys.path:
    sys.path.insert(0, AGENTS_SDK_ROOT)

from agents_sdk.resume_agent.provider_governor import format_provider_status, load_provider_governor_config


def configured_providers() -> list[tuple[str, int]]:
    config = load_provider_governor_config(WORKSPACE)
    providers = config.get("providers", {})
    policy = str(config.get("scheduler", {}).get("policy") or "throughput_first")
    preferred_order = ["minimax", "zai"] if policy == "throughput_first" else sorted(providers.keys())
    seen: set[str] = set()
    ordered: list[tuple[str, int]] = []
    for name in preferred_order + sorted(providers.keys()):
        if name in seen or name not in providers:
            continue
        seen.add(name)
        ordered.append((name, int(providers[name].get("max_concurrent") or 1)))
    return ordered


# ── Job Status Detection ───────────────────────────────────────────────────────
def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-") or "job"


@dataclass
class JobStatus:
    job_index: int
    company: str
    state: str          # COMPLETE / RESUMABLE / PARTIAL_CL / PARTIAL_RESUME / MARKDOWN / EMPTY / MISSING
    latest_dir: Optional[Path] = None


def _dir_state(path: Path) -> str:
    rp = (path / "resume.pdf").exists()
    cp = (path / "cover_letter.pdf").exists()
    rm = (path / "resume.md").exists()
    cm = (path / "cover_letter.md").exists()
    resumable = any((path / "stream").glob("*.resume.partial.md")) or any(
        (path / "stream").glob("*.cover_letter.partial.md")
    )

    if rp and cp:
        return "COMPLETE"
    if rp:
        return "PARTIAL_RESUME"
    if cp:
        return "PARTIAL_CL"
    if resumable:
        return "RESUMABLE"
    if rm or cm:
        return "MARKDOWN"
    return "EMPTY"


def detect_job_status(job_index: int, company: str) -> JobStatus:
    apps_root = WORKSPACE / "applications" / "all_jobs"
    if apps_root.exists():
        app_dirs = sorted(
            apps_root.glob(f"{job_index:02d}_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if app_dirs:
            app_dir = app_dirs[0]
            return JobStatus(job_index, company, _dir_state(app_dir), app_dir)

    slug = _slug(company)
    outputs = WORKSPACE / "outputs"
    dirs = sorted(
        list(outputs.glob(f"*_{job_index:02d}_{slug}")) +
        list(outputs.glob(f"*_{job_index}_{slug}")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        return JobStatus(job_index, company, "MISSING")

    d = dirs[0]
    return JobStatus(job_index, company, _dir_state(d), d)


# ── Provider Pool ──────────────────────────────────────────────────────────────
@dataclass
class ProviderSlot:
    name: str
    capacity: int
    active: int = 0
    failures: int = 0
    last_failure: float = 0.0

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.active)

    @property
    def cooldown_remaining(self) -> float:
        if self.failures == 0:
            return 0.0
        cooldown = min(90.0, 15.0 * self.failures)
        return max(0.0, cooldown - (time.monotonic() - self.last_failure))

    def status_str(self) -> str:
        cd = f" ⏳{self.cooldown_remaining:.0f}s" if self.cooldown_remaining > 0 else ""
        fx = f" ✗{self.failures}" if self.failures > 0 else ""
        return f"  [{self.name:8s}] {self.active}/{self.capacity}{fx}{cd}"


class ProviderPool:
    def __init__(self, providers: list[tuple[str, int]]):
        self.slots = {n: ProviderSlot(n, c) for n, c in providers}
        self._lock = asyncio.Lock()

    def print_status(self):
        print("─── Provider Status ───", flush=True)
        for s in self.slots.values():
            print(s.status_str(), flush=True)
        print("", flush=True)
        print(format_provider_status(WORKSPACE), flush=True)
        print("──────────────────────", flush=True)

    async def acquire(self) -> Optional[ProviderSlot]:
        async with self._lock:
            opts = [s for s in self.slots.values()
                    if s.available > 0 and s.cooldown_remaining == 0]
            if not opts:
                return None
            for preferred in ["minimax", "zai"]:
                for slot in opts:
                    if slot.name == preferred:
                        slot.active += 1
                        return slot
            chosen = min(opts, key=lambda s: s.active / s.capacity)
            chosen.active += 1
            return chosen

    async def release(self, slot: ProviderSlot, success: bool):
        async with self._lock:
            slot.active = max(0, slot.active - 1)
            if success:
                slot.failures = 0
            else:
                slot.failures += 1
                slot.last_failure = time.monotonic()

    async def wait_for_slot(self, timeout_s: float = 300.0) -> Optional[ProviderSlot]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sl = await self.acquire()
            if sl:
                return sl
            await asyncio.sleep(5.0)
        return None


# ── Subprocess Runner ──────────────────────────────────────────────────────────
@dataclass
class JobResult:
    job_index: int
    company: str
    provider: str
    success: bool
    elapsed: float
    error: str = ""
    retried: bool = False


def _refresh_unified_status(job_index: int | None = None) -> None:
    """Refresh the canonical catalog and markdown report during active batch runs."""

    if AGENTS_SDK_ROOT not in sys.path:
        sys.path.insert(0, AGENTS_SDK_ROOT)
    from agents_sdk.resume_agent.unified_workspace import consolidate_workspace

    job_indices = {job_index} if job_index is not None else None
    consolidate_workspace(
        WORKSPACE,
        extra_workspaces=LEGACY_WORKSPACES,
        write_jobs=False,
        write_report=True,
        job_indices=job_indices,
    )


async def run_job_subprocess(
    job_index: int, provider: str, timeout_s: float
) -> tuple[bool, str]:
    """
    Launch run_single_job.py in a separate process.
    Uses asyncio.create_subprocess_exec → real OS process, real SIGKILL on timeout.
    Output is streamed to a temp log file and tail-printed on failure.
    """
    log_path = Path(f"/tmp/job_{job_index}_{provider}_{int(time.time())}.log")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PYTHON), str(SINGLE_JOB_RUNNER),
            str(job_index), provider,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except Exception as exc:
        return False, f"Failed to start subprocess: {exc}"

    output_lines: list[str] = []
    try:
        async def _read_output():
            assert proc.stdout is not None
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                output_lines.append(decoded)

        await asyncio.wait_for(
            asyncio.gather(proc.wait(), _read_output()),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except Exception:
            pass
        tail = "\n".join(output_lines[-10:])
        return False, f"Timed out after {timeout_s:.0f}s. Last output:\n{tail}"
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return False, f"Subprocess error: {exc}"

    returncode = proc.returncode or 0
    success = returncode == 0
    if not success:
        tail = "\n".join(output_lines[-10:])
        return False, f"Exit code {returncode}. Output:\n{tail}"
    return True, ""


async def process_job(
    job_index: int,
    company: str,
    pool: ProviderPool,
    semaphore: asyncio.Semaphore,
    timeout_s: float,
    retry: bool,
) -> JobResult:
    async with semaphore:
        start = time.monotonic()

        slot = await pool.wait_for_slot(300.0)
        if slot is None:
            return JobResult(job_index, company, "none", False,
                             time.monotonic() - start, "No slot available after 5 min")

        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] ▶ Job {job_index:2d} ({company}) on [{slot.name}]", flush=True)

        success, error = await run_job_subprocess(job_index, slot.name, timeout_s)
        await pool.release(slot, success)
        provider_used = slot.name

        if not success and retry:
            alt = await pool.wait_for_slot(120.0)
            if alt is not None:
                ts2 = datetime.now().strftime("%H:%M:%S")
                err_short = error.splitlines()[0][:80] if error else ""
                print(f"  [{ts2}] ↺ Retry Job {job_index:2d} on [{alt.name}] (was: {err_short})", flush=True)
                success, error = await run_job_subprocess(job_index, alt.name, timeout_s)
                await pool.release(alt, success)
                provider_used = alt.name

        elapsed = time.monotonic() - start
        ts_done = datetime.now().strftime("%H:%M:%S")
        icon = "✓" if success else "✗"
        err_short = error.splitlines()[0][:100] if error and not success else ""
        try:
            _refresh_unified_status(job_index)
        except Exception as exc:
            warn_ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{warn_ts}] ! Status refresh failed for job {job_index:2d}: {exc}", flush=True)
        print(f"  [{ts_done}] {icon} Job {job_index:2d} ({company}) [{provider_used}] {elapsed:.0f}s"
              + (f"\n      ↳ {err_short}" if err_short else ""), flush=True)

        return JobResult(job_index, company, provider_used, success, elapsed, error)


# ── Status Printer Task ────────────────────────────────────────────────────────
async def _status_loop(pool: ProviderPool, stop: asyncio.Event, interval: float = 45.0):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if not stop.is_set():
            pool.print_status()


# ── Entrypoint ─────────────────────────────────────────────────────────────────
async def main(argv=None):
    ap = argparse.ArgumentParser(description="Multi-provider batch resume generation")
    ap.add_argument("--jobs",     default="",  help="Comma-separated job indices (default: all)")
    ap.add_argument("--parallel", type=int, default=3, help="Max concurrent jobs (default: 3)")
    ap.add_argument("--timeout",  type=float, default=1800.0, help="Per-job timeout seconds (default: 1800)")
    ap.add_argument("--no-retry", action="store_true", help="Disable retry on alternate provider")
    ap.add_argument("--force",    action="store_true", help="Re-run COMPLETE jobs too")
    ap.add_argument("--status",   action="store_true", help="Print status for all jobs and exit")
    args = ap.parse_args(argv)

    # Read jobs.md
    sys.path.insert(0, AGENTS_SDK_ROOT)
    from agents_sdk.resume_agent.jobs_parser import parse_jobs_markdown
    all_jobs = parse_jobs_markdown(WORKSPACE / "jobs.md")
    job_map = {j.index: j for j in all_jobs}

    requested = sorted(job_map.keys())
    if args.jobs:
        requested = [int(x.strip()) for x in args.jobs.split(",") if x.strip()]

    # Detect states
    print(f"\n{'='*60}", flush=True)
    providers = configured_providers()
    print(f" Job Application Batch — Providers: {', '.join(p[0] for p in providers)}", flush=True)
    print(f"{'='*60}", flush=True)

    statuses: list[JobStatus] = []
    for idx in requested:
        if idx not in job_map:
            print(f"  WARNING: job {idx} not in jobs.md", flush=True)
            continue
        statuses.append(detect_job_status(idx, job_map[idx].company))

    counts = Counter(s.state for s in statuses)
    print(f"\n Status Summary ({len(statuses)} jobs):", flush=True)
    for st, n in sorted(counts.items()):
        print(f"   {st:16s} {n}", flush=True)

    if args.status:
        print("")
        print(format_provider_status(WORKSPACE), flush=True)
        print(f"\n{'─'*60}", flush=True)
        for s in sorted(statuses, key=lambda x: x.job_index):
            icon = {
                "COMPLETE": "✓",
                "RESUMABLE": "↺",
                "PARTIAL_RESUME": "◑",
                "PARTIAL_CL": "◐",
                "MARKDOWN": "~",
                "EMPTY": "○",
                "MISSING": "✗",
            }.get(s.state, "?")
            d = s.latest_dir.name if s.latest_dir else "—"
            print(f"  {icon} {s.job_index:2d}: {s.state:16s} {s.company}  ({d})", flush=True)
        sys.exit(0)

    to_run = [s for s in statuses if s.state != "COMPLETE" or args.force]
    if not to_run:
        print(f"\n All {len(statuses)} jobs COMPLETE. Use --force to re-run.\n", flush=True)
        sys.exit(0)

    print(f"\n Will run {len(to_run)} jobs | parallel={args.parallel} | timeout={args.timeout:.0f}s | retry={not args.no_retry}", flush=True)

    priority = {
        "RESUMABLE": 0,
        "PARTIAL_RESUME": 1,
        "PARTIAL_CL": 2,
        "MARKDOWN": 3,
        "EMPTY": 4,
        "MISSING": 5,
        "COMPLETE": 6,
    }
    to_run.sort(key=lambda status: (priority.get(status.state, 99), status.job_index))

    pool = ProviderPool(providers)
    pool.print_status()

    sem = asyncio.Semaphore(args.parallel)
    stop_ev = asyncio.Event()
    printer = asyncio.create_task(_status_loop(pool, stop_ev))

    print(f"\n{'─'*60}", flush=True)
    print(f" Batch started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"{'─'*60}\n", flush=True)

    coros = [
        process_job(s.job_index, s.company, pool, sem, args.timeout, not args.no_retry)
        for s in to_run
    ]
    raw = await asyncio.gather(*coros)
    results: list[JobResult] = list(raw)

    stop_ev.set()
    try:
        await asyncio.wait_for(printer, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    succeeded = [r for r in results if r.success]
    failed    = [r for r in results if not r.success]

    print(f"\n{'='*60}", flush=True)
    print(f" Batch done: {len(succeeded)}/{len(results)} succeeded", flush=True)
    print(f"{'='*60}\n", flush=True)

    for r in sorted(succeeded, key=lambda r: r.job_index):
        print(f"  ✓ {r.job_index:2d}: {r.company} [{r.provider}] {r.elapsed:.0f}s", flush=True)

    if failed:
        print("\n  Failures:", flush=True)
        for r in sorted(failed, key=lambda r: r.job_index):
            err = r.error.splitlines()[0][:120] if r.error else ""
            print(f"  ✗ {r.job_index:2d}: {r.company} [{r.provider}] — {err}", flush=True)

    try:
        _refresh_unified_status()
    except Exception as exc:
        print(f"\n  WARN: final status refresh failed: {exc}", flush=True)

    # Final status sweep
    print(f"\n{'─'*60}\n Final Status:\n{'─'*60}", flush=True)
    complete = 0
    for idx in sorted(job_map.keys()):
        st = detect_job_status(idx, job_map[idx].company)
        if st.state == "COMPLETE":
            complete += 1
        else:
            icon = {
                "RESUMABLE": "↺",
                "PARTIAL_RESUME": "◑",
                "PARTIAL_CL": "◐",
                "MARKDOWN": "~",
                "EMPTY": "○",
                "MISSING": "✗",
            }.get(st.state, "?")
            print(f"  {icon} {idx:2d}: {st.state:16s} {st.company}", flush=True)
    print(f"\n  COMPLETE: {complete}/{len(job_map)}\n{'='*60}\n", flush=True)

    return len(failed) == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
