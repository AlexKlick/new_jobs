"""
Search Store - SQLite-backed persistence for search preferences, runs, and candidates.

Stores:
- SearchPreference: saved search presets with keywords, locations, and discovery settings
- SearchRun: single search execution with status tracking and warnings
- JobCandidate: individual job from a run with deduplication metadata and rank

Deduplication prefers normalized apply URLs and falls back to normalized
company + role + location tuples.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from graph.career_event_bus import emit_career_event

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.resolve()
SEARCH_DIR = PROJECT_ROOT
SEARCH_DB = SEARCH_DIR / "search.db"


class JobSource(str):
    greenhouse = "greenhouse"
    lever = "lever"
    career_page = "career_page"
    generic_web = "generic_web"


class SearchRunStatus(str):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SearchPreferenceModel(BaseModel):
    preference_id: str
    label: str
    archetype: str
    keywords: list[str]
    locations: list[str]
    sources: list[str]
    experience_level: Optional[str] = None
    remote_policy: Optional[str] = None
    salary_min: Optional[int] = None
    discovery_strategy: str = "search_and_career_pages"
    companies: list[str] = Field(default_factory=list)
    max_results_per_source: int = 50
    created_at: str
    updated_at: str
    last_run_at: Optional[str] = None


class JobCandidateModel(BaseModel):
    candidate_id: str
    run_id: str
    source: str
    source_url: str
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None
    remote: Optional[str] = None
    posted_date: Optional[str] = None
    apply_url: Optional[str] = None
    discovery_url: Optional[str] = None
    extraction_method: str = "ats_api"
    source_confidence: str = "high"
    search_rank: int = 0
    identity_key: str
    is_duplicate: bool = False
    duplicate_of_candidate_id: Optional[str] = None
    ingested: bool = False
    created_at: str


class SearchRunModel(BaseModel):
    run_id: str
    preference_id: Optional[str] = None
    preference_label: Optional[str] = None
    status: str = "pending"
    started_at: str
    completed_at: Optional[str] = None
    total_candidates: int = 0
    new_candidates: int = 0
    duplicate_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class SearchRunDetailModel(SearchRunModel):
    candidates: list[JobCandidateModel] = Field(default_factory=list)


class JobListModel(BaseModel):
    list_id: str
    run_id: str
    label: str
    created_at: str
    updated_at: str


class JobListItemModel(BaseModel):
    item_id: str
    list_id: str
    candidate_id: str
    position: int
    notes: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    promoted: bool = False
    created_at: str


class JobListItemDisplayModel(JobListItemModel):
    source: str
    source_url: str
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None
    remote: Optional[str] = None
    posted_date: Optional[str] = None
    apply_url: Optional[str] = None
    discovery_url: Optional[str] = None
    extraction_method: str = "ats_api"
    source_confidence: str = "high"
    search_rank: int = 0
    identity_key: str
    is_duplicate: bool = False
    ingested: bool = False


class JobListDetailModel(JobListModel):
    items: list[JobListItemDisplayModel] = Field(default_factory=list)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_preferences (
    preference_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    archetype TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '[]',
    locations TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    experience_level TEXT,
    remote_policy TEXT,
    salary_min INTEGER,
    discovery_strategy TEXT NOT NULL DEFAULT 'search_and_career_pages',
    companies TEXT NOT NULL DEFAULT '[]',
    max_results_per_source INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS search_runs (
    run_id TEXT PRIMARY KEY,
    preference_id TEXT REFERENCES search_preferences(preference_id),
    preference_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    total_candidates INTEGER NOT NULL DEFAULT 0,
    new_candidates INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    warnings TEXT NOT NULL DEFAULT '[]',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS job_candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES search_runs(run_id),
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT,
    salary TEXT,
    remote TEXT,
    posted_date TEXT,
    apply_url TEXT,
    discovery_url TEXT,
    extraction_method TEXT NOT NULL DEFAULT 'ats_api',
    source_confidence TEXT NOT NULL DEFAULT 'high',
    search_rank INTEGER NOT NULL DEFAULT 0,
    identity_key TEXT NOT NULL,
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    duplicate_of_candidate_id TEXT,
    ingested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_run ON job_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_identity ON job_candidates(identity_key);
CREATE INDEX IF NOT EXISTS idx_candidates_rank ON job_candidates(run_id, search_rank);
CREATE INDEX IF NOT EXISTS idx_runs_status ON search_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started ON search_runs(started_at);

CREATE TABLE IF NOT EXISTS job_lists (
    list_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES search_runs(run_id),
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_list_items (
    item_id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL REFERENCES job_lists(list_id),
    candidate_id TEXT NOT NULL REFERENCES job_candidates(candidate_id),
    position INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    priority TEXT,
    status TEXT,
    promoted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_list_items_list ON job_list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_list_items_position ON job_list_items(list_id, position);
CREATE UNIQUE INDEX IF NOT EXISTS idx_list_items_unique_candidate
ON job_list_items(list_id, candidate_id);
"""

