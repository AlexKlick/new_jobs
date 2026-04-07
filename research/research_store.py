"""
Research Store - SQLite-backed persistence for company research snapshots,
claims, and interview questions.

Stores:
- ResearchCompany: company identity keyed by normalized slug
- ResearchSnapshot: immutable timestamped snapshot of research data
- ResearchClaim: normalized claim extracted from a snapshot
- ResearchInterviewQuestion: interview question extracted from a snapshot
- ResearchRefresh: refresh lifecycle tracking (pending -> running -> completed/failed)

Snapshots are immutable once persisted. Raw artifacts are retained on the
filesystem under outputs/research/{company_key}/ for later re-normalization.
"""

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.resolve()
RESEARCH_DIR = PROJECT_ROOT / "research"
RESEARCH_DB = RESEARCH_DIR / "research.db"
RESEARCH_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "research"

STALE_THRESHOLD_DAYS = 7
VERY_STALE_THRESHOLD_DAYS = 30


# ── Pydantic Models ────────────────────────────────────────────────────────────

class ResearchSnapshotModel(BaseModel):
    snapshot_id: str
    company_key: str
    collected_at: str
    source_count: int = 0
    claim_count: int = 0
    question_count: int = 0
    status: str = "pending"
    error_message: Optional[str] = None
    artifact_paths: list[str] = []
    created_at: str


class ResearchClaimModel(BaseModel):
    claim_id: str
    snapshot_id: str
    company_key: str
    claim_text: str
    source_url: str
    collected_at: str
    confidence: str = "medium"
    themes: list[str] = []
    sentiment_score: Optional[float] = None
    role_applicability: list[str] = []
    created_at: str


class InterviewQuestionModel(BaseModel):
    question_id: str
    snapshot_id: str
    company_key: str
    question_text: str
    source_url: str
    collected_at: str
    role_applicability: list[str] = []
    themes: list[str] = []
    created_at: str


class ResearchRefreshModel(BaseModel):
    refresh_id: str
    company_key: str
    status: str = "pending"
    started_at: str
    completed_at: Optional[str] = None
    current_source: Optional[str] = None
    sources_total: int = 0
    sources_completed: int = 0
    error_message: Optional[str] = None


