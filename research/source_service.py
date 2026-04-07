"""
Source Record Service

SQLite-backed metadata store for source records with revision history.
Stores artifact files on disk under `sources/` directory.

Provides CRUD for source records, revision tracking, and archetype definitions.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
from pydantic import BaseModel, Field

from db.runtime import get_runtime_pool, runtime_pool_enabled
from graph.career_event_bus import emit_career_event

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.resolve()
SOURCES_DIR = PROJECT_ROOT / "sources"
SOURCES_DB = SOURCES_DIR / "source_metadata.db"

# ── Archetype Definitions ─────────────────────────────────────────────────────

ARCHETYPE_DEFINITIONS = {
    "new_grad": {
        "archetype": "new_grad",
        "label": "New Graduate",
        "description": "Profile for recent graduates emphasizing education, projects, and potential.",
        "fields": [
            {"field_id": "full_name", "label": "Full Name", "category": "identity", "order": 1, "placeholder": "e.g. Alex Klick", "required": True},
            {"field_id": "email", "label": "Email", "category": "identity", "order": 2, "placeholder": "e.g. alex@example.com", "required": True},
            {"field_id": "phone", "label": "Phone", "category": "identity", "order": 3, "placeholder": "e.g. +1-555-000-0000", "required": False},
            {"field_id": "location", "label": "Location", "category": "identity", "order": 4, "placeholder": "e.g. Denver, CO", "required": False},
            {"field_id": "linkedin", "label": "LinkedIn URL", "category": "identity", "order": 5, "placeholder": "e.g. linkedin.com/in/your-name", "required": False},
            {"field_id": "university", "label": "University", "category": "education", "order": 1, "placeholder": "e.g. University of Michigan", "required": True},
            {"field_id": "degree", "label": "Degree", "category": "education", "order": 2, "placeholder": "e.g. B.S. Computer Science", "required": True},
            {"field_id": "graduation", "label": "Graduation Date", "category": "education", "order": 3, "placeholder": "e.g. May 2026", "required": True},
            {"field_id": "gpa", "label": "GPA", "category": "education", "order": 4, "placeholder": "e.g. 3.8/4.0", "required": False},
            {"field_id": "relevant_coursework", "label": "Relevant Coursework", "category": "education", "order": 5, "placeholder": "e.g. Data Structures, ML, NLP", "required": False},
            {"field_id": "project_1", "label": "Project 1", "category": "projects", "order": 1, "placeholder": "Name and description of a key project", "required": False},
            {"field_id": "project_2", "label": "Project 2", "category": "projects", "order": 2, "placeholder": "Name and description of a key project", "required": False},
            {"field_id": "project_3", "label": "Project 3", "category": "projects", "order": 3, "placeholder": "Name and description of a key project", "required": False},
            {"field_id": "internship_1", "label": "Internship 1", "category": "experience", "order": 1, "placeholder": "Company, role, dates, key contributions", "required": False},
            {"field_id": "internship_2", "label": "Internship 2", "category": "experience", "order": 2, "placeholder": "Company, role, dates, key contributions", "required": False},
            {"field_id": "technical_skills", "label": "Technical Skills", "category": "skills", "order": 1, "placeholder": "e.g. Python, TypeScript, React, PyTorch", "required": True},
            {"field_id": "soft_skills", "label": "Soft Skills", "category": "skills", "order": 2, "placeholder": "e.g. Communication, Team Leadership", "required": False},
            {"field_id": "certifications", "label": "Certifications", "category": "skills", "order": 3, "placeholder": "e.g. AWS Solutions Architect", "required": False},
            {"field_id": "career_objective", "label": "Career Objective", "category": "preferences", "order": 1, "placeholder": "What kind of role are you targeting?", "required": False},
            {"field_id": "preferred_locations", "label": "Preferred Locations", "category": "preferences", "order": 2, "placeholder": "e.g. Remote, Denver, Austin", "required": False},
        ],
    },
    "experienced": {
        "archetype": "experienced",
        "label": "Experienced Professional",
        "description": "Profile for experienced professionals emphasizing work history, achievements, and leadership.",
        "fields": [
            {"field_id": "full_name", "label": "Full Name", "category": "identity", "order": 1, "placeholder": "e.g. Alex Klick", "required": True},
            {"field_id": "email", "label": "Email", "category": "identity", "order": 2, "placeholder": "e.g. alex@example.com", "required": True},
            {"field_id": "phone", "label": "Phone", "category": "identity", "order": 3, "placeholder": "e.g. +1-555-000-0000", "required": False},
            {"field_id": "location", "label": "Location", "category": "identity", "order": 4, "placeholder": "e.g. Denver, CO", "required": False},
            {"field_id": "linkedin", "label": "LinkedIn URL", "category": "identity", "order": 5, "placeholder": "e.g. linkedin.com/in/your-name", "required": False},
            {"field_id": "current_title", "label": "Current Title", "category": "identity", "order": 6, "placeholder": "e.g. Senior AI Consultant", "required": False},
            {"field_id": "role_1", "label": "Role 1 (Most Recent)", "category": "experience", "order": 1, "placeholder": "Company, title, dates, key achievements", "required": True},
            {"field_id": "role_2", "label": "Role 2", "category": "experience", "order": 2, "placeholder": "Company, title, dates, key achievements", "required": False},
            {"field_id": "role_3", "label": "Role 3", "category": "experience", "order": 3, "placeholder": "Company, title, dates, key achievements", "required": False},
            {"field_id": "role_4", "label": "Role 4", "category": "experience", "order": 4, "placeholder": "Company, title, dates, key achievements", "required": False},
            {"field_id": "education", "label": "Education", "category": "education", "order": 1, "placeholder": "Degree, university, year", "required": True},
            {"field_id": "certifications", "label": "Certifications", "category": "education", "order": 2, "placeholder": "e.g. AWS Solutions Architect, PMP", "required": False},
            {"field_id": "technical_skills", "label": "Technical Skills", "category": "skills", "order": 1, "placeholder": "e.g. Python, TypeScript, React, PyTorch", "required": True},
            {"field_id": "domain_expertise", "label": "Domain Expertise", "category": "skills", "order": 2, "placeholder": "e.g. Financial Services, Healthcare, AI/ML", "required": False},
            {"field_id": "leadership", "label": "Leadership Experience", "category": "skills", "order": 3, "placeholder": "Team size, scope, management style", "required": False},
            {"field_id": "key_achievements", "label": "Key Achievements", "category": "achievements", "order": 1, "placeholder": "Top 3-5 quantified achievements", "required": False},
            {"field_id": "publications", "label": "Publications / Patents", "category": "achievements", "order": 2, "placeholder": "Notable publications or patents", "required": False},
            {"field_id": "career_objective", "label": "Career Objective", "category": "preferences", "order": 1, "placeholder": "What is your next career goal?", "required": False},
            {"field_id": "preferred_locations", "label": "Preferred Locations", "category": "preferences", "order": 2, "placeholder": "e.g. Remote, Denver, Austin", "required": False},
            {"field_id": "salary_range", "label": "Salary Range", "category": "preferences", "order": 3, "placeholder": "e.g. $150k-200k", "required": False},
        ],
    },
}


# ── Pydantic Models ────────────────────────────────────────────────────────────

class SourceFieldValueModel(BaseModel):
    field_id: str
    label: str
    value: str
    category: str
    order: int


class SourceRecordModel(BaseModel):
    record_id: str
    archetype: str
    label: str
    fields: list[SourceFieldValueModel]
    created_at: str
    updated_at: str
    revision_count: int = 0


class SourceRevisionModel(BaseModel):
    revision_id: str
    record_id: str
    created_at: str
    provenance: str
    summary: str
    field_count: int
    snapshot: str  # JSON blob of the fields at this revision


class SourceSuggestionModel(BaseModel):
    suggestion_id: str
    record_id: str
    field_id: str
    field_label: str
    current_value: str
    suggested_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_note: str


class NoteExtractionResultModel(BaseModel):
    suggestions: list[SourceSuggestionModel]
    note_text: str
    created_at: str


# ── Database Layer ─────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_records (
    record_id   TEXT PRIMARY KEY,
    archetype   TEXT NOT NULL,
    label       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    revision_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_fields (
    field_id    TEXT NOT NULL,
    record_id   TEXT NOT NULL REFERENCES source_records(record_id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    field_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (record_id, field_id)
);

CREATE TABLE IF NOT EXISTS source_revisions (
    revision_id TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL REFERENCES source_records(record_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    field_count INTEGER NOT NULL DEFAULT 0,
    snapshot    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_fields_record ON source_fields(record_id);
CREATE INDEX IF NOT EXISTS idx_revisions_record ON source_revisions(record_id);
CREATE INDEX IF NOT EXISTS idx_revisions_created ON source_revisions(created_at);
"""