_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "search_preferences": (
        "ALTER TABLE search_preferences ADD COLUMN discovery_strategy TEXT NOT NULL DEFAULT 'search_and_career_pages'",
        "ALTER TABLE search_preferences ADD COLUMN companies TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE search_preferences ADD COLUMN max_results_per_source INTEGER NOT NULL DEFAULT 50",
    ),
    "search_runs": (
        "ALTER TABLE search_runs ADD COLUMN warnings TEXT NOT NULL DEFAULT '[]'",
    ),
    "job_candidates": (
        "ALTER TABLE job_candidates ADD COLUMN discovery_url TEXT",
        "ALTER TABLE job_candidates ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'ats_api'",
        "ALTER TABLE job_candidates ADD COLUMN source_confidence TEXT NOT NULL DEFAULT 'high'",
        "ALTER TABLE job_candidates ADD COLUMN search_rank INTEGER NOT NULL DEFAULT 0",
    ),
}


def _safe_json_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    for table, statements in _MIGRATIONS.items():
        existing_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for statement in statements:
            parts = statement.split()
            column_name = parts[5]
            if column_name in existing_columns:
                continue
            conn.execute(statement)
            existing_columns.add(column_name)


def _get_db() -> sqlite3.Connection:
    SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SEARCH_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _ensure_migrations(conn)
    return conn


