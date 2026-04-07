"""Tests for research API endpoints -- companies, snapshots, claims, refresh."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_research_db(tmp_path, monkeypatch):
    """Redirect the research DB to a temp path for each test."""
    import research_store as rs

    db_dir = tmp_path / "research"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "research.db"

    monkeypatch.setattr(rs, "RESEARCH_DIR", db_dir)
    monkeypatch.setattr(rs, "RESEARCH_DB", db_path)
    rs._research_store = None
    yield
    rs._research_store = None


@pytest.fixture()
def manifest_path(tmp_path) -> Path:
    path = tmp_path / "jobs_manifest.json"
    path.write_text('{"jobs": []}', encoding="utf-8")
    return path


@pytest.fixture()
def client(tmp_path, manifest_path, monkeypatch):
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

    client = TestClient(api.app)
    yield client
    rs.reset_runtime_settings_cache()


def _seed_company_with_data():
    """Seed a company with a completed snapshot containing claims and questions."""
    from research_store import get_research_store

    store = get_research_store()
    store.ensure_company("acme-corp", "Acme Corp")

    snap = store.create_snapshot("acme-corp", source_count=1)

    store.add_claim(
        snapshot_id=snap.snapshot_id,
        company_key="acme-corp",
        claim_text="Acme has a strong engineering culture",
        source_url="https://glassdoor.com/acme",
        collected_at="2026-01-15T12:00:00Z",
        confidence="high",
        themes=["culture", "engineering"],
    )

    store.add_interview_question(
        snapshot_id=snap.snapshot_id,
        company_key="acme-corp",
        question_text="Tell me about a time you resolved a conflict",
        source_url="https://glassdoor.com/acme/interview",
        collected_at="2026-01-15T12:00:00Z",
        themes=["behavioral"],
        role_applicability=["SWE"],
    )

    store.complete_snapshot(snap.snapshot_id, claim_count=1, question_count=1)


# ── GET /api/research/companies ──────────────────────────────────────────────────


class TestListCompanies:
    def test_empty_list(self, client):
        resp = client.get("/api/research/companies")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_seeded_companies(self, client):
        _seed_company_with_data()

        resp = client.get("/api/research/companies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["company_key"] == "acme-corp"
        assert data[0]["company_name"] == "Acme Corp"
        assert data[0]["claim_count"] == 1
        assert data[0]["question_count"] == 1
        assert data[0]["latest_snapshot_id"] is not None


# ── GET /api/research/company/{company_key} ──────────────────────────────────────


class TestGetCompanyResearch:
    def test_404_for_unknown_company(self, client):
        resp = client.get("/api/research/company/no-such-company")
        assert resp.status_code == 404

    def test_returns_full_detail(self, client):
        _seed_company_with_data()

        resp = client.get("/api/research/company/acme-corp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_key"] == "acme-corp"
        assert data["company_name"] == "Acme Corp"
        assert len(data["claims"]) == 1
        assert data["claims"][0]["claim_text"] == "Acme has a strong engineering culture"
        assert data["claims"][0]["confidence"] == "high"
        assert data["claims"][0]["themes"] == ["culture", "engineering"]
        assert len(data["questions"]) == 1
        assert data["questions"][0]["question_text"] == "Tell me about a time you resolved a conflict"
        assert len(data["snapshots"]) == 1
        assert data["stale_days"] is not None or data["last_refreshed_at"] is not None


# ── GET /api/research/company/{company_key}/snapshots ────────────────────────────


class TestListSnapshots:
    def test_404_for_unknown_company(self, client):
        resp = client.get("/api/research/company/no-such-company/snapshots")
        assert resp.status_code == 404

    def test_returns_snapshots_for_company(self, client):
        _seed_company_with_data()

        resp = client.get("/api/research/company/acme-corp/snapshots")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["snapshot_id"].startswith("snap-")
        assert data[0]["company_key"] == "acme-corp"
        assert data[0]["claim_count"] == 1
        assert data[0]["question_count"] == 1


# ── POST /api/research/company/{company_key}/refresh ─────────────────────────────


class TestTriggerRefresh:
    def test_creates_refresh_for_new_company(self, client, monkeypatch):
        import research_store as rs
        import api_server as api

        # Just create a refresh record without running async execution
        store = rs.get_research_store()
        store.ensure_company("new-co", "New Co")
        refresh = store.create_refresh("new-co", sources_total=2)

        # Patch start_research_refresh to return our controlled refresh_id
        monkeypatch.setattr(
            api,
            "start_research_refresh",
            lambda ck, cn: refresh.refresh_id,
        )

        resp = client.post("/api/research/company/new-co/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_id"] == refresh.refresh_id
        assert data["company_key"] == "new-co"
        assert data["status"] == "pending"

    def test_creates_refresh_for_existing_company(self, client, monkeypatch):
        from research_store import get_research_store
        import api_server as api

        _seed_company_with_data()
        store = get_research_store()
        refresh = store.create_refresh("acme-corp", sources_total=2)

        monkeypatch.setattr(
            api,
            "start_research_refresh",
            lambda ck, cn: refresh.refresh_id,
        )

        resp = client.post("/api/research/company/acme-corp/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_key"] == "acme-corp"
        assert data["status"] == "pending"


# ── GET /api/research/refresh/{refresh_id} ───────────────────────────────────────


class TestGetRefreshStatus:
    def test_404_for_unknown_refresh(self, client):
        resp = client.get("/api/research/refresh/refresh-nonexistent")
        assert resp.status_code == 404

    def test_returns_pending_refresh(self, client):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        refresh = store.create_refresh("acme-corp", sources_total=2)

        resp = client.get(f"/api/research/refresh/{refresh.refresh_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_id"] == refresh.refresh_id
        assert data["status"] == "pending"
        assert data["completed_at"] is None

    def test_returns_completed_refresh(self, client):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        refresh = store.create_refresh("acme-corp", sources_total=2)
        store.update_refresh(
            refresh.refresh_id,
            status="completed",
            sources_completed=2,
        )

        resp = client.get(f"/api/research/refresh/{refresh.refresh_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["sources_completed"] == 2
        assert data["completed_at"] is not None

    def test_returns_failed_refresh_with_error(self, client):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        refresh = store.create_refresh("acme-corp", sources_total=2)
        store.update_refresh(
            refresh.refresh_id,
            status="failed",
            error_message="Connection refused",
        )

        resp = client.get(f"/api/research/refresh/{refresh.refresh_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Connection refused"
