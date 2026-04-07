"""Career event models — Pydantic event envelope and typed payload definitions.

All career activity across 5 domains (source, search, list, research, application)
produces events conforming to these schemas. Events are persisted via
CareerEventStore and routed through CareerEventBus.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


# ── Event Category ────────────────────────────────────────────────────────────

class CareerEventCategory(StrEnum):
    SOURCE = "source"
    SEARCH = "search"
    LIST = "list"
    RESEARCH = "research"
    APPLICATION = "application"


# ── Event Envelope ────────────────────────────────────────────────────────────

class CareerEventEnvelope(BaseModel):
    """Universal envelope wrapping every career event.

    The idempotency_key prevents duplicate ingest when the same action fires
    more than once (e.g. retry, re-emit). It is typically derived as:
        "{category}:{entity_id}:{action}:{timestamp_minute_bucket}"
    """

    event_id: str
    idempotency_key: str
    category: CareerEventCategory
    action: str
    entity_id: str
    entity_type: str
    payload: dict = {}
    timestamp: str
    metadata: dict = Field(default_factory=dict)


# ── Typed Payloads ────────────────────────────────────────────────────────────

class SourceEventPayload(BaseModel):
    record_id: str
    archetype: str
    action_type: str  # created | updated | deleted
    field_ids_changed: list[str] = Field(default_factory=list)


class SearchEventPayload(BaseModel):
    run_id: str
    preference_id: Optional[str] = None
    action_type: str  # started | completed | failed
    candidate_count: int = 0
    source_counts: dict[str, int] = Field(default_factory=dict)


class ListEventPayload(BaseModel):
    list_id: str
    item_id: str
    action_type: str  # reordered | removed | notes_updated | priority_updated | status_updated | promoted
    candidate_id: Optional[str] = None


class ResearchEventPayload(BaseModel):
    company_key: str
    snapshot_id: Optional[str] = None
    action_type: str  # refresh_started | refresh_completed | refresh_failed
    claim_count: int = 0
    question_count: int = 0


class ApplicationEventPayload(BaseModel):
    candidate_id: str
    job_index: int
    action_type: str  # ingested | promoted
    company: str
    role: str
