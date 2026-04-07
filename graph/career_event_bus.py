"""Career event bus — persists events and provides a convenience emission API.

The bus wraps CareerEventStore and generates event envelopes from simple
(keyword) arguments. Every mutation in the career services calls emit_career_event
to record graph-ingest events.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from graph.career_event_models import CareerEventCategory, CareerEventEnvelope
from graph.career_event_store import CareerEventStore, get_career_event_store

logger = logging.getLogger(__name__)


class CareerEventBus:
    """Event bus that persists career events and notifies listeners."""

    def __init__(self, store: Optional[CareerEventStore] = None) -> None:
        self._store = store or get_career_event_store()

    def emit(
        self,
        *,
        category: str,
        action: str,
        entity_id: str,
        entity_type: str,
        payload: dict,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Create and persist a career event. Returns the event_id."""
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        if not idempotency_key:
            # Bucket to the minute to avoid sub-second duplicates
            minute_bucket = now[:16]  # "2026-01-01T12:34"
            idempotency_key = f"{category}:{entity_id}:{action}:{minute_bucket}"

        try:
            cat = CareerEventCategory(category)
        except ValueError:
            cat = category  # type: ignore[assignment]

        envelope = CareerEventEnvelope(
            event_id=event_id,
            idempotency_key=idempotency_key,
            category=cat,
            action=action,
            entity_id=entity_id,
            entity_type=entity_type,
            payload=payload,
            timestamp=now,
            metadata=metadata or {},
        )

        try:
            self._store.append(envelope)
        except ValueError:
            # Idempotency: duplicate key — return the existing event_id
            existing = self._store.get_by_idempotency_key(envelope.idempotency_key)
            if existing is not None:
                return existing.event_id
            return event_id
        return event_id


# ── Module-level singleton ────────────────────────────────────────────────────

_bus: Optional[CareerEventBus] = None


def get_career_event_bus() -> CareerEventBus:
    """Lazy singleton getter for the event bus."""
    global _bus
    if _bus is None:
        _bus = CareerEventBus()
    return _bus


def emit_career_event(
    *,
    category: str,
    action: str,
    entity_id: str,
    entity_type: str,
    payload: dict,
    **kwargs: object,
) -> str:
    """Convenience function: get bus, emit event, return event_id.

    Keyword args forwarded to CareerEventBus.emit (idempotency_key, metadata).
    """
    bus = get_career_event_bus()
    return bus.emit(
        category=category,
        action=action,
        entity_id=entity_id,
        entity_type=entity_type,
        payload=payload,
        idempotency_key=kwargs.get("idempotency_key"),  # type: ignore[arg-type]
        metadata=kwargs.get("metadata"),  # type: ignore[arg-type]
    )