# ── Database Schema ───────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_companies (
    company_key      TEXT PRIMARY KEY,
    company_name     TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_snapshots (
    snapshot_id      TEXT PRIMARY KEY,
    company_key      TEXT NOT NULL REFERENCES research_companies(company_key),
    collected_at     TEXT NOT NULL,
    source_count     INTEGER NOT NULL DEFAULT 0,
    claim_count      INTEGER NOT NULL DEFAULT 0,
    question_count   INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending',
    error_message    TEXT,
    artifact_paths   TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_claims (
    claim_id         TEXT PRIMARY KEY,
    snapshot_id      TEXT NOT NULL REFERENCES research_snapshots(snapshot_id),
    company_key      TEXT NOT NULL REFERENCES research_companies(company_key),
    claim_text       TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    collected_at     TEXT NOT NULL,
    confidence       TEXT NOT NULL DEFAULT 'medium',
    themes           TEXT NOT NULL DEFAULT '[]',
    sentiment_score  REAL,
    role_applicability TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_interview_questions (
    question_id      TEXT PRIMARY KEY,
    snapshot_id      TEXT NOT NULL REFERENCES research_snapshots(snapshot_id),
    company_key      TEXT NOT NULL REFERENCES research_companies(company_key),
    question_text    TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    collected_at     TEXT NOT NULL,
    role_applicability TEXT NOT NULL DEFAULT '[]',
    themes           TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_refreshes (
    refresh_id       TEXT PRIMARY KEY,
    company_key      TEXT NOT NULL REFERENCES research_companies(company_key),
    status           TEXT NOT NULL DEFAULT 'pending',
    started_at       TEXT NOT NULL,
    completed_at     TEXT,
    current_source   TEXT,
    sources_total    INTEGER NOT NULL DEFAULT 0,
    sources_completed INTEGER NOT NULL DEFAULT 0,
    error_message    TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_company ON research_snapshots(company_key);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON research_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_claims_snapshot ON research_claims(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_claims_company ON research_claims(company_key);
CREATE INDEX IF NOT EXISTS idx_questions_snapshot ON research_interview_questions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_questions_company ON research_interview_questions(company_key);
CREATE INDEX IF NOT EXISTS idx_refreshes_company ON research_refreshes(company_key);
CREATE INDEX IF NOT EXISTS idx_refreshes_status ON research_refreshes(status);
"""


def _get_db() -> sqlite3.Connection:
    """Get a connection to the research database."""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RESEARCH_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _compute_company_key(name: str) -> str:
    """Normalize a company name to a consistent slug key."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "unknown-company"


def _compute_stale_days(last_refreshed_at: Optional[str]) -> Optional[int]:
    """Compute days since last refresh. Returns None if never refreshed."""
    if last_refreshed_at is None:
        return None
    try:
        refreshed = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - refreshed).days
    except (ValueError, TypeError):
        return None


def _is_stale(stale_days: Optional[int]) -> bool:
    """Return True if the research is stale (7+ days since last refresh)."""
    return stale_days is not None and stale_days >= STALE_THRESHOLD_DAYS


def _summarize_sentiment(claims: list[dict]) -> Optional[float]:
    """Compute average sentiment over claims that include a score."""
    values = [claim["sentiment_score"] for claim in claims if claim.get("sentiment_score") is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 3)


# ── Store Class ────────────────────────────────────────────────────────────────

class ResearchStore:
    """SQLite-backed store for company research data."""

    def __init__(self) -> None:
        self._db_path = RESEARCH_DB
        with _get_db() as conn:
            pass  # Ensure schema is initialized

    # ── Company Operations ──────────────────────────────────────────────────

    def ensure_company(self, company_key: str, company_name: str) -> None:
        """Create a company record if it does not exist."""
        now = datetime.now(timezone.utc).isoformat()
        with _get_db() as conn:
            existing = conn.execute(
                "SELECT company_key FROM research_companies WHERE company_key = ?",
                (company_key,),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO research_companies (company_key, company_name, created_at) "
                    "VALUES (?, ?, ?)",
                    (company_key, company_name, now),
                )

    def get_company_name(self, company_key: str) -> Optional[str]:
        """Get the display name for a company key."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT company_name FROM research_companies WHERE company_key = ?",
                (company_key,),
            ).fetchone()
            return row["company_name"] if row else None

    def list_companies(self) -> list[dict]:
        """List all companies with last refreshed metadata and counts."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT c.company_key, c.company_name, "
                "  (SELECT s.collected_at FROM research_snapshots s "
                "   WHERE s.company_key = c.company_key AND s.status = 'completed' "
                "   ORDER BY s.collected_at DESC LIMIT 1) AS last_refreshed_at, "
                "  (SELECT s.snapshot_id FROM research_snapshots s "
                "   WHERE s.company_key = c.company_key AND s.status = 'completed' "
                "   ORDER BY s.collected_at DESC LIMIT 1) AS latest_snapshot_id, "
                "  (SELECT COUNT(*) FROM research_claims r "
                "   WHERE r.company_key = c.company_key) AS claim_count, "
                "  (SELECT COUNT(*) FROM research_interview_questions q "
                "   WHERE q.company_key = c.company_key) AS question_count "
                "FROM research_companies c "
                "ORDER BY c.company_name"
            ).fetchall()

            companies = []
            for row in rows:
                stale_days = _compute_stale_days(row["last_refreshed_at"])
                claims = self._get_claims_for_company(row["company_key"])
                companies.append({
                    "company_key": row["company_key"],
                    "company_name": row["company_name"],
                    "last_refreshed_at": row["last_refreshed_at"],
                    "is_stale": _is_stale(stale_days),
                    "stale_days": stale_days,
                    "claim_count": row["claim_count"],
                    "question_count": row["question_count"],
                    "latest_snapshot_id": row["latest_snapshot_id"],
                    "average_sentiment": _summarize_sentiment(claims),
                })
            return companies

    def get_company_detail(self, company_key: str) -> Optional[dict]:
        """Get full company research with claims, questions, and snapshot history."""
        with _get_db() as conn:
            company_row = conn.execute(
                "SELECT company_key, company_name FROM research_companies "
                "WHERE company_key = ?",
                (company_key,),
            ).fetchone()
            if not company_row:
                return None

            company_name = company_row["company_name"]

            # Last refreshed timestamp
            last_refreshed_row = conn.execute(
                "SELECT collected_at FROM research_snapshots "
                "WHERE company_key = ? AND status = 'completed' "
                "ORDER BY collected_at DESC LIMIT 1",
                (company_key,),
            ).fetchone()
            last_refreshed_at = last_refreshed_row["collected_at"] if last_refreshed_row else None

            # Snapshot summaries
            snap_rows = conn.execute(
                "SELECT snapshot_id, collected_at, source_count, claim_count, question_count "
                "FROM research_snapshots "
                "WHERE company_key = ? AND status = 'completed' "
                "ORDER BY collected_at DESC",
                (company_key,),
            ).fetchall()
            snapshots = [
                {
                    "snapshot_id": r["snapshot_id"],
                    "collected_at": r["collected_at"],
                    "source_count": r["source_count"],
                    "claim_count": r["claim_count"],
                    "question_count": r["question_count"],
                }
                for r in snap_rows
            ]

            # Claims
            claims = self._get_claims_for_company(company_key)

            # Questions
            questions = self._get_questions_for_company(company_key)

            stale_days = _compute_stale_days(last_refreshed_at)
            return {
                "company_key": company_key,
                "company_name": company_name,
                "last_refreshed_at": last_refreshed_at,
                "is_stale": _is_stale(stale_days),
                "stale_days": stale_days,
                "claim_count": len(claims),
                "question_count": len(questions),
                "average_sentiment": _summarize_sentiment(claims),
                "claims": claims,
                "questions": questions,
                "snapshots": snapshots,
            }

    # ── Snapshot Operations ────────────────────────────────────────────────

    def create_snapshot(
        self,
        company_key: str,
        source_count: int = 0,
        artifact_paths: Optional[list[str]] = None,
    ) -> ResearchSnapshotModel:
        """Create a new research snapshot in pending state."""
        now = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO research_snapshots "
                "(snapshot_id, company_key, collected_at, source_count, "
                "claim_count, question_count, status, artifact_paths, created_at) "
                "VALUES (?, ?, ?, ?, 0, 0, 'pending', ?, ?)",
                (snapshot_id, company_key, now, source_count,
                 json.dumps(artifact_paths or []), now),
            )

        return ResearchSnapshotModel(
            snapshot_id=snapshot_id,
            company_key=company_key,
            collected_at=now,
            source_count=source_count,
            claim_count=0,
            question_count=0,
            status="pending",
            artifact_paths=artifact_paths or [],
            created_at=now,
        )

    def complete_snapshot(
        self,
        snapshot_id: str,
        claim_count: int,
        question_count: int,
    ) -> None:
        """Mark a snapshot as completed with final counts."""
        with _get_db() as conn:
            conn.execute(
                "UPDATE research_snapshots "
                "SET claim_count = ?, question_count = ?, status = 'completed' "
                "WHERE snapshot_id = ?",
                (claim_count, question_count, snapshot_id),
            )

    def fail_snapshot(self, snapshot_id: str, error_message: str) -> None:
        """Mark a snapshot as failed."""
        with _get_db() as conn:
            conn.execute(
                "UPDATE research_snapshots "
                "SET status = 'failed', error_message = ? "
                "WHERE snapshot_id = ?",
                (error_message, snapshot_id),
            )

    def list_snapshots(self, company_key: str) -> list[ResearchSnapshotModel]:
        """List all snapshots for a company, newest first."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT snapshot_id, company_key, collected_at, source_count, "
                "claim_count, question_count, status, error_message, "
                "artifact_paths, created_at "
                "FROM research_snapshots "
                "WHERE company_key = ? "
                "ORDER BY collected_at DESC",
                (company_key,),
            ).fetchall()
            return [self._row_to_snapshot(r) for r in rows]

    # ── Claim Operations ──────────────────────────────────────────────────

    def add_claim(
        self,
        snapshot_id: str,
        company_key: str,
        claim_text: str,
        source_url: str,
        collected_at: str,
        confidence: str = "medium",
        themes: Optional[list[str]] = None,
        sentiment_score: Optional[float] = None,
        role_applicability: Optional[list[str]] = None,
    ) -> ResearchClaimModel:
        """Add a research claim."""
        now = datetime.now(timezone.utc).isoformat()
        claim_id = f"claim-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO research_claims "
                "(claim_id, snapshot_id, company_key, claim_text, source_url, "
                "collected_at, confidence, themes, sentiment_score, "
                "role_applicability, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, snapshot_id, company_key, claim_text, source_url,
                 collected_at, confidence, json.dumps(themes or []),
                 sentiment_score,
                 json.dumps(role_applicability or []), now),
            )

        return ResearchClaimModel(
            claim_id=claim_id,
            snapshot_id=snapshot_id,
            company_key=company_key,
            claim_text=claim_text,
            source_url=source_url,
            collected_at=collected_at,
            confidence=confidence,
            themes=themes or [],
            sentiment_score=sentiment_score,
            role_applicability=role_applicability or [],
            created_at=now,
        )

    def _get_claims_for_company(self, company_key: str) -> list[dict]:
        """Get all claims for a company as dicts."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT claim_id, snapshot_id, company_key, claim_text, source_url, "
                "collected_at, confidence, themes, sentiment_score, "
                "role_applicability, created_at "
                "FROM research_claims "
                "WHERE company_key = ? "
                "ORDER BY collected_at DESC",
                (company_key,),
            ).fetchall()
            return [self._row_to_claim_dict(r) for r in rows]

    def get_claims_for_snapshot(self, snapshot_id: str) -> list[ResearchClaimModel]:
        """Get all claims for a snapshot."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT claim_id, snapshot_id, company_key, claim_text, source_url, "
                "collected_at, confidence, themes, sentiment_score, "
                "role_applicability, created_at "
                "FROM research_claims WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()
            return [self._row_to_claim(r) for r in rows]

    # ── Interview Question Operations ──────────────────────────────────────

    def add_interview_question(
        self,
        snapshot_id: str,
        company_key: str,
        question_text: str,
        source_url: str,
        collected_at: str,
        role_applicability: Optional[list[str]] = None,
        themes: Optional[list[str]] = None,
    ) -> InterviewQuestionModel:
        """Add an interview question."""
        now = datetime.now(timezone.utc).isoformat()
        question_id = f"iq-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO research_interview_questions "
                "(question_id, snapshot_id, company_key, question_text, source_url, "
                "collected_at, role_applicability, themes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (question_id, snapshot_id, company_key, question_text, source_url,
                 collected_at, json.dumps(role_applicability or []),
                 json.dumps(themes or []), now),
            )

        return InterviewQuestionModel(
            question_id=question_id,
            snapshot_id=snapshot_id,
            company_key=company_key,
            question_text=question_text,
            source_url=source_url,
            collected_at=collected_at,
            role_applicability=role_applicability or [],
            themes=themes or [],
            created_at=now,
        )

    def _get_questions_for_company(self, company_key: str) -> list[dict]:
        """Get all questions for a company as dicts."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT question_id, snapshot_id, company_key, question_text, source_url, "
                "collected_at, role_applicability, themes, created_at "
                "FROM research_interview_questions "
                "WHERE company_key = ? "
                "ORDER BY collected_at DESC",
                (company_key,),
            ).fetchall()
            return [self._row_to_question_dict(r) for r in rows]

    # ── Refresh Operations ────────────────────────────────────────────────

    def create_refresh(self, company_key: str, sources_total: int = 2) -> ResearchRefreshModel:
        """Create a new refresh record."""
        now = datetime.now(timezone.utc).isoformat()
        refresh_id = f"refresh-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO research_refreshes "
                "(refresh_id, company_key, status, started_at, sources_total) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (refresh_id, company_key, now, sources_total),
            )

        return ResearchRefreshModel(
            refresh_id=refresh_id,
            company_key=company_key,
            status="pending",
            started_at=now,
            sources_total=sources_total,
        )

    def update_refresh(
        self,
        refresh_id: str,
        status: str,
        current_source: Optional[str] = None,
        sources_completed: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update a refresh record's state."""
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if status in ("completed", "failed") else None

        with _get_db() as conn:
            conn.execute(
                "UPDATE research_refreshes "
                "SET status = ?, "
                "    current_source = COALESCE(?, current_source), "
                "    sources_completed = COALESCE(?, sources_completed), "
                "    error_message = ?, "
                "    completed_at = ? "
                "WHERE refresh_id = ?",
                (status, current_source, sources_completed, error_message,
                 completed_at, refresh_id),
            )

    def get_refresh(self, refresh_id: str) -> Optional[ResearchRefreshModel]:
        """Get a refresh record by ID."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT refresh_id, company_key, status, started_at, completed_at, "
                "current_source, sources_total, sources_completed, error_message "
                "FROM research_refreshes WHERE refresh_id = ?",
                (refresh_id,),
            ).fetchone()
            return self._row_to_refresh(row) if row else None

    def get_active_refresh(self, company_key: str) -> Optional[ResearchRefreshModel]:
        """Get the active (pending or running) refresh for a company."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT refresh_id, company_key, status, started_at, completed_at, "
                "current_source, sources_total, sources_completed, error_message "
                "FROM research_refreshes "
                "WHERE company_key = ? AND status IN ('pending', 'running') "
                "ORDER BY started_at DESC LIMIT 1",
                (company_key,),
            ).fetchone()
            return self._row_to_refresh(row) if row else None

    # ── Row Converters ────────────────────────────────────────────────────

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> ResearchSnapshotModel:
        return ResearchSnapshotModel(
            snapshot_id=row["snapshot_id"],
            company_key=row["company_key"],
            collected_at=row["collected_at"],
            source_count=row["source_count"],
            claim_count=row["claim_count"],
            question_count=row["question_count"],
            status=row["status"],
            error_message=row["error_message"],
            artifact_paths=json.loads(row["artifact_paths"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> ResearchClaimModel:
        return ResearchClaimModel(
            claim_id=row["claim_id"],
            snapshot_id=row["snapshot_id"],
            company_key=row["company_key"],
            claim_text=row["claim_text"],
            source_url=row["source_url"],
            collected_at=row["collected_at"],
            confidence=row["confidence"],
            themes=json.loads(row["themes"]),
            sentiment_score=row["sentiment_score"],
            role_applicability=json.loads(row["role_applicability"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_claim_dict(row: sqlite3.Row) -> dict:
        return {
            "claim_id": row["claim_id"],
            "snapshot_id": row["snapshot_id"],
            "company_key": row["company_key"],
            "claim_text": row["claim_text"],
            "source_url": row["source_url"],
            "collected_at": row["collected_at"],
            "confidence": row["confidence"],
            "themes": json.loads(row["themes"]),
            "sentiment_score": row["sentiment_score"],
            "role_applicability": json.loads(row["role_applicability"]),
        }

    @staticmethod
    def _row_to_question_dict(row: sqlite3.Row) -> dict:
        return {
            "question_id": row["question_id"],
            "snapshot_id": row["snapshot_id"],
            "company_key": row["company_key"],
            "question_text": row["question_text"],
            "source_url": row["source_url"],
            "collected_at": row["collected_at"],
            "role_applicability": json.loads(row["role_applicability"]),
            "themes": json.loads(row["themes"]),
        }

    @staticmethod
    def _row_to_refresh(row: sqlite3.Row) -> ResearchRefreshModel:
        return ResearchRefreshModel(
            refresh_id=row["refresh_id"],
            company_key=row["company_key"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            current_source=row["current_source"],
            sources_total=row["sources_total"],
            sources_completed=row["sources_completed"],
            error_message=row["error_message"],
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_research_store: Optional[ResearchStore] = None


def get_research_store() -> ResearchStore:
    """Get or create the research store singleton."""
    global _research_store
    if _research_store is None:
        _research_store = ResearchStore()
    return _research_store


def compute_company_key(name: str) -> str:
    """Public helper to normalize company name to a key."""
    return _compute_company_key(name)