def _get_db() -> sqlite3.Connection:
    """Get a connection to the source metadata database."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SOURCES_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


# ── Service Class ──────────────────────────────────────────────────────────────

class SourceService:
    """Manages source records, revisions, and archetype definitions."""

    def __init__(self) -> None:
        self._db_path = SOURCES_DB
        # Ensure schema is initialized
        with _get_db() as conn:
            pass

    # ── Archetype Definitions ──────────────────────────────────────────────

    def list_archetypes(self) -> list[dict]:
        """Return all archetype definitions."""
        return list(ARCHETYPE_DEFINITIONS.values())

    def get_archetype(self, archetype: str) -> Optional[dict]:
        """Return a single archetype definition by name."""
        return ARCHETYPE_DEFINITIONS.get(archetype)

    # ── CRUD ───────────────────────────────────────────────────────────────

    def list_records(self) -> list[SourceRecordModel]:
        """Return all source records with their fields."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                "FROM source_records ORDER BY updated_at DESC"
            ).fetchall()
            records = []
            for row in rows:
                fields = self._load_fields(conn, row["record_id"])
                records.append(SourceRecordModel(
                    record_id=row["record_id"],
                    archetype=row["archetype"],
                    label=row["label"],
                    fields=fields,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    revision_count=row["revision_count"],
                ))
            return records

    def get_record(self, record_id: str) -> Optional[SourceRecordModel]:
        """Return a single source record by ID."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                "FROM source_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                return None
            fields = self._load_fields(conn, record_id)
            return SourceRecordModel(
                record_id=row["record_id"],
                archetype=row["archetype"],
                label=row["label"],
                fields=fields,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                revision_count=row["revision_count"],
            )

    def create_record(self, archetype: str, label: str) -> SourceRecordModel:
        """Create a new source record with empty archetype fields."""
        arch = ARCHETYPE_DEFINITIONS.get(archetype)
        if not arch:
            raise ValueError(f"Unknown archetype: {archetype}")

        now = datetime.now(timezone.utc).isoformat()
        record_id = f"src-{uuid.uuid4().hex[:12]}"

        with _get_db() as conn:
            conn.execute(
                "INSERT INTO source_records (record_id, archetype, label, created_at, updated_at, revision_count) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (record_id, archetype, label, now, now),
            )
            # Insert empty field rows from the archetype schema
            for field_def in arch["fields"]:
                conn.execute(
                    "INSERT INTO source_fields (field_id, record_id, label, value, category, field_order) "
                    "VALUES (?, ?, ?, '', ?, ?)",
                    (field_def["field_id"], record_id, field_def["label"],
                     field_def["category"], field_def["order"]),
                )

        record = self.get_record(record_id)
        if record:
            try:
                emit_career_event(
                    category="source",
                    action="source_record_created",
                    entity_id=record_id,
                    entity_type="source_record",
                    payload={"archetype": archetype, "field_ids": [f.field_id for f in record.fields]},
                )
            except Exception:
                logger.warning("Failed to emit graph event for source record_created", exc_info=True)
        return record  # type: ignore[return-value]

    def update_record(self, record_id: str, label: Optional[str], fields: list[dict],
                      provenance: str = "manual_edit") -> Optional[SourceRecordModel]:
        """Update a source record's fields, creating a revision snapshot."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                "FROM source_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                return None

            # Snapshot the current fields before update
            old_fields = self._load_fields(conn, record_id)
            snapshot = json.dumps([f.model_dump() for f in old_fields])

            now = datetime.now(timezone.utc).isoformat()
            new_rev = row["revision_count"] + 1

            # Update label if provided
            effective_label = label if label is not None else row["label"]
            conn.execute(
                "UPDATE source_records SET label = ?, updated_at = ?, revision_count = ? "
                "WHERE record_id = ?",
                (effective_label, now, new_rev, record_id),
            )

            # Update field values
            changed_fields = []
            for field_update in fields:
                fid = field_update.get("field_id")
                val = field_update.get("value", "")
                # Check if value actually changed
                old_val = next((f.value for f in old_fields if f.field_id == fid), None)
                if old_val != val:
                    changed_fields.append(fid)
                conn.execute(
                    "UPDATE source_fields SET value = ? WHERE record_id = ? AND field_id = ?",
                    (val, record_id, fid),
                )

            # Write revision row
            summary = f"Updated {len(changed_fields)} field(s)" if changed_fields else "No field changes"
            revision_id = f"rev-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO source_revisions (revision_id, record_id, created_at, provenance, summary, field_count, snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (revision_id, record_id, now, provenance, summary,
                 len(old_fields), snapshot),
            )

            # Write artifact to disk
            self._write_artifact(record_id, effective_label, archetype=row["archetype"])

        updated = self.get_record(record_id)
        if updated:
            try:
                emit_career_event(
                    category="source",
                    action="source_record_updated",
                    entity_id=record_id,
                    entity_type="source_record",
                    payload={"archetype": updated.archetype, "field_ids_changed": changed_fields},
                )
            except Exception:
                logger.warning("Failed to emit graph event for source record_updated", exc_info=True)
        return updated

    def delete_record(self, record_id: str) -> bool:
        """Delete a source record and all associated data."""
        with _get_db() as conn:
            row = conn.execute(
                "SELECT record_id FROM source_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM source_fields WHERE record_id = ?", (record_id,))
            conn.execute("DELETE FROM source_revisions WHERE record_id = ?", (record_id,))
            conn.execute("DELETE FROM source_records WHERE record_id = ?", (record_id,))

        # Remove artifact directory
        artifact_dir = SOURCES_DIR / record_id
        if artifact_dir.exists():
            import shutil
            shutil.rmtree(artifact_dir, ignore_errors=True)

        try:
            emit_career_event(
                category="source",
                action="source_record_deleted",
                entity_id=record_id,
                entity_type="source_record",
                payload={},
            )
        except Exception:
                logger.warning("Failed to emit graph event for source record_deleted", exc_info=True)
        return True

    # ── Async Runtime Methods ─────────────────────────────────────────────

    async def list_records_async(self) -> list[SourceRecordModel]:
        """Return all source records, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.list_records()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                "FROM source_records ORDER BY updated_at DESC"
            )
            records = []
            for row in rows:
                fields = await self._load_fields_pg(conn, row["record_id"])
                records.append(
                    SourceRecordModel(
                        record_id=row["record_id"],
                        archetype=row["archetype"],
                        label=row["label"],
                        fields=fields,
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        revision_count=row["revision_count"],
                    )
                )
            return records

    async def get_record_async(self, record_id: str) -> Optional[SourceRecordModel]:
        """Return a single source record, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.get_record(record_id)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                "FROM source_records WHERE record_id = $1",
                record_id,
            )
            if row is None:
                return None
            fields = await self._load_fields_pg(conn, record_id)
            return SourceRecordModel(
                record_id=row["record_id"],
                archetype=row["archetype"],
                label=row["label"],
                fields=fields,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                revision_count=row["revision_count"],
            )

    async def create_record_async(self, archetype: str, label: str) -> SourceRecordModel:
        """Create a new source record, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.create_record(archetype, label)

        arch = ARCHETYPE_DEFINITIONS.get(archetype)
        if not arch:
            raise ValueError(f"Unknown archetype: {archetype}")

        now = datetime.now(timezone.utc).isoformat()
        record_id = f"src-{uuid.uuid4().hex[:12]}"

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO source_records (record_id, archetype, label, created_at, updated_at, revision_count) "
                    "VALUES ($1, $2, $3, $4, $5, 0)",
                    record_id,
                    archetype,
                    label,
                    now,
                    now,
                )
                await conn.executemany(
                    "INSERT INTO source_fields (field_id, record_id, label, value, category, field_order) "
                    "VALUES ($1, $2, $3, '', $4, $5)",
                    [
                        (
                            field_def["field_id"],
                            record_id,
                            field_def["label"],
                            field_def["category"],
                            field_def["order"],
                        )
                        for field_def in arch["fields"]
                    ],
                )

        record = await self.get_record_async(record_id)
        if record is None:
            raise RuntimeError(f"Created source record could not be reloaded: {record_id}")

        try:
            emit_career_event(
                category="source",
                action="source_record_created",
                entity_id=record_id,
                entity_type="source_record",
                payload={"archetype": archetype, "field_ids": [f.field_id for f in record.fields]},
            )
        except Exception:
            logger.warning("Failed to emit graph event for source record_created", exc_info=True)
        return record

    async def update_record_async(
        self,
        record_id: str,
        label: Optional[str],
        fields: list[dict],
        provenance: str = "manual_edit",
    ) -> Optional[SourceRecordModel]:
        """Update a source record, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.update_record(record_id, label, fields, provenance=provenance)

        changed_fields: list[str] = []

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT record_id, archetype, label, created_at, updated_at, revision_count "
                    "FROM source_records WHERE record_id = $1",
                    record_id,
                )
                if row is None:
                    return None

                old_fields = await self._load_fields_pg(conn, record_id)
                old_values = {field.field_id: field.value for field in old_fields}
                snapshot = json.dumps([field.model_dump() for field in old_fields])

                now = datetime.now(timezone.utc).isoformat()
                new_rev = row["revision_count"] + 1
                effective_label = label if label is not None else row["label"]

                await conn.execute(
                    "UPDATE source_records SET label = $1, updated_at = $2, revision_count = $3 "
                    "WHERE record_id = $4",
                    effective_label,
                    now,
                    new_rev,
                    record_id,
                )

                for field_update in fields:
                    field_id = field_update.get("field_id")
                    if not field_id:
                        continue
                    value = field_update.get("value", "")
                    if old_values.get(field_id) != value:
                        changed_fields.append(field_id)
                    await conn.execute(
                        "UPDATE source_fields SET value = $1 WHERE record_id = $2 AND field_id = $3",
                        value,
                        record_id,
                        field_id,
                    )

                summary = (
                    f"Updated {len(changed_fields)} field(s)"
                    if changed_fields
                    else "No field changes"
                )
                revision_id = f"rev-{uuid.uuid4().hex[:12]}"
                await conn.execute(
                    "INSERT INTO source_revisions (revision_id, record_id, created_at, provenance, summary, field_count, snapshot) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
                    revision_id,
                    record_id,
                    now,
                    provenance,
                    summary,
                    len(old_fields),
                    snapshot,
                )

                self._write_artifact(record_id, effective_label, archetype=row["archetype"])

        updated = await self.get_record_async(record_id)
        if updated is not None:
            try:
                emit_career_event(
                    category="source",
                    action="source_record_updated",
                    entity_id=record_id,
                    entity_type="source_record",
                    payload={"archetype": updated.archetype, "field_ids_changed": changed_fields},
                )
            except Exception:
                logger.warning("Failed to emit graph event for source record_updated", exc_info=True)
        return updated

    async def delete_record_async(self, record_id: str) -> bool:
        """Delete a source record, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.delete_record(record_id)

        async with pool.acquire() as conn:
            deleted = await conn.fetchval(
                "DELETE FROM source_records WHERE record_id = $1 RETURNING record_id",
                record_id,
            )
        if deleted is None:
            return False

        artifact_dir = SOURCES_DIR / record_id
        if artifact_dir.exists():
            import shutil

            shutil.rmtree(artifact_dir, ignore_errors=True)

        try:
            emit_career_event(
                category="source",
                action="source_record_deleted",
                entity_id=record_id,
                entity_type="source_record",
                payload={},
            )
        except Exception:
            logger.warning("Failed to emit graph event for source record_deleted", exc_info=True)
        return True

    async def list_revisions_async(self, record_id: str) -> list[SourceRevisionModel]:
        """Return revision history for a record, using PostgreSQL when configured."""
        pool = get_runtime_pool()
        if not runtime_pool_enabled() or pool is None:
            return self.list_revisions(record_id)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT revision_id, record_id, created_at, provenance, summary, field_count, snapshot::text AS snapshot "
                "FROM source_revisions WHERE record_id = $1 ORDER BY created_at DESC",
                record_id,
            )
            return [
                SourceRevisionModel(
                    revision_id=row["revision_id"],
                    record_id=row["record_id"],
                    created_at=row["created_at"],
                    provenance=row["provenance"],
                    summary=row["summary"],
                    field_count=row["field_count"],
                    snapshot=row["snapshot"],
                )
                for row in rows
            ]

    async def extract_suggestions_async(
        self,
        record_id: str,
        note_text: str,
    ) -> NoteExtractionResultModel:
        """Parse freeform notes into structured suggestions."""
        if not runtime_pool_enabled() or get_runtime_pool() is None:
            return self.extract_suggestions(record_id, note_text)

        record = await self.get_record_async(record_id)
        if not record:
            raise ValueError(f"Record not found: {record_id}")

        suggestions: list[SourceSuggestionModel] = []
        now = datetime.now(timezone.utc).isoformat()

        for field in record.fields:
            label_words = field.label.lower().split()
            for line in note_text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                line_lower = line_stripped.lower()
                if any(word in line_lower for word in label_words if len(word) > 2):
                    value = line_stripped
                    if ":" in line_stripped:
                        value = line_stripped.split(":", 1)[1].strip()
                    elif " is " in line_lower:
                        value = line_stripped.split(" is ", 1)[1].strip()
                    if value and value != field.value:
                        suggestions.append(
                            SourceSuggestionModel(
                                suggestion_id=f"sug-{uuid.uuid4().hex[:8]}",
                                record_id=record_id,
                                field_id=field.field_id,
                                field_label=field.label,
                                current_value=field.value,
                                suggested_value=value,
                                confidence=0.6,
                                source_note=line_stripped,
                            )
                        )
                    break

        return NoteExtractionResultModel(
            suggestions=suggestions,
            note_text=note_text,
            created_at=now,
        )

    async def apply_suggestion_async(
        self,
        suggestion: SourceSuggestionModel,
    ) -> Optional[SourceRecordModel]:
        """Apply a single suggestion, updating the record and creating a revision."""
        if not runtime_pool_enabled() or get_runtime_pool() is None:
            return self.apply_suggestion(suggestion)

        return await self.update_record_async(
            record_id=suggestion.record_id,
            label=None,
            fields=[{"field_id": suggestion.field_id, "value": suggestion.suggested_value}],
            provenance="note_extraction",
        )

    # ── Revisions ──────────────────────────────────────────────────────────

    def list_revisions(self, record_id: str) -> list[SourceRevisionModel]:
        """Return revision history for a record."""
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT revision_id, record_id, created_at, provenance, summary, field_count, snapshot "
                "FROM source_revisions WHERE record_id = ? ORDER BY created_at DESC",
                (record_id,),
            ).fetchall()
            return [
                SourceRevisionModel(
                    revision_id=r["revision_id"],
                    record_id=r["record_id"],
                    created_at=r["created_at"],
                    provenance=r["provenance"],
                    summary=r["summary"],
                    field_count=r["field_count"],
                    snapshot=r["snapshot"],
                )
                for r in rows
            ]

    # ── Note Extraction (simplified) ───────────────────────────────────────

    def extract_suggestions(self, record_id: str, note_text: str) -> NoteExtractionResultModel:
        """
        Parse freeform notes into structured suggestions.

        This is a heuristic extraction that looks for patterns like:
        "field_name: value" or "My X is Y" to suggest field updates.
        A production version would use an LLM for extraction.
        """
        record = self.get_record(record_id)
        if not record:
            raise ValueError(f"Record not found: {record_id}")

        suggestions: list[SourceSuggestionModel] = []
        now = datetime.now(timezone.utc).isoformat()

        # Simple keyword matching against field labels
        note_lower = note_text.lower()
        for field in record.fields:
            label_lower = field.label.lower().replace(" ", "")
            # Check if the field label or a close variant appears in the note
            label_words = field.label.lower().split()
            for line in note_text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                line_lower = line_stripped.lower()
                # Match patterns like "label: value" or "my label is value"
                if any(w in line_lower for w in label_words if len(w) > 2):
                    # Extract the value part after a colon or "is"
                    value = line_stripped
                    if ":" in line_stripped:
                        value = line_stripped.split(":", 1)[1].strip()
                    elif " is " in line_lower:
                        value = line_stripped.split(" is ", 1)[1].strip()
                    if value and value != field.value:
                        suggestions.append(SourceSuggestionModel(
                            suggestion_id=f"sug-{uuid.uuid4().hex[:8]}",
                            record_id=record_id,
                            field_id=field.field_id,
                            field_label=field.label,
                            current_value=field.value,
                            suggested_value=value,
                            confidence=0.6,
                            source_note=line_stripped,
                        ))
                    break  # One suggestion per field per note

        return NoteExtractionResultModel(
            suggestions=suggestions,
            note_text=note_text,
            created_at=now,
        )

    def apply_suggestion(self, suggestion: SourceSuggestionModel) -> Optional[SourceRecordModel]:
        """Apply a single suggestion, updating the record and creating a revision."""
        return self.update_record(
            record_id=suggestion.record_id,
            label=None,
            fields=[{"field_id": suggestion.field_id, "value": suggestion.suggested_value}],
            provenance="note_extraction",
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_fields(conn: sqlite3.Connection, record_id: str) -> list[SourceFieldValueModel]:
        """Load field values for a record from the database."""
        rows = conn.execute(
            "SELECT field_id, label, value, category, field_order "
            "FROM source_fields WHERE record_id = ? ORDER BY category, field_order",
            (record_id,),
        ).fetchall()
        return [
            SourceFieldValueModel(
                field_id=r["field_id"],
                label=r["label"],
                value=r["value"],
                category=r["category"],
                order=r["field_order"],
            )
            for r in rows
        ]

    @staticmethod
    async def _load_fields_pg(
        conn: asyncpg.Connection,
        record_id: str,
    ) -> list[SourceFieldValueModel]:
        """Load field values for a record from PostgreSQL."""
        rows = await conn.fetch(
            "SELECT field_id, label, value, category, field_order "
            "FROM source_fields WHERE record_id = $1 ORDER BY category, field_order",
            record_id,
        )
        return [
            SourceFieldValueModel(
                field_id=row["field_id"],
                label=row["label"],
                value=row["value"],
                category=row["category"],
                order=row["field_order"],
            )
            for row in rows
        ]

    @staticmethod
    def _write_artifact(record_id: str, label: str, archetype: str) -> None:
        """Write a JSON artifact for the record to disk."""
        artifact_dir = SOURCES_DIR / record_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "record.json"
        artifact_path.write_text(
            json.dumps({
                "record_id": record_id,
                "label": label,
                "archetype": archetype,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            encoding="utf-8",
        )


# Singleton
_source_service: Optional[SourceService] = None


def get_source_service() -> SourceService:
    """Get or create the source service singleton."""
    global _source_service
    if _source_service is None:
        _source_service = SourceService()
    return _source_service
