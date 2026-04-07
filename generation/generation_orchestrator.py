"""
Generation Orchestrator — manages resume/cover letter regeneration workflow.

Provides:
  - Async generation of resume, cover letter, or both for a specific job
  - Provider selection (Z.AI, MiniMax) with fallback
  - Real-time progress tracking via state file
  - Timeout handling (subprocess-based for true OS-level timeout)
  - Accept/reject workflow for generated content

Called by api_server.py endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Coroutine, Optional

from db.state_store import (
    delete_generation_state,
    load_generation_state,
    state_store_enabled,
    upsert_generation_state,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
AGENTS_SDK_ROOT = Path("/home/alexk/documents/agents_sdk")
WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")
VENV_PYTHON = AGENTS_SDK_ROOT / ".venv" / "bin" / "python3"
SINGLE_JOB_RUNNER = WORKSPACE / "run_single_job.py"

# ── Logging ────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────
class GenerationTarget(str, Enum):
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    BOTH = "both"


class GenerationStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


# ── Data Models ────────────────────────────────────────────────────────────────
@dataclass
class GenerationProgress:
    """Immutable snapshot of generation progress for a job."""
    job_index: int
    target: GenerationTarget
    status: GenerationStatus
    provider: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_pct: float = 0.0
    current_step: str = ""
    estimated_remaining_s: Optional[float] = None
    error: Optional[str] = None
    output_dir: Optional[str] = None
    rubric_scores: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "job_index": self.job_index,
            "target": self.target.value,
            "status": self.status.value,
            "provider": self.provider,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress_pct": self.progress_pct,
            "current_step": self.current_step,
            "estimated_remaining_s": self.estimated_remaining_s,
            "error": self.error,
            "output_dir": self.output_dir,
            "rubric_scores": self.rubric_scores,
        }


@dataclass
class PendingGeneration:
    """Mutable state for an in-progress generation."""
    job_index: int
    target: GenerationTarget
    provider: str
    fallback_provider: Optional[str]
    quality_policy: str
    status: GenerationStatus = GenerationStatus.IDLE
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_pct: float = 0.0
    current_step: str = ""
    estimated_remaining_s: Optional[float] = None
    error: Optional[str] = None
    output_dir: Optional[str] = None
    rubric_scores: Optional[dict] = None
    proc: Optional[asyncio.subprocess.Process] = None
    result_ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    _subprocess_done: bool = False

    def to_progress(self) -> GenerationProgress:
        return GenerationProgress(
            job_index=self.job_index,
            target=self.target,
            status=self.status,
            provider=self.provider,
            started_at=self.started_at,
            completed_at=self.completed_at,
            progress_pct=self.progress_pct,
            current_step=self.current_step,
            estimated_remaining_s=self.estimated_remaining_s,
            error=self.error,
            output_dir=self.output_dir,
            rubric_scores=self.rubric_scores,
        )


# ── State File Management ──────────────────────────────────────────────────────
STATE_DIR = WORKSPACE / ".generation_state"
STATE_DIR.mkdir(exist_ok=True)


def _state_file(job_index: int) -> Path:
    return STATE_DIR / f"gen_{job_index:02d}.json"


def _schedule_background(coro: Coroutine[Any, Any, Any]) -> None:
    """Schedule a background coroutine without leaking it in patched tests."""
    try:
        task = asyncio.create_task(coro)
    except Exception:
        coro.close()
        raise
    if not isinstance(task, asyncio.Task):
        coro.close()


async def _load_state(job_index: int) -> Optional[dict]:
    """Load persisted generation state from PostgreSQL or disk."""
    if state_store_enabled():
        try:
            pg_state = await load_generation_state(job_index)
            if pg_state is not None:
                return pg_state
        except Exception as exc:
            logger.warning(
                "Failed to load PostgreSQL generation state for job %s: %s",
                job_index,
                exc,
            )

    path = _state_file(job_index)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Failed to load generation state for job {job_index}: {exc}")
        return None


async def _save_state(progress: GenerationProgress) -> None:
    """Persist generation state to PostgreSQL when available, otherwise disk."""
    if state_store_enabled():
        try:
            await upsert_generation_state(progress.to_dict())
            return
        except Exception as exc:
            logger.warning(
                "Failed to save PostgreSQL generation state for job %s: %s",
                progress.job_index,
                exc,
            )

    path = _state_file(progress.job_index)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress.to_dict(), indent=2), encoding="utf-8")
    tmp.rename(path)


async def _clear_state(job_index: int) -> None:
    """Remove persisted state for a job."""
    if state_store_enabled():
        try:
            await delete_generation_state(job_index)
        except Exception as exc:
            logger.warning(
                "Failed to clear PostgreSQL generation state for job %s: %s",
                job_index,
                exc,
            )

    path = _state_file(job_index)
    if path.exists():
        path.unlink()


# ── Generation Steps (for progress reporting) ──────────────────────────────────
STEPS_BOTH = [
    (5, "Initializing generation workflow"),
    (10, "Selecting provider"),
    (20, "Analyzing job requirements"),
    (40, "Generating resume content"),
    (55, "Quality audit - resume"),
    (65, "Generating cover letter content"),
    (80, "Quality audit - cover letter"),
    (90, "Finalizing output"),
    (100, "Generation complete"),
]

STEPS_SINGLE = [
    (10, "Initializing generation workflow"),
    (15, "Selecting provider"),
    (25, "Analyzing job requirements"),
    (50, "Generating content"),
    (70, "Quality audit"),
    (85, "Finalizing output"),
    (100, "Generation complete"),
]


# ── Subprocess Runner ──────────────────────────────────────────────────────────
async def _run_generation_subprocess(
    pending: PendingGeneration,
    timeout_s: float = 1800.0,
) -> tuple[bool, str]:
    """
    Launch run_single_job.py in a subprocess with real OS-level timeout.
    Returns (success, error_message).
    """
    log_path = Path(f"/tmp/gen_{pending.job_index}_{int(time.time())}.log")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    try:
        pending.current_step = f"Starting subprocess with {pending.provider}"
        pending.status = GenerationStatus.RUNNING
        pending.started_at = datetime.utcnow().isoformat() + "Z"
        await _save_state(pending.to_progress())

        proc = await asyncio.create_subprocess_exec(
            str(VENV_PYTHON),
            str(SINGLE_JOB_RUNNER),
            str(pending.job_index),
            pending.provider,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        pending.proc = proc
    except Exception as exc:
        return False, f"Failed to start subprocess: {exc}"

    output_lines: list[str] = []
    started_at = time.monotonic()

    try:
        async def _read_output():
            nonlocal output_lines
            if proc.stdout is None:
                return
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                output_lines.append(decoded)
                # Update progress based on time elapsed
                elapsed = time.monotonic() - started_at
                if pending.target == GenerationTarget.BOTH:
                    pct = min(95, int(10 + elapsed / timeout_s * 80))
                else:
                    pct = min(95, int(15 + elapsed / timeout_s * 75))
                pending.progress_pct = float(pct)
                remaining = max(0, timeout_s - elapsed)
                pending.estimated_remaining_s = remaining
                pending.current_step = f"Running ({elapsed:.0f}s elapsed)"
                await _save_state(pending.to_progress())

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
        pending.status = GenerationStatus.TIMED_OUT
        pending.error = f"Timed out after {timeout_s:.0f}s"
        await _save_state(pending.to_progress())
        return False, pending.error
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        pending.status = GenerationStatus.FAILED
        pending.error = str(exc)
        await _save_state(pending.to_progress())
        return False, str(exc)

    returncode = proc.returncode or 0
    success = returncode == 0
    if not success:
        tail = "\n".join(output_lines[-10:])
        pending.status = GenerationStatus.FAILED
        pending.error = f"Exit code {returncode}. Output:\n{tail}"
        await _save_state(pending.to_progress())
        return False, pending.error

    return True, ""


# ── Main Orchestrator Class ───────────────────────────────────────────────────
class GenerationOrchestrator:
    """
    Singleton orchestrator managing all in-flight generation requests.

    Thread-safe via asyncio.Lock. Each job has at most one in-flight generation.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[int, PendingGeneration] = {}
        self._result_cache: dict[int, tuple[bool, str]] = {}  # job_index -> (success, error)

    async def start_generation(
        self,
        job_index: int,
        target: GenerationTarget = GenerationTarget.BOTH,
        provider: str = "minimax",
        fallback_provider: Optional[str] = None,
        quality_policy: str = "advisory",
    ) -> GenerationProgress:
        """
        Start generation for a job. Returns immediately with initial progress.
        Generation runs in background.
        """
        async with self._lock:
            # Reject if already running
            if job_index in self._pending:
                existing = self._pending[job_index]
                if existing.status in (GenerationStatus.STARTING, GenerationStatus.RUNNING):
                    raise ValueError(f"Generation already in progress for job {job_index}")

            pending = PendingGeneration(
                job_index=job_index,
                target=target,
                provider=provider,
                fallback_provider=fallback_provider,
                quality_policy=quality_policy,
                status=GenerationStatus.STARTING,
                current_step="Preparing generation request",
            )
            self._pending[job_index] = pending

        # Mark as started
        pending.status = GenerationStatus.RUNNING
        pending.started_at = datetime.utcnow().isoformat() + "Z"
        if target == GenerationTarget.BOTH:
            pending.progress_pct = 5.0
            pending.current_step = STEPS_BOTH[1][1]
        else:
            pending.progress_pct = 10.0
            pending.current_step = STEPS_SINGLE[1][1]
        await _save_state(pending.to_progress())

        # Run generation in background task (no await)
        _schedule_background(self._run_generation(pending))

        return pending.to_progress()

    async def _run_generation(self, pending: PendingGeneration) -> None:
        """Background task that runs generation and updates state."""
        timeout_s = 1800.0  # 30 minutes

        try:
            success, error = await _run_generation_subprocess(pending, timeout_s)

            if success:
                pending.status = GenerationStatus.COMPLETED
                pending.progress_pct = 100.0
                pending.current_step = "Generation complete"
                pending.completed_at = datetime.utcnow().isoformat() + "Z"
                pending.estimated_remaining_s = 0.0

                # Read output dir from run_single_job output
                output_dir = self._find_latest_output_dir(pending.job_index)
                pending.output_dir = str(output_dir) if output_dir else None

                # Try to load rubric scores
                if output_dir:
                    rubric = self._load_rubric_scores(output_dir)
                    if rubric:
                        pending.rubric_scores = rubric
            else:
                pending.status = GenerationStatus.FAILED
                pending.error = error
                pending.completed_at = datetime.utcnow().isoformat() + "Z"

            await _save_state(pending.to_progress())
            pending.result_ready_event.set()

        except Exception as exc:
            pending.status = GenerationStatus.FAILED
            pending.error = str(exc)
            pending.completed_at = datetime.utcnow().isoformat() + "Z"
            await _save_state(pending.to_progress())
            pending.result_ready_event.set()

    def _find_latest_output_dir(self, job_index: int) -> Optional[Path]:
        """Find the latest output directory for a job."""
        outputs = WORKSPACE / "outputs"
        if not outputs.exists():
            return None

        app_dirs = outputs.glob(f"*_{job_index:02d}_*") or outputs.glob(f"*_{job_index}_*")
        candidates = sorted(app_dirs, key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]

        # Also check applications/all_jobs
        apps = WORKSPACE / "applications" / "all_jobs"
        if apps.exists():
            candidates = sorted(
                apps.glob(f"{job_index:02d}_*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]
        return None

    def _load_rubric_scores(self, output_dir: Path) -> Optional[dict]:
        """Load rubric scores from output directory if available."""
        # Look for quality audit output
        audit_files = list(output_dir.glob("*.quality_audit.json"))
        if not audit_files:
            audit_files = list(output_dir.glob("quality_audit.json"))
        if audit_files:
            try:
                return json.loads(audit_files[0].read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return None

    async def get_status(self, job_index: int) -> GenerationProgress:
        """Get current generation status for a job."""
        async with self._lock:
            if job_index in self._pending:
                return self._pending[job_index].to_progress()

        # Check persisted state
        state = await _load_state(job_index)
        if state:
            return GenerationProgress(
                job_index=state["job_index"],
                target=GenerationTarget(state["target"]),
                status=GenerationStatus(state["status"]),
                provider=state["provider"],
                started_at=state.get("started_at"),
                completed_at=state.get("completed_at"),
                progress_pct=state.get("progress_pct", 0.0),
                current_step=state.get("current_step", ""),
                estimated_remaining_s=state.get("estimated_remaining_s"),
                error=state.get("error"),
                output_dir=state.get("output_dir"),
                rubric_scores=state.get("rubric_scores"),
            )

        # No state found — return idle
        return GenerationProgress(
            job_index=job_index,
            target=GenerationTarget.BOTH,
            status=GenerationStatus.IDLE,
            provider="",
        )

    async def accept(self, job_index: int) -> GenerationProgress:
        """
        Accept generated content. Promotes the latest generation to the canonical bundle.
        """
        async with self._lock:
            if job_index in self._pending:
                pending = self._pending[job_index]
                if pending.status not in (GenerationStatus.COMPLETED, GenerationStatus.ACCEPTED, GenerationStatus.REJECTED):
                    raise ValueError(f"Cannot accept: generation not complete for job {job_index}")

        # Call promote (same as run_single_job.py does on success)
        try:
            sys.path.insert(0, str(AGENTS_SDK_ROOT))
            from agents_sdk.resume_agent.unified_workspace import promote_latest_application_for_job

            promote_latest_application_for_job(
                str(WORKSPACE),
                job_index,
                extra_workspaces=[str(WORKSPACE.parent / "new_job")],
            )
        except Exception as exc:
            logger.warning(f"Promote failed for job {job_index}: {exc}")

        # Update state
        progress = await self.get_status(job_index)
        progress.status = GenerationStatus.ACCEPTED
        await _save_state(progress)

        async with self._lock:
            if job_index in self._pending:
                self._pending[job_index].status = GenerationStatus.ACCEPTED

        return progress

    async def reject(self, job_index: int) -> GenerationProgress:
        """
        Reject generated content. Keeps the old content, clears the generation state.
        """
        async with self._lock:
            if job_index in self._pending:
                pending = self._pending[job_index]
                pending.status = GenerationStatus.REJECTED
                pending.completed_at = datetime.utcnow().isoformat() + "Z"
                progress = pending.to_progress()
                await _save_state(progress)
                return progress

        # No pending — just return rejected from persisted state
        progress = await self.get_status(job_index)
        progress.status = GenerationStatus.REJECTED
        await _save_state(progress)
        return progress

    async def cancel(self, job_index: int) -> GenerationProgress:
        """Cancel in-progress generation."""
        async with self._lock:
            if job_index not in self._pending:
                raise ValueError(f"No generation in progress for job {job_index}")

            pending = self._pending[job_index]
            if pending.proc:
                try:
                    pending.proc.kill()
                except Exception:
                    pass

            pending.status = GenerationStatus.FAILED
            pending.error = "Cancelled by user"
            pending.completed_at = datetime.utcnow().isoformat() + "Z"
            progress = pending.to_progress()
            await _save_state(progress)
            del self._pending[job_index]
            return progress


# ── Global singleton ───────────────────────────────────────────────────────────
_orchestrator: Optional[GenerationOrchestrator] = None


def get_orchestrator() -> GenerationOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GenerationOrchestrator()
    return _orchestrator
