"""Career event store — SQLite-backed append-only event persistence.

Every career action (source CRUD, search run, list mutation, research refresh,
application ingest) produces a CareerEventEnvelope that is persisted here.
The store enforces idempotency via a UNIQUE constraint on idempotency_key.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from graph.career_event_models import CareerEventEnvelope

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
GRAPH_DIR = PROJECT_ROOT / "graph"
GRAPH_DB = GRAPH_DIR / "career_events.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS career_events (
    event_id        TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    category        TEXT NOT NULL,
    action          TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    timestamp       TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX IF NOT EXISTS idx_events_idempotency ON career_events(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_events_category ON career_events(category);
CREATE INDEX IF NOT EXISTS idx_events_entity_id ON career_events(entity_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON career_events(timestamp);
"""


class CareerEventStore:
    """Append-only store for career graph-ingest events."""

    def __init__(self, db_path: Path = GRAPH_DB) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._init_schema()

    def _init_schema(self) -> None:
        """Schema is initialized via executescript in __init__."""
        pass

    def append(self, envelope: CareerEventEnvelope) -> str:
        """Persist an event envelope. Returns event_id.

        Raises ValueError if idempotency_key already exists.
        """
        try:
            self._conn.execute(
                "INSERT INTO career_events "
                "(event_id, idempotency_key, category, action, entity_id, entity_type, "
                "payload, timestamp, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    envelope.event_id,
                    envelope.idempotency_key,
                    envelope.category.value if hasattr(envelope.category, "value") else str(envelope.category),
                    envelope.action,
                    envelope.entity_id,
                    envelope.entity_type,
                    json.dumps(envelope.payload),
                    envelope.timestamp,
                    json.dumps(envelope.metadata),
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "idempotency_key" in str(exc) or "UNIQUE constraint" in str(exc):
                raise ValueError(
                    f"Duplicate idempotency_key: {envelope.idempotency_key}"
                ) from exc
            raise
        return envelope.event_id

    def get(self, event_id: str) -> Optional[CareerEventEnvelope]:
        """Retrieve an event by its event_id."""
        row = self._conn.execute(
            "SELECT event_id, idempotency_key, category, action, entity_id, entity_type, "
            "payload, timestamp, metadata FROM career_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_envelope(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[CareerEventEnvelope]:
        """Retrieve an event by its idempotency_key."""
        row = self._conn.execute(
            "SELECT event_id, idempotency_key, category, action, entity_id, entity_type, "
            "payload, timestamp, metadata FROM career_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_envelope(row)

    def list_events(
        self,
        category: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CareerEventEnvelope]:
        """List events with optional filters."""
        clauses: list[str] = []
        params: list[str] = []

        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT event_id, idempotency_key, category, action, entity_id, entity_type, "
            f"payload, timestamp, metadata FROM career_events{where} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        params.extend([str(limit), str(offset)])

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_envelope(r) for r in rows]

    def count_events(self, category: Optional[str] = None) -> int:
        """Count events, optionally filtered by category."""
        if category is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM career_events WHERE category = ?",
                (category,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM career_events").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_envelope(row: sqlite3.Row) -> CareerEventEnvelope:
        from graph.career_event_models import CareerEventCategory

        category_str = row["category"]
        try:
            category = CareerEventCategory(category_str)
        except ValueError:
            category = category_str  # type: ignore[assignment]

        return CareerEventEnvelope(
            event_id=row["event_id"],
            idempotency_key=row["idempotency_key"],
            category=category,
            action=row["action"],
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            timestamp=row["timestamp"],
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


# ── Module-level singleton ────────────────────────────────────────────────────

_store: Optional[CareerEventStore] = None


def get_career_event_store() -> CareerEventStore:
    """Lazy singleton getter for the event store."""
    global _store
    if _store is None:
        _store = CareerEventStore()
    return _store


def reset_career_event_store(db_path: Path = GRAPH_DB) -> CareerEventStore:
    """Reset the singleton (useful for testing)."""
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = CareerEventStore(db_path=db_path)
    return _store
