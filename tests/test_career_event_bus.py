"""Tests for CareerEventBus — event bus with persistence and idempotency."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from graph.career_event_bus import CareerEventBus, emit_career_event
from graph.career_event_models import (
    CareerEventCategory,
    SourceEventPayload,
    SearchEventPayload,
    ListEventPayload,
    ResearchEventPayload,
    ApplicationEventPayload,
)
from graph.career_event_store import CareerEventStore


@pytest.fixture()
def bus(tmp_path: Path) -> CareerEventBus:
    """Create a CareerEventBus with a temporary event store."""
    db_path = tmp_path / "test_bus_events.db"
    store = CareerEventStore(db_path=db_path)
    return CareerEventBus(store=store)


# ── Test 5: emit persists and returns event_id ───────────────────────────────

def test_emit_persists_and_returns_event_id(bus: CareerEventBus) -> None:
    event_id = bus.emit(
        category="source",
        action="source_record_created",
        entity_id="rec-1",
        entity_type="source_record",
        payload={"archetype": "new_grad", "field_ids": ["full_name"]},
    )

    assert event_id.startswith("evt-")

    store = bus._store
    retrieved = store.get(event_id)
    assert retrieved is not None
    assert retrieved.category == CareerEventCategory.SOURCE
    assert retrieved.action == "source_record_created"
    assert retrieved.entity_id == "rec-1"


# ── Test 6: duplicate idempotency_key does not create second event ────────────

def test_duplicate_idempotency_key_does_not_duplicate(bus: CareerEventBus) -> None:
    event_id_1 = bus.emit(
        category="source",
        action="source_record_created",
        entity_id="rec-1",
        entity_type="source_record",
        payload={},
        idempotency_key="fixed-key",
    )

    event_id_2 = bus.emit(
        category="source",
        action="source_record_created",
        entity_id="rec-1",
        entity_type="source_record",
        payload={},
        idempotency_key="fixed-key",
    )

    # Second emit with same idempotency_key should return same event_id
    assert event_id_2 == event_id_1

    store = bus._store
    assert store.count_events() == 1


# ── Test 7: payload types serialize and deserialize correctly ─────────────────

def test_source_event_payload_serialization() -> None:
    payload = SourceEventPayload(
        record_id="rec-1",
        archetype="new_grad",
        action_type="created",
        field_ids_changed=["full_name", "email"],
    )
    data = payload.model_dump()
    restored = SourceEventPayload.model_validate(data)
    assert restored.record_id == "rec-1"
    assert restored.archetype == "new_grad"
    assert restored.action_type == "created"
    assert restored.field_ids_changed == ["full_name", "email"]


def test_search_event_payload_serialization() -> None:
    payload = SearchEventPayload(
        run_id="run-1",
        preference_id="pref-1",
        action_type="completed",
        candidate_count=10,
        source_counts={"greenhouse": 6, "lever": 4},
    )
    data = payload.model_dump()
    restored = SearchEventPayload.model_validate(data)
    assert restored.run_id == "run-1"
    assert restored.candidate_count == 10
    assert restored.source_counts["greenhouse"] == 6


def test_list_event_payload_serialization() -> None:
    payload = ListEventPayload(
        list_id="list-1",
        item_id="item-1",
        action_type="promoted",
        candidate_id="cand-1",
    )
    data = payload.model_dump()
    restored = ListEventPayload.model_validate(data)
    assert restored.list_id == "list-1"
    assert restored.action_type == "promoted"


def test_research_event_payload_serialization() -> None:
    payload = ResearchEventPayload(
        company_key="acme-corp",
        snapshot_id="snap-1",
        action_type="refresh_completed",
        claim_count=5,
        question_count=2,
    )
    data = payload.model_dump()
    restored = ResearchEventPayload.model_validate(data)
    assert restored.company_key == "acme-corp"
    assert restored.claim_count == 5


def test_application_event_payload_serialization() -> None:
    payload = ApplicationEventPayload(
        candidate_id="cand-1",
        job_index=42,
        action_type="ingested",
        company="Acme Corp",
        role="Software Engineer",
    )
    data = payload.model_dump()
    restored = ApplicationEventPayload.model_validate(data)
    assert restored.candidate_id == "cand-1"
    assert restored.job_index == 42
    assert restored.company == "Acme Corp"
