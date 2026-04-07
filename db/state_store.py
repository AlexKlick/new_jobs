"""Optional PostgreSQL-backed state persistence for runtime file stores.

This module covers the two runtime state surfaces that were previously
file-backed:

- ``generation_state`` for in-flight and completed generation progress
- ``job_posting_status`` for cached job availability checks

Call ``configure_state_store_pool()`` during app startup to enable the
PostgreSQL-backed path. Callers should still handle fallback behavior if the
pool is unavailable or a database operation fails.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from db.runtime import configure_runtime_pool, get_runtime_pool, runtime_pool_enabled


def state_store_enabled() -> bool:
    """Return True when PostgreSQL-backed state storage is configured."""
    return runtime_pool_enabled()


def configure_state_store_pool(pool) -> None:
    """Backward-compatible alias for runtime pool registration."""
    configure_runtime_pool(pool)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump_json(value: object) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _load_json(value: object, default: object) -> object:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _generation_state_from_row(row: asyncpg.Record) -> dict:
    return {
        "job_index": row["job_index"],
        "target": row["target"],
        "status": row["status"],
        "provider": row["provider"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "progress_pct": row["progress_pct"],
        "current_step": row["current_step"],
        "estimated_remaining_s": row["estimated_remaining_s"],
        "error": row["error"],
        "output_dir": row["output_dir"],
        "rubric_scores": _load_json(row["rubric_scores"], None),
    }


def _job_status_from_row(row: asyncpg.Record) -> dict:
    return {
        "index": row["index"],
        "url": row["url"],
        "status": row["status"],
        "lastChecked": row["last_checked"],
        "error": row["error"],
        "source": row["source"],
        "httpStatusCode": row["http_status_code"],
        "responseTimeMs": row["response_time_ms"],
    }


async def load_generation_state(job_index: int) -> Optional[dict]:
    """Load generation progress from PostgreSQL."""
    pool = get_runtime_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT job_index, target, status, provider, started_at, completed_at,
                   progress_pct, current_step, estimated_remaining_s, error,
                   output_dir, rubric_scores
            FROM generation_state
            WHERE job_index = $1
            """,
            job_index,
        )
    if row is None:
        return None
    return _generation_state_from_row(row)


async def upsert_generation_state(progress: dict) -> None:
    """Upsert generation progress into PostgreSQL."""
    pool = get_runtime_pool()
    if pool is None:
        raise RuntimeError("state store pool is not configured")

    updated_at = (
        progress.get("updated_at")
        or progress.get("completed_at")
        or progress.get("started_at")
        or _utc_now()
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO generation_state (
                job_index, target, status, provider, started_at, completed_at,
                progress_pct, current_step, estimated_remaining_s, error,
                output_dir, rubric_scores, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12::jsonb, $13
            )
            ON CONFLICT (job_index) DO UPDATE SET
                target = EXCLUDED.target,
                status = EXCLUDED.status,
                provider = EXCLUDED.provider,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                progress_pct = EXCLUDED.progress_pct,
                current_step = EXCLUDED.current_step,
                estimated_remaining_s = EXCLUDED.estimated_remaining_s,
                error = EXCLUDED.error,
                output_dir = EXCLUDED.output_dir,
                rubric_scores = EXCLUDED.rubric_scores,
                updated_at = EXCLUDED.updated_at
            """,
            progress["job_index"],
            progress.get("target", "both"),
            progress.get("status", "idle"),
            progress.get("provider", ""),
            progress.get("started_at"),
            progress.get("completed_at"),
            progress.get("progress_pct", 0.0),
            progress.get("current_step", ""),
            progress.get("estimated_remaining_s"),
            progress.get("error"),
            progress.get("output_dir"),
            _dump_json(progress.get("rubric_scores")),
            updated_at,
        )


async def delete_generation_state(job_index: int) -> None:
    """Delete generation progress from PostgreSQL."""
    pool = get_runtime_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM generation_state WHERE job_index = $1",
            job_index,
        )


async def load_job_posting_statuses() -> dict[int, dict]:
    """Load cached job-posting statuses from PostgreSQL."""
    pool = get_runtime_pool()
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT "index", url, status, last_checked, error, source,
                   http_status_code, response_time_ms
            FROM job_posting_status
            ORDER BY "index" ASC
            """
        )
    return {row["index"]: _job_status_from_row(row) for row in rows}


async def save_job_posting_statuses(statuses: list[dict]) -> None:
    """Upsert cached job-posting statuses into PostgreSQL."""
    pool = get_runtime_pool()
    if pool is None:
        raise RuntimeError("state store pool is not configured")

    rows = [
        (
            entry["index"],
            entry.get("url", ""),
            entry.get("status", "UNKNOWN"),
            entry.get("lastChecked"),
            entry.get("error"),
            entry.get("source", "generic"),
            entry.get("httpStatusCode"),
            entry.get("responseTimeMs"),
            entry.get("updated_at") or entry.get("lastChecked") or _utc_now(),
        )
        for entry in statuses
    ]

    async with pool.acquire() as conn:
        if rows:
            await conn.executemany(
                """
                INSERT INTO job_posting_status (
                    "index", url, status, last_checked, error, source,
                    http_status_code, response_time_ms, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9
                )
                ON CONFLICT ("index") DO UPDATE SET
                    url = EXCLUDED.url,
                    status = EXCLUDED.status,
                    last_checked = EXCLUDED.last_checked,
                    error = EXCLUDED.error,
                    source = EXCLUDED.source,
                    http_status_code = EXCLUDED.http_status_code,
                    response_time_ms = EXCLUDED.response_time_ms,
                    updated_at = EXCLUDED.updated_at
                """,
                rows,
            )
