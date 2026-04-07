"""Tests for graph API endpoints — health, company history, search history."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from graph.career_graph_read_models import (
    CompanyHistoryEntry,
    CompanyHistoryReadModel,
    GraphDegradedResponse,
    GraphHealthResponse,
    SearchHistoryEntry,
    SearchHistoryReadModel,
)


@pytest.fixture(autouse=True)
def _isolate_graph_db(tmp_path, monkeypatch):
    """Redirect the graph DB to a temp path for each test."""
    import graph.career_event_store as ces

    db_dir = tmp_path / "graph"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "career_events.db"

    monkeypatch.setattr(ces, "GRAPH_DIR", db_dir)
    monkeypatch.setattr(ces, "GRAPH_DB", db_path)
    ces._store = None
    yield
    ces._store = None


@pytest.fixture()
def manifest_path(tmp_path) -> Path:
    path = tmp_path / "jobs_manifest.json"
    path.write_text('{"jobs": []}', encoding="utf-8")
    return path


@pytest.fixture()
def client(tmp_path, manifest_path, monkeypatch):
    """Create a TestClient with isolated DBs and no real LightRAG."""
    import api_server as api
    import runtime_settings as rs

    monkeypatch.setattr(api, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rs, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CANONICAL_INGEST_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_SDK_ROOT", raising=False)
    monkeypatch.delenv("LEGACY_WORKSPACES", raising=False)
    monkeypatch.delenv("CANONICAL_WORKSPACE_ROOT", raising=False)
    rs.reset_runtime_settings_cache()

    # Reset graph worker singleton so startup event creates a fresh one
    import graph.career_graph_worker as gw
    gw._worker = None

    # Reset graph service singleton
    import graph.career_graph_service as gs
    gs._service = None

    client = TestClient(api.app)
    yield client
    rs.reset_runtime_settings_cache()


def _mock_service() -> MagicMock:
    """Build a mock CareerGraphService."""
    svc = MagicMock()
    svc.health.return_value = GraphHealthResponse(
        status="healthy",
        is_available=True,
        total_events=10,
        processed_events=8,
        pending_events=2,
        last_processed_at="2026-04-07T12:00:00+00:00",
        initialized_at="2026-04-07T11:00:00+00:00",
    )
    # query_company_history and query_search_history are async
    svc.query_company_history = AsyncMock(return_value=CompanyHistoryReadModel(
        company_key="acme-corp",
        total_events=3,
        entries=[
            CompanyHistoryEntry(
                company_key="acme-corp",
                company_name="Acme Corp",
                event_type="search:completed",
                event_timestamp="2026-04-07T12:00:00+00:00",
                summary="search completed",
                source="search",
            ),
        ],
        related_companies=["other-corp"],
        is_degraded=False,
    ))
    svc.query_search_history = AsyncMock(return_value=SearchHistoryReadModel(
        total_runs=2,
        entries=[
            SearchHistoryEntry(
                run_id="run-001",
                preference_label="My Search",
                started_at="2026-04-07T10:00:00+00:00",
                completed_at="2026-04-07T10:05:00+00:00",
                total_candidates=10,
                new_candidates=5,
                top_companies=["acme-corp"],
            ),
        ],
        companies_seen=["acme-corp"],
        is_degraded=False,
    ))
    return svc


class TestGraphHealthEndpoint:
    """Test 1: GET /api/graph/health returns 200 with status, is_available, total_events."""

    def test_health_200(self, client) -> None:
        with patch("api_server.get_career_graph_service", return_value=_mock_service()):
            resp = client.get("/api/graph/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "is_available" in data
        assert "total_events" in data
        assert data["is_available"] is True
        assert data["total_events"] == 10


class TestGraphCompanyHistoryEndpoint:
    """Test 2: GET /api/graph/company/{key}/history returns 200 with company_key and entries."""

    def test_company_history_200(self, client) -> None:
        with patch("api_server.get_career_graph_service", return_value=_mock_service()):
            resp = client.get("/api/graph/company/acme-corp/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_key"] == "acme-corp"
        assert "entries" in data
        assert len(data["entries"]) == 1
        assert data["is_degraded"] is False

    def test_company_history_invalid_key_400(self, client) -> None:
        with patch("api_server.get_career_graph_service", return_value=_mock_service()):
            # Dots are not allowed by the alphanumeric+hyphens+underscores validation
            resp = client.get("/api/graph/company/bad.key/history")
        assert resp.status_code == 400


class TestGraphSearchHistoryEndpoint:
    """Test 3: GET /api/graph/search/history returns 200 with total_runs and entries."""

    def test_search_history_200(self, client) -> None:
        with patch("api_server.get_career_graph_service", return_value=_mock_service()):
            resp = client.get("/api/graph/search/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_runs" in data
        assert "entries" in data
        assert data["total_runs"] == 2
        assert data["is_degraded"] is False


class TestGraphDegradedMode:
    """Test 4: When worker is unhealthy, company history response contains is_degraded=True."""

    def test_degraded_company_history(self, client) -> None:
        svc = _mock_service()
        svc.query_company_history = AsyncMock(return_value=GraphDegradedResponse(
            total_events=5,
        ))
        with patch("api_server.get_career_graph_service", return_value=svc):
            resp = client.get("/api/graph/company/acme-corp/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_degraded"] is True
