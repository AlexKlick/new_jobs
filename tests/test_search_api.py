"""Tests for search/list API endpoints and canonical-ingest bridge behavior."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_search_db(tmp_path, monkeypatch):
    """Redirect the search DB to a temp path for each test."""
    import search.search_store as ss

    db_dir = tmp_path / "search"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "search.db"

    monkeypatch.setattr(ss, "SEARCH_DIR", db_dir)
    monkeypatch.setattr(ss, "SEARCH_DB", db_path)
    ss._search_store = None
    yield
    ss._search_store = None


@pytest.fixture(autouse=True)
def _isolate_research_db(tmp_path, monkeypatch):
    """Redirect the research DB to a temp path for each test."""
    import research.research_store as rs

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


def _seed_list_item():
    from search.search_store import get_search_store

    store = get_search_store()
    run = store.create_run(preference_id=None, preference_label="API Test")
    candidate = store.add_candidate(
        run_id=run.run_id,
        source="greenhouse",
        source_url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        role="Platform Engineer",
        location="Remote",
        salary="$200k",
        remote="yes",
        posted_date="2025-01-01",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    lst = store.create_list_for_run(run_id=run.run_id, label="API List")
    store.add_candidates_to_list_from_run(run.run_id)
    detail = store.get_list_detail(lst.list_id)
    assert detail is not None
    return candidate, detail.items[0]


class TestListDetailEndpoint:
    def test_get_list_returns_denormalized_candidate_fields(self, client):
        _, item = _seed_list_item()

        resp = client.get(f"/api/search/lists/{item.list_id}")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["items"]) == 1
        returned = data["items"][0]
        assert returned["company"] == "Acme"
        assert returned["role"] == "Platform Engineer"
        assert returned["source"] == "greenhouse"
        assert returned["apply_url"] == "https://boards.greenhouse.io/acme/jobs/1"
        assert returned["ingested"] is False
        assert returned["fit_score"] >= 0
        assert returned["research_summary"]["has_research"] is False


class TestRunEndpoints:
    def test_start_run_returns_pending_run(self, client):
        from search.search_store import get_search_store

        store = get_search_store()
        pref = store.create_preference(
            label="API Start Run",
            archetype="experienced",
            keywords=["python"],
            locations=["Remote"],
            sources=["greenhouse"],
        )

        with patch("search.search_service.asyncio.create_task") as mock_create_task:
            resp = client.post("/api/search/runs", json={"preference_id": pref.preference_id})

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"].startswith("run-")
        assert body["preference_id"] == pref.preference_id
        assert body["preference_label"] == pref.label
        assert body["status"] == "pending"
        assert mock_create_task.called

        updated_pref = store.get_preference(pref.preference_id)
        assert updated_pref is not None
        assert updated_pref.last_run_at is not None


class TestPromotionEndpoints:
    def test_ingest_candidate_bridges_before_marking_ingested(self, client, monkeypatch):
        candidate, _ = _seed_list_item()
        observed: dict[str, str] = {}

        from canonical_ingest import CanonicalIngestResult

        async def fake_ingest(cand, *, settings, load_jobs_manifest):
            observed["candidate_id"] = cand.candidate_id
            assert settings.canonical_ingest_provider == "agents_sdk"
            assert callable(load_jobs_manifest)
            return CanonicalIngestResult(
                canonical_job_index=77,
                already_exists=False,
                ingested_url=cand.apply_url,
            )

        monkeypatch.setattr("api_server.ingest_candidate_into_canonical_inventory", fake_ingest)

        resp = client.post(f"/api/search/candidates/{candidate.candidate_id}/ingest")
        assert resp.status_code == 200
        assert observed["candidate_id"] == candidate.candidate_id
        assert resp.json()["canonical_job_index"] == 77
        assert resp.json()["ingested"] is True

        from search.search_store import get_search_store

        stored = get_search_store().get_candidate(candidate.candidate_id)
        assert stored is not None
        assert stored.ingested is True

    def test_promote_list_item_marks_item_and_candidate_after_bridge(self, client, monkeypatch):
        candidate, item = _seed_list_item()

        from canonical_ingest import CanonicalIngestResult

        async def fake_ingest(cand, *, settings, load_jobs_manifest):
            assert settings.canonical_ingest_provider == "agents_sdk"
            assert callable(load_jobs_manifest)
            return CanonicalIngestResult(
                canonical_job_index=88,
                already_exists=True,
                ingested_url=cand.apply_url,
            )

        monkeypatch.setattr("api_server.ingest_candidate_into_canonical_inventory", fake_ingest)

        resp = client.post(f"/api/search/lists/items/{item.item_id}/promote")
        assert resp.status_code == 200
        body = resp.json()
        assert body["canonical_job_index"] == 88
        assert body["promoted"] is True

        from search.search_store import get_search_store

        store = get_search_store()
        stored_item = store.get_item(item.item_id)
        stored_candidate = store.get_candidate(candidate.candidate_id)
        assert stored_item is not None
        assert stored_candidate is not None
        assert stored_item.promoted is True
        assert stored_candidate.ingested is True

    def test_ingest_candidate_returns_503_when_provider_unavailable(self, client):
        candidate, _ = _seed_list_item()

        resp = client.post(f"/api/search/candidates/{candidate.candidate_id}/ingest")
        assert resp.status_code == 503

        from search.search_store import get_search_store

        stored = get_search_store().get_candidate(candidate.candidate_id)
        assert stored is not None
        assert stored.ingested is False

    def test_existing_canonical_match_short_circuits_provider(self, client, manifest_path, monkeypatch):
        candidate, _ = _seed_list_item()
        manifest_path.write_text(
            """
{
  "jobs": [
    {
      "canonical_index": 5,
      "job": {
        "index": 5,
        "company": "Acme",
        "role": "Platform Engineer",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1"
      }
    }
  ]
}
            """.strip(),
            encoding="utf-8",
        )

        async def fail_if_called(self, *, target_url, settings):
            raise AssertionError(f"bridge should not be called for {target_url}")

        monkeypatch.setattr(
            "canonical_ingest.AgentsSdkCanonicalIngestBridge.ingest",
            fail_if_called,
        )

        resp = client.post(f"/api/search/candidates/{candidate.candidate_id}/ingest")
        assert resp.status_code == 200
        assert resp.json()["canonical_job_index"] == 5
        assert resp.json()["already_exists"] is True
