"""Tests for CareerEventStore — append-only SQLite event persistence."""

import tempfile
from pathlib import Path

import pytest

from graph.career_event_models import (
    CareerEventCategory,
    CareerEventEnvelope,
)
from graph.career_event_store import CareerEventStore


@pytest.fixture()
def event_store(tmp_path: Path) -> CareerEventStore:
    """Create a CareerEventStore backed by a temporary database."""
    db_path = tmp_path / "test_events.db"
    return CareerEventStore(db_path=db_path)


def _make_envelope(
    *,
    event_id: str = "evt-001",
    idempotency_key: str = "src:rec-1:created:2026-01-01T00:00",
    category: CareerEventCategory = CareerEventCategory.SOURCE,
    action: str = "source_record_created",
    entity_id: str = "rec-1",
    entity_type: str = "source_record",
    payload: dict | None = None,
) -> CareerEventEnvelope:
    from datetime import datetime, timezone

    return CareerEventEnvelope(
        event_id=event_id,
        idempotency_key=idempotency_key,
        category=category,
        action=action,
        entity_id=entity_id,
        entity_type=entity_type,
        payload=payload or {"field_ids": ["f1"]},
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata={},
    )


# ── Test 1: persist and retrieve by event_id ──────────────────────────────────

def test_append_and_get_by_event_id(event_store: CareerEventStore) -> None:
    envelope = _make_envelope()
    result = event_store.append(envelope)

    assert result == "evt-001"

    retrieved = event_store.get("evt-001")
    assert retrieved is not None
    assert retrieved.event_id == "evt-001"
    assert retrieved.category == CareerEventCategory.SOURCE
    assert retrieved.action == "source_record_created"
    assert retrieved.entity_id == "rec-1"
    assert retrieved.entity_type == "source_record"


# ── Test 2: reject duplicate idempotency_key ──────────────────────────────────

def test_reject_duplicate_idempotency_key(event_store: CareerEventStore) -> None:
    envelope_a = _make_envelope(event_id="evt-001", idempotency_key="dup-key")
    envelope_b = _make_envelope(event_id="evt-002", idempotency_key="dup-key")

    event_store.append(envelope_a)

    with pytest.raises(ValueError, match="idempotency_key"):
        event_store.append(envelope_b)


# ── Test 3: list events filtered by category ──────────────────────────────────

def test_list_events_filtered_by_category(event_store: CareerEventStore) -> None:
    src_event = _make_envelope(
        event_id="evt-src",
        idempotency_key="k1",
        category=CareerEventCategory.SOURCE,
        entity_id="e1",
    )
    search_event = _make_envelope(
        event_id="evt-search",
        idempotency_key="k2",
        category=CareerEventCategory.SEARCH,
        entity_id="e2",
    )

    event_store.append(src_event)
    event_store.append(search_event)

    source_events = event_store.list_events(category="source")
    assert len(source_events) == 1
    assert source_events[0].event_id == "evt-src"

    search_events = event_store.list_events(category="search")
    assert len(search_events) == 1
    assert search_events[0].event_id == "evt-search"


# ── Test 4: list events filtered by entity_id ─────────────────────────────────

def test_list_events_filtered_by_entity_id(event_store: CareerEventStore) -> None:
    event_a = _make_envelope(
        event_id="evt-a",
        idempotency_key="ka",
        entity_id="entity-x",
    )
    event_b = _make_envelope(
        event_id="evt-b",
        idempotency_key="kb",
        entity_id="entity-y",
    )

    event_store.append(event_a)
    event_store.append(event_b)

    results = event_store.list_events(entity_id="entity-x")
    assert len(results) == 1
    assert results[0].event_id == "evt-a"


# ── Test 5: count_events ─────────────────────────────────────────────────────

def test_count_events(event_store: CareerEventStore) -> None:
    assert event_store.count_events() == 0

    event_store.append(_make_envelope(event_id="e1", idempotency_key="k1", entity_id="x"))
    event_store.append(_make_envelope(event_id="e2", idempotency_key="k2", entity_id="y"))

    assert event_store.count_events() == 2
    assert event_store.count_events(category="source") == 2
    assert event_store.count_events(category="search") == 0