class SearchStore:
    """SQLite-backed store for search preferences, runs, and candidates."""

    def __init__(self) -> None:
        self._db_path = SEARCH_DB
        with _get_db():
            pass

    def list_preferences(self) -> list[SearchPreferenceModel]:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT preference_id, label, archetype, keywords, locations, sources, "
                "experience_level, remote_policy, salary_min, discovery_strategy, "
                "companies, max_results_per_source, created_at, updated_at, last_run_at "
                "FROM search_preferences ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_preference(r) for r in rows]

    def get_preference(self, preference_id: str) -> Optional[SearchPreferenceModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT preference_id, label, archetype, keywords, locations, sources, "
                "experience_level, remote_policy, salary_min, discovery_strategy, "
                "companies, max_results_per_source, created_at, updated_at, last_run_at "
                "FROM search_preferences WHERE preference_id = ?",
                (preference_id,),
            ).fetchone()
            return self._row_to_preference(row) if row else None

    def create_preference(
        self,
        label: str,
        archetype: str,
        keywords: list[str],
        locations: list[str],
        sources: list[str],
        experience_level: Optional[str] = None,
        remote_policy: Optional[str] = None,
        salary_min: Optional[int] = None,
        discovery_strategy: str = "search_and_career_pages",
        companies: Optional[list[str]] = None,
        max_results_per_source: int = 50,
    ) -> SearchPreferenceModel:
        now = datetime.now(timezone.utc).isoformat()
        preference_id = f"pref-{uuid.uuid4().hex[:12]}"
        companies = companies or []

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO search_preferences "
                "(preference_id, label, archetype, keywords, locations, sources, "
                "experience_level, remote_policy, salary_min, discovery_strategy, companies, "
                "max_results_per_source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    preference_id,
                    label,
                    archetype,
                    json.dumps(keywords),
                    json.dumps(locations),
                    json.dumps(sources),
                    experience_level,
                    remote_policy,
                    salary_min,
                    discovery_strategy,
                    json.dumps(companies),
                    max_results_per_source,
                    now,
                    now,
                ),
            )

        return SearchPreferenceModel(
            preference_id=preference_id,
            label=label,
            archetype=archetype,
            keywords=keywords,
            locations=locations,
            sources=sources,
            experience_level=experience_level,
            remote_policy=remote_policy,
            salary_min=salary_min,
            discovery_strategy=discovery_strategy,
            companies=companies,
            max_results_per_source=max_results_per_source,
            created_at=now,
            updated_at=now,
            last_run_at=None,
        )

    def update_preference_last_run(self, preference_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _get_db() as conn:
            conn.execute(
                "UPDATE search_preferences SET last_run_at = ?, updated_at = ? "
                "WHERE preference_id = ?",
                (now, now, preference_id),
            )

    def delete_preference(self, preference_id: str) -> bool:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT preference_id FROM search_preferences WHERE preference_id = ?",
                (preference_id,),
            ).fetchone()
            if not row:
                return False
            run_rows = conn.execute(
                "SELECT run_id FROM search_runs WHERE preference_id = ?",
                (preference_id,),
            ).fetchall()
            run_ids = [row["run_id"] for row in run_rows]
            if run_ids:
                placeholders = ", ".join("?" for _ in run_ids)
                list_rows = conn.execute(
                    f"SELECT list_id FROM job_lists WHERE run_id IN ({placeholders})",
                    run_ids,
                ).fetchall()
                list_ids = [row["list_id"] for row in list_rows]
                if list_ids:
                    list_placeholders = ", ".join("?" for _ in list_ids)
                    conn.execute(
                        f"DELETE FROM job_list_items WHERE list_id IN ({list_placeholders})",
                        list_ids,
                    )
                    conn.execute(
                        f"DELETE FROM job_lists WHERE list_id IN ({list_placeholders})",
                        list_ids,
                    )
                conn.execute(
                    f"DELETE FROM job_candidates WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                conn.execute(
                    f"DELETE FROM search_runs WHERE run_id IN ({placeholders})",
                    run_ids,
                )
            conn.execute("DELETE FROM search_preferences WHERE preference_id = ?", (preference_id,))
            return True

    def list_runs(self) -> list[SearchRunModel]:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT run_id, preference_id, preference_label, status, started_at, "
                "completed_at, total_candidates, new_candidates, duplicate_count, warnings, "
                "error_message FROM search_runs ORDER BY started_at DESC"
            ).fetchall()
            return [self._row_to_run(r) for r in rows]

    def get_run(self, run_id: str) -> Optional[SearchRunModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT run_id, preference_id, preference_label, status, started_at, "
                "completed_at, total_candidates, new_candidates, duplicate_count, warnings, "
                "error_message FROM search_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return self._row_to_run(row) if row else None

    def get_run_detail(self, run_id: str) -> Optional[SearchRunDetailModel]:
        run = self.get_run(run_id)
        if not run:
            return None
        candidates = self.list_candidates_for_run(run_id)
        return SearchRunDetailModel(**run.model_dump(), candidates=candidates)

    def create_run(self, preference_id: Optional[str], preference_label: Optional[str]) -> SearchRunModel:
        now = datetime.now(timezone.utc).isoformat()
        run_id = f"run-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO search_runs "
                "(run_id, preference_id, preference_label, status, started_at, warnings) "
                "VALUES (?, ?, ?, 'pending', ?, '[]')",
                (run_id, preference_id, preference_label, now),
            )

        return SearchRunModel(
            run_id=run_id,
            preference_id=preference_id,
            preference_label=preference_label,
            status="pending",
            started_at=now,
            completed_at=None,
            total_candidates=0,
            new_candidates=0,
            duplicate_count=0,
            warnings=[],
            error_message=None,
        )

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error_message: Optional[str] = None,
        warnings: Optional[list[str]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if status in ("completed", "failed") else None
        warning_payload = json.dumps(warnings if warnings is not None else [])
        with _get_db() as conn:
            conn.execute(
                "UPDATE search_runs SET status = ?, completed_at = ?, error_message = ?, warnings = ? "
                "WHERE run_id = ?",
                (status, completed_at, error_message, warning_payload, run_id),
            )

    def update_run_counts(
        self,
        run_id: str,
        total_candidates: int,
        new_candidates: int,
        duplicate_count: int,
    ) -> None:
        with _get_db() as conn:
            conn.execute(
                "UPDATE search_runs SET total_candidates = ?, new_candidates = ?, "
                "duplicate_count = ? WHERE run_id = ?",
                (total_candidates, new_candidates, duplicate_count, run_id),
            )

    def list_candidates_for_run(self, run_id: str) -> list[JobCandidateModel]:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT candidate_id, run_id, source, source_url, company, role, location, "
                "salary, remote, posted_date, apply_url, discovery_url, extraction_method, "
                "source_confidence, search_rank, identity_key, is_duplicate, "
                "duplicate_of_candidate_id, ingested, created_at "
                "FROM job_candidates WHERE run_id = ? ORDER BY search_rank ASC, created_at ASC",
                (run_id,),
            ).fetchall()
            return [self._row_to_candidate(r) for r in rows]

    def find_existing_candidate(self, identity_key: str) -> Optional[JobCandidateModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT candidate_id, run_id, source, source_url, company, role, location, "
                "salary, remote, posted_date, apply_url, discovery_url, extraction_method, "
                "source_confidence, search_rank, identity_key, is_duplicate, "
                "duplicate_of_candidate_id, ingested, created_at "
                "FROM job_candidates WHERE identity_key = ? LIMIT 1",
                (identity_key,),
            ).fetchone()
            return self._row_to_candidate(row) if row else None

    def get_candidate(self, candidate_id: str) -> Optional[JobCandidateModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT candidate_id, run_id, source, source_url, company, role, location, "
                "salary, remote, posted_date, apply_url, discovery_url, extraction_method, "
                "source_confidence, search_rank, identity_key, is_duplicate, "
                "duplicate_of_candidate_id, ingested, created_at "
                "FROM job_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            return self._row_to_candidate(row) if row else None

    def add_candidate(
        self,
        run_id: str,
        source: str,
        source_url: str,
        company: str,
        role: str,
        location: Optional[str],
        salary: Optional[str],
        remote: Optional[str],
        posted_date: Optional[str],
        apply_url: Optional[str],
        discovery_url: Optional[str] = None,
        extraction_method: str = "ats_api",
        source_confidence: str = "high",
        search_rank: int = 0,
    ) -> JobCandidateModel:
        now = datetime.now(timezone.utc).isoformat()
        candidate_id = f"cand-{uuid.uuid4().hex[:12]}"
        primary_identity_key = self._compute_identity_key(company, role, location=location, apply_url=apply_url)
        fallback_identity_key = self._compute_identity_key(company, role, location=location, apply_url=None)
        identity_key = primary_identity_key or fallback_identity_key

        existing = self.find_existing_candidate(primary_identity_key)
        if existing is None and fallback_identity_key != primary_identity_key:
            existing = self._find_existing_candidate_by_fallback(company, role, location)
        is_duplicate = existing is not None
        duplicate_of = existing.candidate_id if existing else None

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO job_candidates "
                "(candidate_id, run_id, source, source_url, company, role, location, salary, "
                "remote, posted_date, apply_url, discovery_url, extraction_method, "
                "source_confidence, search_rank, identity_key, is_duplicate, "
                "duplicate_of_candidate_id, ingested, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    candidate_id,
                    run_id,
                    source,
                    source_url,
                    company,
                    role,
                    location,
                    salary,
                    remote,
                    posted_date,
                    apply_url,
                    discovery_url,
                    extraction_method,
                    source_confidence,
                    search_rank,
                    identity_key,
                    int(is_duplicate),
                    duplicate_of,
                    now,
                ),
            )

        return JobCandidateModel(
            candidate_id=candidate_id,
            run_id=run_id,
            source=source,
            source_url=source_url,
            company=company,
            role=role,
            location=location,
            salary=salary,
            remote=remote,
            posted_date=posted_date,
            apply_url=apply_url,
            discovery_url=discovery_url,
            extraction_method=extraction_method,
            source_confidence=source_confidence,
            search_rank=search_rank,
            identity_key=identity_key,
            is_duplicate=is_duplicate,
            duplicate_of_candidate_id=duplicate_of,
            ingested=False,
            created_at=now,
        )

    def mark_candidate_ingested(self, candidate_id: str) -> bool:
        with _get_db() as conn:
            result = conn.execute(
                "UPDATE job_candidates SET ingested = 1 WHERE candidate_id = ?",
                (candidate_id,),
            )
            return result.rowcount > 0

    def compute_run_counts(self, run_id: str) -> tuple[int, int, int]:
        with _get_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM job_candidates WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            dup = conn.execute(
                "SELECT COUNT(*) FROM job_candidates WHERE run_id = ? AND is_duplicate = 1",
                (run_id,),
            ).fetchone()[0]
            return total, total - dup, dup

    def create_list_for_run(self, run_id: str, label: str) -> JobListModel:
        now = datetime.now(timezone.utc).isoformat()
        list_id = f"list-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO job_lists (list_id, run_id, label, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (list_id, run_id, label, now, now),
            )

        return JobListModel(
            list_id=list_id,
            run_id=run_id,
            label=label,
            created_at=now,
            updated_at=now,
        )

    def get_list_for_run(self, run_id: str) -> Optional[JobListModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT list_id, run_id, label, created_at, updated_at FROM job_lists WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return self._row_to_list(row) if row else None

    def get_list_detail(self, list_id: str) -> Optional[JobListDetailModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT list_id, run_id, label, created_at, updated_at FROM job_lists WHERE list_id = ?",
                (list_id,),
            ).fetchone()
            if not row:
                return None

            item_rows = conn.execute(
                "SELECT jli.item_id, jli.list_id, jli.candidate_id, jli.position, "
                "jli.notes, jli.priority, jli.status, jli.promoted, jli.created_at, "
                "jc.source, jc.source_url, jc.company, jc.role, jc.location, jc.salary, "
                "jc.remote, jc.posted_date, jc.apply_url, jc.discovery_url, "
                "jc.extraction_method, jc.source_confidence, jc.search_rank, "
                "jc.identity_key, jc.is_duplicate, jc.ingested "
                "FROM job_list_items jli "
                "JOIN job_candidates jc ON jli.candidate_id = jc.candidate_id "
                "WHERE jli.list_id = ? "
                "ORDER BY jli.position",
                (list_id,),
            ).fetchall()

            items = [self._row_to_list_item_with_candidate(r) for r in item_rows]
            return JobListDetailModel(**self._row_to_list(row).model_dump(), items=items)

    def list_lists(self) -> list[JobListModel]:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT list_id, run_id, label, created_at, updated_at "
                "FROM job_lists ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_list(r) for r in rows]

    def add_candidates_to_list_from_run(self, run_id: str) -> int:
        lst = self.get_list_for_run(run_id)
        if not lst:
            return 0

        with _get_db() as conn:
            rows = conn.execute(
                "SELECT candidate_id FROM job_candidates "
                "WHERE run_id = ? AND is_duplicate = 0 "
                "ORDER BY search_rank ASC, created_at ASC",
                (run_id,),
            ).fetchall()

        count = 0
        now = datetime.now(timezone.utc).isoformat()
        for pos, row in enumerate(rows):
            self._upsert_list_item(
                list_id=lst.list_id,
                candidate_id=row["candidate_id"],
                position=pos,
                now=now,
            )
            count += 1
        return count

    def remove_item(self, item_id: str) -> bool:
        with _get_db() as conn:
            # Fetch list_id before deleting for event emission
            row = conn.execute(
                "SELECT list_id, candidate_id FROM job_list_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return False
            list_id = row["list_id"]
            result = conn.execute(
                "DELETE FROM job_list_items WHERE item_id = ?",
                (item_id,),
            )
            success = result.rowcount > 0

        if success:
            try:
                emit_career_event(
                    category="list",
                    action="list_item_removed",
                    entity_id=item_id,
                    entity_type="list_item",
                    payload={"list_id": list_id},
                )
            except Exception:
                logger.warning("Failed to emit graph event for list item_removed", exc_info=True)
        return success

    def reorder_items(self, list_id: str, item_ids: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _get_db() as conn:
            for pos, item_id in enumerate(item_ids):
                conn.execute(
                    "UPDATE job_list_items SET position = ? WHERE item_id = ? AND list_id = ?",
                    (pos, item_id, list_id),
                )
            conn.execute(
                "UPDATE job_lists SET updated_at = ? WHERE list_id = ?",
                (now, list_id),
            )

        try:
            emit_career_event(
                category="list",
                action="list_item_reordered",
                entity_id=list_id,
                entity_type="job_list",
                payload={"item_ids": item_ids},
            )
        except Exception:
            logger.warning("Failed to emit graph event for list item_reordered", exc_info=True)

    def update_item_notes(self, item_id: str, notes: str) -> bool:
        with _get_db() as conn:
            result = conn.execute(
                "UPDATE job_list_items SET notes = ? WHERE item_id = ?",
                (notes, item_id),
            )
            success = result.rowcount > 0

        if success:
            try:
                emit_career_event(
                    category="list",
                    action="list_item_notes_updated",
                    entity_id=item_id,
                    entity_type="list_item",
                    payload={"notes_length": len(notes)},
                )
            except Exception:
                logger.warning("Failed to emit graph event for list item_notes_updated", exc_info=True)
        return success

    def update_item_priority(self, item_id: str, priority: str) -> bool:
        with _get_db() as conn:
            result = conn.execute(
                "UPDATE job_list_items SET priority = ? WHERE item_id = ?",
                (priority, item_id),
            )
            success = result.rowcount > 0

        if success:
            try:
                emit_career_event(
                    category="list",
                    action="list_item_priority_updated",
                    entity_id=item_id,
                    entity_type="list_item",
                    payload={"priority": priority},
                )
            except Exception:
                logger.warning("Failed to emit graph event for list item_priority_updated", exc_info=True)
        return success

    def update_item_status(self, item_id: str, status: str) -> bool:
        with _get_db() as conn:
            result = conn.execute(
                "UPDATE job_list_items SET status = ? WHERE item_id = ?",
                (status, item_id),
            )
            success = result.rowcount > 0

        if success:
            try:
                emit_career_event(
                    category="list",
                    action="list_item_status_updated",
                    entity_id=item_id,
                    entity_type="list_item",
                    payload={"status": status},
                )
            except Exception:
                logger.warning("Failed to emit graph event for list item_status_updated", exc_info=True)
        return success

    def mark_item_promoted(self, item_id: str) -> bool:
        with _get_db() as conn:
            result = conn.execute(
                "UPDATE job_list_items SET promoted = 1 WHERE item_id = ?",
                (item_id,),
            )
            success = result.rowcount > 0

        if success:
            try:
                emit_career_event(
                    category="list",
                    action="list_item_promoted",
                    entity_id=item_id,
                    entity_type="list_item",
                    payload={"promoted": True},
                )
            except Exception:
                logger.warning("Failed to emit graph event for list item_promoted", exc_info=True)
        return success

    def get_item(self, item_id: str) -> Optional[JobListItemModel]:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT item_id, list_id, candidate_id, position, notes, priority, status, promoted, created_at "
                "FROM job_list_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return None
            return JobListItemModel(
                item_id=row["item_id"],
                list_id=row["list_id"],
                candidate_id=row["candidate_id"],
                position=row["position"],
                notes=row["notes"],
                priority=row["priority"],
                status=row["status"],
                promoted=bool(row["promoted"]),
                created_at=row["created_at"],
            )

    def _upsert_list_item(self, list_id: str, candidate_id: str, position: int, now: str) -> None:
        with _get_db() as conn:
            existing = conn.execute(
                "SELECT item_id FROM job_list_items WHERE list_id = ? AND candidate_id = ?",
                (list_id, candidate_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE job_list_items SET position = ? WHERE item_id = ?",
                    (position, existing["item_id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO job_list_items "
                    "(item_id, list_id, candidate_id, position, notes, priority, status, promoted, created_at) "
                    "VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0, ?)",
                    (f"item-{uuid.uuid4().hex[:12]}", list_id, candidate_id, position, now),
                )

    def _find_existing_candidate_by_fallback(
        self,
        company: str,
        role: str,
        location: Optional[str],
    ) -> Optional[JobCandidateModel]:
        normalized_company = self._normalize_identity_fragment(company)
        normalized_role = self._normalize_identity_fragment(role)
        normalized_location = self._normalize_identity_fragment(location or "")
        with _get_db() as conn:
            row = conn.execute(
                "SELECT candidate_id, run_id, source, source_url, company, role, location, "
                "salary, remote, posted_date, apply_url, discovery_url, extraction_method, "
                "source_confidence, search_rank, identity_key, is_duplicate, "
                "duplicate_of_candidate_id, ingested, created_at "
                "FROM job_candidates "
                "WHERE lower(trim(company)) = ? AND lower(trim(role)) = ? "
                "AND lower(trim(COALESCE(location, ''))) = ? "
                "LIMIT 1",
                (normalized_company, normalized_role, normalized_location),
            ).fetchone()
        return self._row_to_candidate(row) if row else None

    @staticmethod
    def _compute_identity_key(
        company: str,
        role: str,
        *,
        location: Optional[str] = None,
        apply_url: Optional[str] = None,
    ) -> str:
        apply_key = SearchStore._normalize_apply_url(apply_url)
        if apply_key:
            return apply_key
        normalized_company = SearchStore._normalize_identity_fragment(company)
        normalized_role = SearchStore._normalize_identity_fragment(role)
        normalized_location = SearchStore._normalize_identity_fragment(location or "")
        return f"{normalized_company}|{normalized_role}|{normalized_location}"

    @staticmethod
    def _normalize_identity_fragment(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().strip())

    @staticmethod
    def _normalize_apply_url(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
        except Exception:
            return None
        host = parsed.netloc.lower()
        path = re.sub(r"/+", "/", parsed.path.rstrip("/"))
        if not host or not path:
            return None
        return f"url|{host}{path}"

    @staticmethod
    def _row_to_preference(row: sqlite3.Row) -> SearchPreferenceModel:
        return SearchPreferenceModel(
            preference_id=row["preference_id"],
            label=row["label"],
            archetype=row["archetype"],
            keywords=_safe_json_list(row["keywords"]),
            locations=_safe_json_list(row["locations"]),
            sources=_safe_json_list(row["sources"]),
            experience_level=row["experience_level"],
            remote_policy=row["remote_policy"],
            salary_min=row["salary_min"],
            discovery_strategy=row["discovery_strategy"] or "search_and_career_pages",
            companies=_safe_json_list(row["companies"]),
            max_results_per_source=int(row["max_results_per_source"] or 50),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_at=row["last_run_at"],
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> SearchRunModel:
        return SearchRunModel(
            run_id=row["run_id"],
            preference_id=row["preference_id"],
            preference_label=row["preference_label"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            total_candidates=row["total_candidates"],
            new_candidates=row["new_candidates"],
            duplicate_count=row["duplicate_count"],
            warnings=_safe_json_list(row["warnings"]),
            error_message=row["error_message"],
        )

    @staticmethod
    def _row_to_candidate(row: sqlite3.Row) -> JobCandidateModel:
        return JobCandidateModel(
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            source=row["source"],
            source_url=row["source_url"],
            company=row["company"],
            role=row["role"],
            location=row["location"],
            salary=row["salary"],
            remote=row["remote"],
            posted_date=row["posted_date"],
            apply_url=row["apply_url"],
            discovery_url=row["discovery_url"],
            extraction_method=row["extraction_method"] or "ats_api",
            source_confidence=row["source_confidence"] or "high",
            search_rank=int(row["search_rank"] or 0),
            identity_key=row["identity_key"],
            is_duplicate=bool(row["is_duplicate"]),
            duplicate_of_candidate_id=row["duplicate_of_candidate_id"],
            ingested=bool(row["ingested"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_list(row: sqlite3.Row) -> JobListModel:
        return JobListModel(
            list_id=row["list_id"],
            run_id=row["run_id"],
            label=row["label"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_list_item_with_candidate(row: sqlite3.Row) -> JobListItemDisplayModel:
        return JobListItemDisplayModel(
            item_id=row["item_id"],
            list_id=row["list_id"],
            candidate_id=row["candidate_id"],
            position=row["position"],
            notes=row["notes"],
            priority=row["priority"],
            status=row["status"],
            promoted=bool(row["promoted"]),
            created_at=row["created_at"],
            source=row["source"],
            source_url=row["source_url"],
            company=row["company"],
            role=row["role"],
            location=row["location"],
            salary=row["salary"],
            remote=row["remote"],
            posted_date=row["posted_date"],
            apply_url=row["apply_url"],
            discovery_url=row["discovery_url"],
            extraction_method=row["extraction_method"] or "ats_api",
            source_confidence=row["source_confidence"] or "high",
            search_rank=int(row["search_rank"] or 0),
            identity_key=row["identity_key"],
            is_duplicate=bool(row["is_duplicate"]),
            ingested=bool(row["ingested"]),
        )


_search_store: Optional[SearchStore] = None


def get_search_store() -> SearchStore:
    global _search_store
    if _search_store is None:
        _search_store = SearchStore()
    return _search_store
