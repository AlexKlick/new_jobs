"""Tests for CareerGraphService — query service with degraded-mode fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from graph.career_event_models import CareerEventCategory, CareerEventEnvelope


def _make_event(
    event_id: str = "evt-test0001",
    category: CareerEventCategory = CareerEventCategory.SEARCH,
    action: str = "completed",
    entity_id: str = "company-acme-corp",
    entity_type: str = "company",
    payload: dict | None = None,
) -> CareerEventEnvelope:
    return CareerEventEnvelope(
        event_id=event_id,
        idempotency_key=f"ik-{event_id}",
        category=category,
        action=action,
        entity_id=entity_id,
        entity_type=entity_type,
        payload=payload or {},
        timestamp="2026-04-07T12:00:00+00:00",
        metadata={},
    )


def _healthy_worker() -> MagicMock:
    """Build a mock worker that reports as healthy."""
    worker = MagicMock()
    worker.is_healthy.return_value = True
    worker.get_stats.return_value = {
        "initialized": True,
        "processed_count": 5,
        "last_processed_at": "2026-04-07T12:00:00+00:00",
        "initialized_at": "2026-04-07T11:00:00+00:00",
        "pending_count": 2,
    }
    return worker


def _unhealthy_worker() -> MagicMock:
    """Build a mock worker that reports as unhealthy."""
    worker = MagicMock()
    worker.is_healthy.return_value = False
    worker.get_stats.return_value = {
        "initialized": False,
        "processed_count": 0,
        "last_processed_at": None,
        "initialized_at": None,
        "pending_count": 3,
    }
    return worker


class TestCompanyHistoryHealthy:
    """Test 3: query_company_history returns CompanyHistoryReadModel when
    worker is healthy."""

    def test_returns_read_model(self) -> None:
        from graph.career_graph_service import CareerGraphService
        from graph.career_graph_read_models import CompanyHistoryReadModel

        store = MagicMock()
        store.list_events.return_value = [
            _make_event(
                category=CareerEventCategory.SEARCH,
                action="completed",
                entity_id="acme-corp",
                payload={"company_name": "Acme Corp", "role": "Engineer"},
            ),
        ]
        store.count_events.return_value = 1

        import asyncio

        svc = CareerGraphService(worker=_healthy_worker(), event_store=store)
        result = asyncio.get_event_loop().run_until_complete(
            svc.query_company_history("acme-corp")
        )
        assert isinstance(result, CompanyHistoryReadModel)
        assert result.company_key == "acme-corp"
        assert result.is_degraded is False


class TestCompanyHistoryDegraded:
    """Test 4: query_company_history returns GraphDegradedResponse when
    worker is unhealthy."""

    def test_returns_degraded(self) -> None:
        from graph.career_graph_service import CareerGraphService
        from graph.career_graph_read_models import GraphDegradedResponse

        store = MagicMock()
        store.count_events.return_value = 10

        import asyncio

        svc = CareerGraphService(worker=_unhealthy_worker(), event_store=store)
        result = asyncio.get_event_loop().run_until_complete(
            svc.query_company_history("acme-corp")
        )
        assert isinstance(result, GraphDegradedResponse)
        assert result.is_degraded is True


class TestSearchHistoryHealthy:
    """Test 5: query_search_history returns SearchHistoryReadModel when
    worker is healthy."""

    def test_returns_read_model(self) -> None:
        from graph.career_graph_service import CareerGraphService
        from graph.career_graph_read_models import SearchHistoryReadModel

        store = MagicMock()
        store.list_events.return_value = [
            _make_event(
                event_id="evt-s1",
                category=CareerEventCategory.SEARCH,
                action="completed",
                entity_id="run-001",
                payload={
                    "run_id": "run-001",
                    "candidate_count": 5,
                    "new_candidates": 3,
                },
            ),
        ]
        store.count_events.return_value = 1

        import asyncio

        svc = CareerGraphService(worker=_healthy_worker(), event_store=store)
        result = asyncio.get_event_loop().run_until_complete(
            svc.query_search_history()
        )
        assert isinstance(result, SearchHistoryReadModel)
        assert result.is_degraded is False


class TestSearchHistoryDegraded:
    """Test 6: query_search_history returns GraphDegradedResponse when
    worker is unhealthy."""

    def test_returns_degraded(self) -> None:
        from graph.career_graph_service import CareerGraphService
        from graph.career_graph_read_models import GraphDegradedResponse

        store = MagicMock()
        store.count_events.return_value = 5

        import asyncio

        svc = CareerGraphService(worker=_unhealthy_worker(), event_store=store)
        result = asyncio.get_event_loop().run_until_complete(
            svc.query_search_history()
        )
        assert isinstance(result, GraphDegradedResponse)
        assert result.is_degraded is True


class TestHealth:
    """Test 7: health() returns GraphHealthResponse with status, event_count,
    and is_available fields."""

    def test_returns_health_response(self) -> None:
        from graph.career_graph_service import CareerGraphService
        from graph.career_graph_read_models import GraphHealthResponse

        store = MagicMock()
        store.count_events.return_value = 10

        svc = CareerGraphService(worker=_healthy_worker(), event_store=store)
        result = svc.health()
        assert isinstance(result, GraphHealthResponse)
        assert result.is_available is True
        assert result.total_events == 10
