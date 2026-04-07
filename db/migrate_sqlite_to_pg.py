"""Migrate denjobs SQLite and JSON state into PostgreSQL.

Run with:

    python -m db.migrate_sqlite_to_pg

The migration is idempotent on rerun. It upserts rows by primary key and skips
legacy stores that do not exist locally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import asyncpg

from db import close_pool, create_pool, ensure_schema

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DB = PROJECT_ROOT / "research" / "sources" / "source_metadata.db"
SEARCH_DB = PROJECT_ROOT / "search" / "search.db"
RESEARCH_DB = PROJECT_ROOT / "research" / "research" / "research.db"
PROFILE_DB = PROJECT_ROOT / "facts" / "profile_metadata.db"
GENERATION_STATE_DIR = PROJECT_ROOT / ".generation_state"
JOB_STATUS_FILE = PROJECT_ROOT / "job_posting_status.json"


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _dump_json(value: Any) -> str:
    return json.dumps(value)


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _fetch_sqlite_rows(db_path: Path, query: str) -> list[sqlite3.Row]:
    if not db_path.exists():
        logger.info("Skipping missing SQLite store: %s", db_path)
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query).fetchall()
    except sqlite3.OperationalError as exc:
        logger.info("Skipping query for %s: %s", db_path, exc)
        return []
    finally:
        conn.close()


async def _executemany(
    conn: asyncpg.Connection,
    sql: str,
    rows: list[tuple[Any, ...]],
) -> int:
    if not rows:
        return 0
    await conn.executemany(sql, rows)
    return len(rows)


async def migrate_source_store(conn: asyncpg.Connection) -> dict[str, int]:
    rows_records = _fetch_sqlite_rows(
        SOURCE_DB,
        """
        SELECT record_id, archetype, label, created_at, updated_at, revision_count
        FROM source_records
        """,
    )
    rows_fields = _fetch_sqlite_rows(
        SOURCE_DB,
        """
        SELECT record_id, field_id, label, value, category, field_order
        FROM source_fields
        """,
    )
    rows_revisions = _fetch_sqlite_rows(
        SOURCE_DB,
        """
        SELECT revision_id, record_id, created_at, provenance, summary, field_count, snapshot
        FROM source_revisions
        """,
    )

    counts = {
        "source_records": await _executemany(
            conn,
            """
            INSERT INTO source_records (
                record_id, archetype, label, created_at, updated_at, revision_count
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (record_id) DO UPDATE SET
                archetype = EXCLUDED.archetype,
                label = EXCLUDED.label,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                revision_count = EXCLUDED.revision_count
            """,
            [
                (
                    row["record_id"],
                    row["archetype"],
                    row["label"],
                    row["created_at"],
                    row["updated_at"],
                    row["revision_count"],
                )
                for row in rows_records
            ],
        ),
        "source_fields": await _executemany(
            conn,
            """
            INSERT INTO source_fields (
                record_id, field_id, label, value, category, field_order
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (record_id, field_id) DO UPDATE SET
                label = EXCLUDED.label,
                value = EXCLUDED.value,
                category = EXCLUDED.category,
                field_order = EXCLUDED.field_order
            """,
            [
                (
                    row["record_id"],
                    row["field_id"],
                    row["label"],
                    row["value"],
                    row["category"],
                    row["field_order"],
                )
                for row in rows_fields
            ],
        ),
        "source_revisions": await _executemany(
            conn,
            """
            INSERT INTO source_revisions (
                revision_id, record_id, created_at, provenance, summary, field_count, snapshot
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (revision_id) DO UPDATE SET
                record_id = EXCLUDED.record_id,
                created_at = EXCLUDED.created_at,
                provenance = EXCLUDED.provenance,
                summary = EXCLUDED.summary,
                field_count = EXCLUDED.field_count,
                snapshot = EXCLUDED.snapshot
            """,
            [
                (
                    row["revision_id"],
                    row["record_id"],
                    row["created_at"],
                    row["provenance"],
                    row["summary"],
                    row["field_count"],
                    _dump_json(_load_json(row["snapshot"], {})),
                )
                for row in rows_revisions
            ],
        ),
    }
    return counts


async def migrate_search_store(conn: asyncpg.Connection) -> dict[str, int]:
    rows_preferences = _fetch_sqlite_rows(SEARCH_DB, "SELECT * FROM search_preferences")
    rows_runs = _fetch_sqlite_rows(SEARCH_DB, "SELECT * FROM search_runs")
    rows_candidates = _fetch_sqlite_rows(SEARCH_DB, "SELECT * FROM job_candidates")
    rows_lists = _fetch_sqlite_rows(SEARCH_DB, "SELECT * FROM job_lists")
    rows_list_items = _fetch_sqlite_rows(SEARCH_DB, "SELECT * FROM job_list_items")

    counts = {
        "search_preferences": await _executemany(
            conn,
            """
            INSERT INTO search_preferences (
                preference_id, label, archetype, keywords, locations, sources,
                experience_level, remote_policy, salary_min, discovery_strategy,
                companies, max_results_per_source, created_at, updated_at, last_run_at
            ) VALUES (
                $1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb,
                $7, $8, $9, $10,
                $11::jsonb, $12, $13, $14, $15
            )
            ON CONFLICT (preference_id) DO UPDATE SET
                label = EXCLUDED.label,
                archetype = EXCLUDED.archetype,
                keywords = EXCLUDED.keywords,
                locations = EXCLUDED.locations,
                sources = EXCLUDED.sources,
                experience_level = EXCLUDED.experience_level,
                remote_policy = EXCLUDED.remote_policy,
                salary_min = EXCLUDED.salary_min,
                discovery_strategy = EXCLUDED.discovery_strategy,
                companies = EXCLUDED.companies,
                max_results_per_source = EXCLUDED.max_results_per_source,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                last_run_at = EXCLUDED.last_run_at
            """,
            [
                (
                    row["preference_id"],
                    row["label"],
                    row["archetype"],
                    _dump_json(_load_json(row["keywords"], [])),
                    _dump_json(_load_json(row["locations"], [])),
                    _dump_json(_load_json(row["sources"], [])),
                    row["experience_level"],
                    row["remote_policy"],
                    row["salary_min"],
                    _row_value(row, "discovery_strategy", "search_and_career_pages"),
                    _dump_json(_load_json(_row_value(row, "companies", "[]"), [])),
                    _row_value(row, "max_results_per_source", 50),
                    row["created_at"],
                    row["updated_at"],
                    row["last_run_at"],
                )
                for row in rows_preferences
            ],
        ),
        "search_runs": await _executemany(
            conn,
            """
            INSERT INTO search_runs (
                run_id, preference_id, preference_label, status, started_at, completed_at,
                total_candidates, new_candidates, duplicate_count, warnings, error_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
            ON CONFLICT (run_id) DO UPDATE SET
                preference_id = EXCLUDED.preference_id,
                preference_label = EXCLUDED.preference_label,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                total_candidates = EXCLUDED.total_candidates,
                new_candidates = EXCLUDED.new_candidates,
                duplicate_count = EXCLUDED.duplicate_count,
                warnings = EXCLUDED.warnings,
                error_message = EXCLUDED.error_message
            """,
            [
                (
                    row["run_id"],
                    row["preference_id"],
                    row["preference_label"],
                    row["status"],
                    row["started_at"],
                    row["completed_at"],
                    row["total_candidates"],
                    row["new_candidates"],
                    row["duplicate_count"],
                    _dump_json(_load_json(_row_value(row, "warnings", "[]"), [])),
                    row["error_message"],
                )
                for row in rows_runs
            ],
        ),
        "job_candidates": await _executemany(
            conn,
            """
            INSERT INTO job_candidates (
                candidate_id, run_id, source, source_url, company, role, location, salary,
                remote, posted_date, apply_url, discovery_url, extraction_method,
                source_confidence, search_rank, identity_key, is_duplicate,
                duplicate_of_candidate_id, ingested, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13,
                $14, $15, $16, $17,
                $18, $19, $20
            )
            ON CONFLICT (candidate_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                source = EXCLUDED.source,
                source_url = EXCLUDED.source_url,
                company = EXCLUDED.company,
                role = EXCLUDED.role,
                location = EXCLUDED.location,
                salary = EXCLUDED.salary,
                remote = EXCLUDED.remote,
                posted_date = EXCLUDED.posted_date,
                apply_url = EXCLUDED.apply_url,
                discovery_url = EXCLUDED.discovery_url,
                extraction_method = EXCLUDED.extraction_method,
                source_confidence = EXCLUDED.source_confidence,
                search_rank = EXCLUDED.search_rank,
                identity_key = EXCLUDED.identity_key,
                is_duplicate = EXCLUDED.is_duplicate,
                duplicate_of_candidate_id = EXCLUDED.duplicate_of_candidate_id,
                ingested = EXCLUDED.ingested,
                created_at = EXCLUDED.created_at
            """,
            [
                (
                    row["candidate_id"],
                    row["run_id"],
                    row["source"],
                    row["source_url"],
                    row["company"],
                    row["role"],
                    row["location"],
                    row["salary"],
                    row["remote"],
                    row["posted_date"],
                    row["apply_url"],
                    _row_value(row, "discovery_url"),
                    _row_value(row, "extraction_method", "ats_api"),
                    _row_value(row, "source_confidence", "high"),
                    _row_value(row, "search_rank", 0),
                    row["identity_key"],
                    bool(row["is_duplicate"]),
                    row["duplicate_of_candidate_id"],
                    bool(row["ingested"]),
                    row["created_at"],
                )
                for row in rows_candidates
            ],
        ),
        "job_lists": await _executemany(
            conn,
            """
            INSERT INTO job_lists (list_id, run_id, label, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (list_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                label = EXCLUDED.label,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (
                    row["list_id"],
                    row["run_id"],
                    row["label"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows_lists
            ],
        ),
        "job_list_items": await _executemany(
            conn,
            """
            INSERT INTO job_list_items (
                item_id, list_id, candidate_id, position, notes, priority,
                status, promoted, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (item_id) DO UPDATE SET
                list_id = EXCLUDED.list_id,
                candidate_id = EXCLUDED.candidate_id,
                position = EXCLUDED.position,
                notes = EXCLUDED.notes,
                priority = EXCLUDED.priority,
                status = EXCLUDED.status,
                promoted = EXCLUDED.promoted,
                created_at = EXCLUDED.created_at
            """,
            [
                (
                    row["item_id"],
                    row["list_id"],
                    row["candidate_id"],
                    row["position"],
                    row["notes"],
                    row["priority"],
                    row["status"],
                    bool(row["promoted"]),
                    row["created_at"],
                )
                for row in rows_list_items
            ],
        ),
    }
    return counts


async def migrate_research_store(conn: asyncpg.Connection) -> dict[str, int]:
    rows_companies = _fetch_sqlite_rows(RESEARCH_DB, "SELECT * FROM research_companies")
    rows_snapshots = _fetch_sqlite_rows(RESEARCH_DB, "SELECT * FROM research_snapshots")
    rows_claims = _fetch_sqlite_rows(RESEARCH_DB, "SELECT * FROM research_claims")
    rows_questions = _fetch_sqlite_rows(RESEARCH_DB, "SELECT * FROM research_interview_questions")
    rows_refreshes = _fetch_sqlite_rows(RESEARCH_DB, "SELECT * FROM research_refreshes")

    counts = {
        "research_companies": await _executemany(
            conn,
            """
            INSERT INTO research_companies (company_key, company_name, created_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (company_key) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                created_at = EXCLUDED.created_at
            """,
            [
                (row["company_key"], row["company_name"], row["created_at"])
                for row in rows_companies
            ],
        ),
        "research_snapshots": await _executemany(
            conn,
            """
            INSERT INTO research_snapshots (
                snapshot_id, company_key, collected_at, source_count, claim_count,
                question_count, status, error_message, artifact_paths, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                company_key = EXCLUDED.company_key,
                collected_at = EXCLUDED.collected_at,
                source_count = EXCLUDED.source_count,
                claim_count = EXCLUDED.claim_count,
                question_count = EXCLUDED.question_count,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                artifact_paths = EXCLUDED.artifact_paths,
                created_at = EXCLUDED.created_at
            """,
            [
                (
                    row["snapshot_id"],
                    row["company_key"],
                    row["collected_at"],
                    row["source_count"],
                    row["claim_count"],
                    row["question_count"],
                    row["status"],
                    row["error_message"],
                    _dump_json(_load_json(row["artifact_paths"], [])),
                    row["created_at"],
                )
                for row in rows_snapshots
            ],
        ),
        "research_claims": await _executemany(
            conn,
            """
            INSERT INTO research_claims (
                claim_id, snapshot_id, company_key, claim_text, source_url,
                collected_at, confidence, themes, sentiment_score,
                role_applicability, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb, $11)
            ON CONFLICT (claim_id) DO UPDATE SET
                snapshot_id = EXCLUDED.snapshot_id,
                company_key = EXCLUDED.company_key,
                claim_text = EXCLUDED.claim_text,
                source_url = EXCLUDED.source_url,
                collected_at = EXCLUDED.collected_at,
                confidence = EXCLUDED.confidence,
                themes = EXCLUDED.themes,
                sentiment_score = EXCLUDED.sentiment_score,
                role_applicability = EXCLUDED.role_applicability,
                created_at = EXCLUDED.created_at
            """,
            [
                (
                    row["claim_id"],
                    row["snapshot_id"],
                    row["company_key"],
                    row["claim_text"],
                    row["source_url"],
                    row["collected_at"],
                    row["confidence"],
                    _dump_json(_load_json(row["themes"], [])),
                    row["sentiment_score"],
                    _dump_json(_load_json(row["role_applicability"], [])),
                    row["created_at"],
                )
                for row in rows_claims
            ],
        ),
        "research_interview_questions": await _executemany(
            conn,
            """
            INSERT INTO research_interview_questions (
                question_id, snapshot_id, company_key, question_text, source_url,
                collected_at, role_applicability, themes, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9)
            ON CONFLICT (question_id) DO UPDATE SET
                snapshot_id = EXCLUDED.snapshot_id,
                company_key = EXCLUDED.company_key,
                question_text = EXCLUDED.question_text,
                source_url = EXCLUDED.source_url,
                collected_at = EXCLUDED.collected_at,
                role_applicability = EXCLUDED.role_applicability,
                themes = EXCLUDED.themes,
                created_at = EXCLUDED.created_at
            """,
            [
                (
                    row["question_id"],
                    row["snapshot_id"],
                    row["company_key"],
                    row["question_text"],
                    row["source_url"],
                    row["collected_at"],
                    _dump_json(_load_json(row["role_applicability"], [])),
                    _dump_json(_load_json(row["themes"], [])),
                    row["created_at"],
                )
                for row in rows_questions
            ],
        ),
        "research_refreshes": await _executemany(
            conn,
            """
            INSERT INTO research_refreshes (
                refresh_id, company_key, status, started_at, completed_at,
                current_source, sources_total, sources_completed, error_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (refresh_id) DO UPDATE SET
                company_key = EXCLUDED.company_key,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                current_source = EXCLUDED.current_source,
                sources_total = EXCLUDED.sources_total,
                sources_completed = EXCLUDED.sources_completed,
                error_message = EXCLUDED.error_message
            """,
            [
                (
                    row["refresh_id"],
                    row["company_key"],
                    row["status"],
                    row["started_at"],
                    row["completed_at"],
                    row["current_source"],
                    row["sources_total"],
                    row["sources_completed"],
                    row["error_message"],
                )
                for row in rows_refreshes
            ],
        ),
    }
    return counts


async def migrate_profile_store(conn: asyncpg.Connection) -> dict[str, int]:
    rows_profiles = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM profiles")
    rows_experiences = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM experiences")
    rows_experience_bullets = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM experience_bullets")
    rows_skills = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM skills")
    rows_skill_links = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM skill_experience_links")
    rows_education = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM education_entries")
    rows_certifications = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM certifications")
    rows_skill_catalog = _fetch_sqlite_rows(PROFILE_DB, "SELECT * FROM skill_catalog")

    counts = {
        "profiles": await _executemany(
            conn,
            """
            INSERT INTO profiles (
                profile_id, label, is_active, full_name, email, phone, location,
                linkedin, headline, summary, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (profile_id) DO UPDATE SET
                label = EXCLUDED.label,
                is_active = EXCLUDED.is_active,
                full_name = EXCLUDED.full_name,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                location = EXCLUDED.location,
                linkedin = EXCLUDED.linkedin,
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (
                    row["profile_id"],
                    row["label"],
                    bool(row["is_active"]),
                    row["full_name"],
                    row["email"],
                    row["phone"],
                    row["location"],
                    row["linkedin"],
                    row["headline"],
                    row["summary"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows_profiles
            ],
        ),
        "experiences": await _executemany(
            conn,
            """
            INSERT INTO experiences (
                profile_id, experience_id, company, title, start_date, end_date,
                is_current, sort_order
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (profile_id, experience_id) DO UPDATE SET
                company = EXCLUDED.company,
                title = EXCLUDED.title,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                is_current = EXCLUDED.is_current,
                sort_order = EXCLUDED.sort_order
            """,
            [
                (
                    row["profile_id"],
                    row["experience_id"],
                    row["company"],
                    row["title"],
                    row["start_date"],
                    row["end_date"],
                    bool(row["is_current"]),
                    row["sort_order"],
                )
                for row in rows_experiences
            ],
        ),
        "experience_bullets": await _executemany(
            conn,
            """
            INSERT INTO experience_bullets (
                profile_id, experience_id, bullet_id, text, sort_order
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (profile_id, bullet_id) DO UPDATE SET
                experience_id = EXCLUDED.experience_id,
                text = EXCLUDED.text,
                sort_order = EXCLUDED.sort_order
            """,
            [
                (
                    row["profile_id"],
                    row["experience_id"],
                    row["bullet_id"],
                    row["text"],
                    row["sort_order"],
                )
                for row in rows_experience_bullets
            ],
        ),
        "skills": await _executemany(
            conn,
            """
            INSERT INTO skills (
                profile_id, skill_entry_id, skill_catalog_id, name, source,
                level, notes, sort_order
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (profile_id, skill_entry_id) DO UPDATE SET
                skill_catalog_id = EXCLUDED.skill_catalog_id,
                name = EXCLUDED.name,
                source = EXCLUDED.source,
                level = EXCLUDED.level,
                notes = EXCLUDED.notes,
                sort_order = EXCLUDED.sort_order
            """,
            [
                (
                    row["profile_id"],
                    row["skill_entry_id"],
                    row["skill_catalog_id"],
                    row["name"],
                    row["source"],
                    row["level"],
                    row["notes"],
                    row["sort_order"],
                )
                for row in rows_skills
            ],
        ),
        "skill_experience_links": await _executemany(
            conn,
            """
            INSERT INTO skill_experience_links (
                profile_id, skill_entry_id, experience_id
            ) VALUES ($1, $2, $3)
            ON CONFLICT (profile_id, skill_entry_id, experience_id) DO NOTHING
            """,
            [
                (
                    row["profile_id"],
                    row["skill_entry_id"],
                    row["experience_id"],
                )
                for row in rows_skill_links
            ],
        ),
        "education_entries": await _executemany(
            conn,
            """
            INSERT INTO education_entries (
                profile_id, education_id, institution, degree, field_of_study,
                graduation_date, notes, sort_order
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (profile_id, education_id) DO UPDATE SET
                institution = EXCLUDED.institution,
                degree = EXCLUDED.degree,
                field_of_study = EXCLUDED.field_of_study,
                graduation_date = EXCLUDED.graduation_date,
                notes = EXCLUDED.notes,
                sort_order = EXCLUDED.sort_order
            """,
            [
                (
                    row["profile_id"],
                    row["education_id"],
                    row["institution"],
                    row["degree"],
                    row["field_of_study"],
                    row["graduation_date"],
                    row["notes"],
                    row["sort_order"],
                )
                for row in rows_education
            ],
        ),
        "certifications": await _executemany(
            conn,
            """
            INSERT INTO certifications (
                profile_id, certification_id, name, issuer, issued_at,
                credential_id, notes, sort_order
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (profile_id, certification_id) DO UPDATE SET
                name = EXCLUDED.name,
                issuer = EXCLUDED.issuer,
                issued_at = EXCLUDED.issued_at,
                credential_id = EXCLUDED.credential_id,
                notes = EXCLUDED.notes,
                sort_order = EXCLUDED.sort_order
            """,
            [
                (
                    row["profile_id"],
                    row["certification_id"],
                    row["name"],
                    row["issuer"],
                    row["issued_at"],
                    row["credential_id"],
                    row["notes"],
                    row["sort_order"],
                )
                for row in rows_certifications
            ],
        ),
        "skill_catalog": await _executemany(
            conn,
            """
            INSERT INTO skill_catalog (
                skill_id, normalized_name, name, source, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (skill_id) DO UPDATE SET
                normalized_name = EXCLUDED.normalized_name,
                name = EXCLUDED.name,
                source = EXCLUDED.source,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (
                    row["skill_id"],
                    row["normalized_name"],
                    row["name"],
                    row["source"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows_skill_catalog
            ],
        ),
    }
    return counts


async def migrate_generation_state(conn: asyncpg.Connection) -> dict[str, int]:
    rows: list[tuple[Any, ...]] = []
    if not GENERATION_STATE_DIR.exists():
        logger.info("Skipping missing generation state directory: %s", GENERATION_STATE_DIR)
        return {"generation_state": 0}

    for path in sorted(GENERATION_STATE_DIR.glob("gen_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping generation state file %s: %s", path, exc)
            continue

        rows.append(
            (
                payload["job_index"],
                payload.get("target", "both"),
                payload.get("status", "idle"),
                payload.get("provider", ""),
                payload.get("started_at"),
                payload.get("completed_at"),
                payload.get("progress_pct", 0.0),
                payload.get("current_step", ""),
                payload.get("estimated_remaining_s"),
                payload.get("error"),
                payload.get("output_dir"),
                _dump_json(payload.get("rubric_scores"))
                if payload.get("rubric_scores") is not None
                else None,
                payload.get("completed_at")
                or payload.get("started_at")
                or datetime_now_utc(),
            )
        )

    return {
        "generation_state": await _executemany(
            conn,
            """
            INSERT INTO generation_state (
                job_index, target, status, provider, started_at, completed_at,
                progress_pct, current_step, estimated_remaining_s, error,
                output_dir, rubric_scores, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13)
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
            rows,
        )
    }


def datetime_now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def migrate_job_posting_status(conn: asyncpg.Connection) -> dict[str, int]:
    if not JOB_STATUS_FILE.exists():
        logger.info("Skipping missing job status file: %s", JOB_STATUS_FILE)
        return {"job_posting_status": 0}

    try:
        payload = json.loads(JOB_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Skipping job status file %s: %s", JOB_STATUS_FILE, exc)
        return {"job_posting_status": 0}

    updated_at = payload.get("updated_at") or datetime_now_utc()
    statuses = payload.get("statuses", [])
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
            entry.get("lastChecked") or updated_at,
        )
        for entry in statuses
    ]

    return {
        "job_posting_status": await _executemany(
            conn,
            """
            INSERT INTO job_posting_status (
                "index", url, status, last_checked, error, source,
                http_status_code, response_time_ms, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
    }


async def run_migration() -> dict[str, int]:
    pool = await create_pool(min_size=1, max_size=4)
    try:
        await ensure_schema(pool)
        async with pool.acquire() as conn:
            async with conn.transaction():
                summary: dict[str, int] = {}
                for migrate in (
                    migrate_source_store,
                    migrate_search_store,
                    migrate_research_store,
                    migrate_profile_store,
                    migrate_generation_state,
                    migrate_job_posting_status,
                ):
                    summary.update(await migrate(conn))
        return summary
    finally:
        await close_pool(pool)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    summary = await run_migration()
    logger.info("Migration complete")
    for table_name, count in summary.items():
        logger.info("  %s: %s rows processed", table_name, count)


if __name__ == "__main__":
    asyncio.run(main())
