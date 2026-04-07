"""Tests for CareerGraphWorker — worker boundary for LightRAG ingest."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph.career_event_models import CareerEventCategory, CareerEventEnvelope


def _make_event(
    event_id: str = "evt-test0001",
    category: CareerEventCategory = CareerEventCategory.SEARCH,
    action: str = "started",
    entity_id: str = "run-abc",
    entity_type: str = "search_run",
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


class TestCareerGraphWorkerHealth:
    """Test 1: CareerGraphWorker.is_healthy() returns False before
    initialization, True after successful init."""

    def test_healthy_false_before_init(self) -> None:
        from graph.career_graph_worker import CareerGraphWorker

        worker = CareerGraphWorker(event_store=MagicMock())
        assert worker.is_healthy() is False

    def test_healthy_true_after_init(self) -> None:
        from graph.career_graph_worker import CareerGraphWorker

        worker = CareerGraphWorker(event_store=MagicMock())
        # Mock LightRAG import so initialize succeeds
        mock_lightrag = MagicMock()
        with patch.dict("sys.modules", {"lightrag": MagicMock(LightRAG=MagicMock(return_value=mock_lightrag))}):
            asyncio.get_event_loop().run_until_complete(
                worker.initialize()
            )
        assert worker.is_healthy() is True


class TestCareerGraphWorkerProcessEvents:
    """Test 2: process_pending_events reads events from the store and
    marks them processed."""

    def test_process_pending_events_reads_and_counts(self, tmp_path: Path) -> None:
        from graph.career_graph_worker import CareerGraphWorker

        events = [
            _make_event(event_id="evt-001", entity_id="run-1"),
            _make_event(event_id="evt-002", entity_id="run-2"),
        ]

        store = MagicMock()
        store.list_events.return_value = events

        worker = CareerGraphWorker(event_store=store)
        # Pretend initialized so _ingest_event runs
        worker._initialized = True
        worker._lightrag = AsyncMock()

        count = asyncio.get_event_loop().run_until_complete(
            worker.process_pending_events()
        )
        assert count == 2
        assert worker._processed_count == 2
        store.list_events.assert_called_once_with(limit=50)
