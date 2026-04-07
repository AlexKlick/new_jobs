"""API tests for cached job-status behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import api_server as api

    manifest_path = tmp_path / "jobs_manifest.json"
    status_path = tmp_path / "job_posting_status.json"

    manifest_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "canonical_index": 1,
                        "job": {
                            "index": 1,
                            "apply_url": "https://example.com/jobs/1",
                        },
                    },
                    {
                        "canonical_index": 2,
                        "job": {
                            "index": 2,
                            "apply_url": "https://example.com/jobs/2",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(api, "STATUS_FILE", status_path)
    monkeypatch.delenv("DENJOBS_ENABLE_POSTGRES", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    return TestClient(api.app)


def test_get_job_status_returns_cached_file_entry(client: TestClient):
    import api_server as api

    api.STATUS_FILE.write_text(
        json.dumps(
            {
                "updated_at": "2026-04-07T00:00:00Z",
                "statuses": [
                    {
                        "index": 1,
                        "url": "https://example.com/jobs/1",
                        "status": "ACTIVE",
                        "lastChecked": "2026-04-07T00:00:00Z",
                        "error": None,
                        "source": "generic",
                        "httpStatusCode": 200,
                        "responseTimeMs": 123,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/api/jobs/1/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["cached"] is True


def test_check_status_updates_cache_file(client: TestClient, monkeypatch):
    import api_server as api
    from job_status_checker import JobPostingStatus

    async def fake_check_job_status(index: int, url: str):
        return JobPostingStatus(
            index=index,
            url=url,
            status="ACTIVE",
            last_checked="2026-04-07T01:02:03Z",
            error=None,
            source="generic",
            http_status_code=200,
            response_time_ms=456,
        )

    monkeypatch.setattr(api.jsc, "check_job_status", fake_check_job_status)

    response = client.post("/api/jobs/1/check-status")

    assert response.status_code == 200
    payload = json.loads(api.STATUS_FILE.read_text(encoding="utf-8"))
    assert payload["statuses"][0]["index"] == 1
    assert payload["statuses"][0]["status"] == "ACTIVE"


def test_list_all_jobs_fills_unknown_for_uncached_entries(client: TestClient):
    response = client.get("/api/jobs")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["index"] == 1
    assert rows[0]["status"] == "UNKNOWN"
    assert rows[0]["cached"] is False
    assert rows[1]["index"] == 2
    assert rows[1]["status"] == "UNKNOWN"
