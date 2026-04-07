"""Tests for source API endpoints via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """Redirect the source DB to a temp path for each test."""
    import source_service as ss

    db_dir = tmp_path / "sources"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "source_metadata.db"

    monkeypatch.setattr(ss, "SOURCES_DIR", db_dir)
    monkeypatch.setattr(ss, "SOURCES_DB", db_path)
    ss._source_service = None
    yield
    ss._source_service = None


@pytest.fixture()
def client():
    """Create a TestClient with isolated DB."""
    from api_server import app

    return TestClient(app)


class TestArchetypeEndpoints:
    def test_list_archetypes(self, client):
        resp = client.get("/api/sources/archetypes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_get_archetype_new_grad(self, client):
        resp = client.get("/api/sources/archetypes/new_grad")
        assert resp.status_code == 200
        data = resp.json()
        assert data["archetype"] == "new_grad"
        assert len(data["fields"]) > 0

    def test_get_archetype_not_found(self, client):
        resp = client.get("/api/sources/archetypes/nonexistent")
        assert resp.status_code == 404


class TestRecordCRUDEndpoints:
    def test_create_and_get_record(self, client):
        create_resp = client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "Test Profile"},
        )
        assert create_resp.status_code == 200
        record = create_resp.json()
        assert record["archetype"] == "new_grad"
        assert record["label"] == "Test Profile"
        record_id = record["record_id"]

        get_resp = client.get(f"/api/sources/records/{record_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["label"] == "Test Profile"

    def test_list_records(self, client):
        client.post(
            "/api/sources/records", json={"archetype": "new_grad", "label": "A"}
        )
        client.post(
            "/api/sources/records",
            json={"archetype": "experienced", "label": "B"},
        )
        resp = client.get("/api/sources/records")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_update_record(self, client):
        create_resp = client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "Profile"},
        )
        record_id = create_resp.json()["record_id"]
        update_resp = client.put(
            f"/api/sources/records/{record_id}",
            json={
                "label": "Updated Profile",
                "fields": [
                    {"field_id": "full_name", "value": "Alex Klick"},
                    {"field_id": "email", "value": "alex@example.com"},
                ],
            },
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["label"] == "Updated Profile"
        assert updated["revision_count"] >= 1

    def test_delete_record(self, client):
        create_resp = client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "Delete Me"},
        )
        record_id = create_resp.json()["record_id"]
        delete_resp = client.delete(f"/api/sources/records/{record_id}")
        assert delete_resp.status_code == 200
        get_resp = client.get(f"/api/sources/records/{record_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_record(self, client):
        resp = client.get("/api/sources/records/nonexistent")
        assert resp.status_code == 404


class TestRevisionEndpoints:
    def test_list_revisions_after_update(self, client):
        create_resp = client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "Profile"},
        )
        record_id = create_resp.json()["record_id"]
        client.put(
            f"/api/sources/records/{record_id}",
            json={"fields": [{"field_id": "full_name", "value": "Test"}]},
        )
        revisions_resp = client.get(
            f"/api/sources/records/{record_id}/revisions"
        )
        assert revisions_resp.status_code == 200
        revisions = revisions_resp.json()
        assert len(revisions) >= 1
        assert revisions[0]["provenance"] == "manual_edit"


class TestExtractionEndpoint:
    def test_extract_suggestions(self, client):
        create_resp = client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "Profile"},
        )
        record_id = create_resp.json()["record_id"]
        extract_resp = client.post(
            f"/api/sources/records/{record_id}/extract",
            json={"note_text": "Full Name: Alex Klick\nEmail: test@example.com"},
        )
        assert extract_resp.status_code == 200
        data = extract_resp.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) >= 1

    def test_extract_nonexistent_record(self, client):
        resp = client.post(
            "/api/sources/records/nonexistent/extract",
            json={"note_text": "some text"},
        )
        assert resp.status_code == 404


class TestBatchNormalizeEndpoint:
    def test_batch_normalize_returns_immediately(self, client):
        client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "A"},
        )
        resp = client.post(
            "/api/sources/normalize",
            json={"note_text": "Full Name: Test User"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("started", "processing")
        assert data["records_scanned"] == 1

    def test_batch_normalize_with_auto_apply(self, client):
        client.post(
            "/api/sources/records",
            json={"archetype": "new_grad", "label": "A"},
        )
        resp = client.post(
            "/api/sources/normalize",
            json={"note_text": "Full Name: Auto Applied", "auto_apply": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] in ("started", "processing")
