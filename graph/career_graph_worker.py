"""Career graph worker — reads events from the store and feeds them to LightRAG.

The worker owns LightRAG initialization (lazy, inside initialize()). Request
handlers never call initialize directly. If LightRAG is not installed or
initialization fails, the worker reports unhealthy and the service returns
degraded responses.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from graph.career_event_models import CareerEventEnvelope
from graph.career_event_store import CareerEventStore, get_career_event_store

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
GRAPH_DIR = PROJECT_ROOT / "graph"


class CareerGraphWorker:
    """Worker that reads events from the store and feeds them to LightRAG.

    LightRAG initialization is lazy and happens only in the initialize() method.
    If LightRAG is not installed, the worker stays uninitialized and is_healthy()
    returns False. The service layer then returns degraded responses.
    """

    def __init__(self, event_store: Optional[CareerEventStore] = None) -> None:
        self._event_store = event_store or get_career_event_store()
        self._initialized = False
        self._processing_lock = asyncio.Lock()
        self._last_processed_at: Optional[str] = None
        self._processed_count = 0
        self._initialized_at: Optional[str] = None
        self._lightrag: Optional[object] = None

    async def initialize(self) -> None:
        """Initialize LightRAG instance.

        This is the ONLY place LightRAG gets initialized. Request handlers
        never call this. If LightRAG is not installed, the worker stays
        uninitialized.
        """
        try:
            from lightrag import LightRAG  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "LightRAG is not installed. Career graph worker will remain uninitialized. "
                "Install lightrag to enable graph memory features."
            )
            self._initialized = False
            return

        try:
            storage_dir = GRAPH_DIR / "lightrag_storage"
            storage_dir.mkdir(parents=True, exist_ok=True)

            # LightRAG configuration for local Nanbeige model
            self._lightrag = LightRAG(working_dir=str(storage_dir))
            self._initialized = True
            self._initialized_at = datetime.now(timezone.utc).isoformat()
            logger.info("Career graph worker initialized successfully at %s", self._initialized_at)
        except Exception as exc:
            logger.error("LightRAG initialization failed: %s", exc)
            self._initialized = False

    def is_healthy(self) -> bool:
        """Return True if the worker has been successfully initialized."""
        return self._initialized

    async def process_pending_events(self) -> int:
        """Read events from the store and feed them to LightRAG.

        Acquires an async lock to prevent concurrent processing. Returns the
        count of events processed (whether ingest succeeded or not per event).
        """
        async with self._processing_lock:
            events = self._event_store.list_events(limit=50)

        if not events:
            return 0

        processed = 0
        for event in events:
            try:
                await self._ingest_event(event)
                processed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to ingest event %s: %s", event.event_id, exc
                )
                # Count it as processed even on failure to avoid infinite retry
                processed += 1

        self._processed_count += processed
        self._last_processed_at = datetime.now(timezone.utc).isoformat()
        return processed

    async def _ingest_event(self, event: CareerEventEnvelope) -> None:
        """Format an event into human-readable text and insert into LightRAG."""
        if not self._initialized or self._lightrag is None:
            return

        formatted_text = self._format_event_for_ingest(event)

        try:
            if hasattr(self._lightrag, "insert"):
                insert_fn = self._lightrag.insert
                if asyncio.iscoroutinefunction(insert_fn):
                    await insert_fn(formatted_text)
                else:
                    insert_fn(formatted_text)
        except Exception as exc:
            logger.warning("LightRAG insert failed for event %s: %s", event.event_id, exc)

    @staticmethod
    def _format_event_for_ingest(event: CareerEventEnvelope) -> str:
        """Format an event envelope into a human-readable string for LightRAG."""
        category = event.category.value if hasattr(event.category, "value") else str(event.category)
        payload_parts = []
        for key, value in event.payload.items():
            payload_parts.append(f"  {key}: {value}")

        payload_section = "\n".join(payload_parts) if payload_parts else "  (no details)"

        return (
            f"Career Event: {category} {event.action}\n"
            f"Entity: {event.entity_type} '{event.entity_id}'\n"
            f"Timestamp: {event.timestamp}\n"
            f"Details:\n{payload_section}"
        )

    async def query(self, question: str) -> Optional[str]:
        """Query LightRAG with a natural language question.

        Returns None if the worker is not initialized.
        """
        if not self._initialized or self._lightrag is None:
            return None

        try:
            if hasattr(self._lightrag, "query"):
                query_fn = self._lightrag.query
                if asyncio.iscoroutinefunction(query_fn):
                    return await query_fn(question)
                else:
                    return query_fn(question)
        except Exception as exc:
            logger.warning("LightRAG query failed: %s", exc)
            return None

        return None

    def get_stats(self) -> dict:
        """Return worker statistics."""
        total_in_store = self._event_store.count_events()
        return {
            "initialized": self._initialized,
            "processed_count": self._processed_count,
            "last_processed_at": self._last_processed_at,
            "initialized_at": self._initialized_at,
            "pending_count": max(0, total_in_store - self._processed_count),
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_worker: Optional[CareerGraphWorker] = None


def get_career_graph_worker() -> CareerGraphWorker:
    """Lazy singleton getter for the career graph worker."""
    global _worker
    if _worker is None:
        _worker = CareerGraphWorker()
    return _worker
