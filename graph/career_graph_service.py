"""Career graph service — LightRAG query service with degraded-mode fallback.

The service checks worker health before executing queries. When the worker is
unhealthy, it returns GraphDegradedResponse instead of raising errors. This
ensures the API always returns a usable response.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from graph.career_event_models import CareerEventCategory, CareerEventEnvelope
from graph.career_event_store import CareerEventStore, get_career_event_store
from graph.career_graph_read_models import (
    CompanyHistoryEntry,
    CompanyHistoryReadModel,
    GraphDegradedResponse,
    GraphHealthResponse,
    SearchHistoryEntry,
    SearchHistoryReadModel,
)
from graph.career_graph_worker import CareerGraphWorker, get_career_graph_worker

logger = logging.getLogger(__name__)


class CareerGraphService:
    """Query service for the career graph with health-gated queries.

    When the worker is unavailable, all query methods return
    GraphDegradedResponse with a clear unavailable indicator.
    """

    def __init__(
        self,
        worker: Optional[CareerGraphWorker] = None,
        event_store: Optional[CareerEventStore] = None,
    ) -> None:
        self._worker = worker or get_career_graph_worker()
        self._event_store = event_store or get_career_event_store()

    def health(self) -> GraphHealthResponse:
        """Return graph worker health and event statistics."""
        stats = self._worker.get_stats()
        total_events = self._event_store.count_events()

        initialized = stats.get("initialized", False)
        status = "healthy" if initialized else "unavailable"

        return GraphHealthResponse(
            status=status,
            is_available=initialized,
            total_events=total_events,
            processed_events=stats.get("processed_count", 0),
            pending_events=stats.get("pending_count", 0),
            last_processed_at=stats.get("last_processed_at"),
            initialized_at=stats.get("initialized_at"),
        )

    async def query_company_history(
        self, company_key: str
    ) -> Union[CompanyHistoryReadModel, GraphDegradedResponse]:
        """Return career history for a specific company.

        If the worker is unhealthy, returns GraphDegradedResponse.
        """
        if not self._worker.is_healthy():
            total = self._event_store.count_events()
            return GraphDegradedResponse(total_events=total)

        # Query events from store filtered by entity_id matching company_key
        events = self._event_store.list_events(entity_id=company_key, limit=100)

        entries: list[CompanyHistoryEntry] = []
        related_companies: set[str] = set()

        for event in events:
            payload = event.payload or {}
            # Extract related companies from payload
            if "company_name" in payload and payload.get("company_name"):
                # Track related company keys from cross-references
                pass

            # Build entry from event data
            category = event.category.value if hasattr(event.category, "value") else str(event.category)
            company_name = payload.get("company_name") or payload.get("company")
            summary = self._build_company_event_summary(event)

            entries.append(
                CompanyHistoryEntry(
                    company_key=company_key,
                    company_name=company_name,
                    event_type=f"{category}:{event.action}",
                    event_timestamp=event.timestamp,
                    summary=summary,
                    source=category,
                )
            )

            # Extract related companies from payload references
            related = payload.get("related_companies", [])
            if isinstance(related, list):
                related_companies.update(related)
            # Also check for company references in application events
            if payload.get("company") and payload["company"] != company_key:
                related_companies.add(payload["company"])

        return CompanyHistoryReadModel(
            company_key=company_key,
            total_events=len(events),
            entries=entries,
            related_companies=sorted(related_companies),
            is_degraded=False,
        )

    async def query_search_history(
        self, limit: int = 20
    ) -> Union[SearchHistoryReadModel, GraphDegradedResponse]:
        """Return search run history with company aggregation.

        If the worker is unhealthy, returns GraphDegradedResponse.
        """
        if not self._worker.is_healthy():
            total = self._event_store.count_events()
            return GraphDegradedResponse(total_events=total)

        # Read search events from store
        search_events = self._event_store.list_events(
            category=CareerEventCategory.SEARCH.value, limit=limit * 2
        )

        # Group by run_id
        runs: dict[str, list[CareerEventEnvelope]] = {}
        for event in search_events:
            run_id = event.payload.get("run_id", event.entity_id)
            if run_id not in runs:
                runs[run_id] = []
            runs[run_id].append(event)

        entries: list[SearchHistoryEntry] = []
        companies_seen: set[str] = set()

        for run_id, run_events in runs.items():
            # Find started and completed events
            started_at: str | None = None
            completed_at: str | None = None
            preference_label: str | None = None
            total_candidates = 0
            new_candidates = 0
            top_companies: list[str] = []

            for event in run_events:
                payload = event.payload or {}
                if event.action == "started":
                    started_at = event.timestamp
                    preference_label = payload.get("preference_label")
                elif event.action == "completed":
                    completed_at = event.timestamp
                    total_candidates = payload.get("candidate_count", 0)
                    new_candidates = payload.get("new_candidates", 0)
                    top_companies = payload.get("top_companies", [])

            entries.append(
                SearchHistoryEntry(
                    run_id=run_id,
                    preference_label=preference_label,
                    started_at=started_at or run_events[0].timestamp,
                    completed_at=completed_at,
                    total_candidates=total_candidates,
                    new_candidates=new_candidates,
                    top_companies=top_companies,
                )
            )

            companies_seen.update(top_companies)

        # Sort by started_at descending and apply limit
        entries.sort(key=lambda e: e.started_at, reverse=True)
        entries = entries[:limit]

        return SearchHistoryReadModel(
            total_runs=len(runs),
            entries=entries,
            companies_seen=sorted(companies_seen),
            is_degraded=False,
        )

    @staticmethod
    def _build_company_event_summary(event: CareerEventEnvelope) -> str:
        """Build a human-readable summary for a company event."""
        payload = event.payload or {}
        category = event.category.value if hasattr(event.category, "value") else str(event.category)

        parts = [f"{category} {event.action}"]

        if "role" in payload:
            parts.append(f"for role '{payload['role']}'")
        if "candidate_count" in payload:
            parts.append(f"with {payload['candidate_count']} candidates")

        return " ".join(parts) if len(parts) > 1 else parts[0]


# ── Module-level singleton ────────────────────────────────────────────────────

_service: Optional[CareerGraphService] = None


def get_career_graph_service() -> CareerGraphService:
    """Lazy singleton getter for the career graph service."""
    global _service
    if _service is None:
        _service = CareerGraphService()
    return _service
