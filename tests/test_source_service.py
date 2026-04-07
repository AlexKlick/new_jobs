"""Tests for source_service.py — source record CRUD, revisions, and note extraction."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Patch the project root to use a temp directory
_tmp = tempfile.mkdtemp(prefix="src_test_")
_TMP_PATH = Path(_tmp)


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """Redirect the source DB and artifact dir to a temp path for each test."""
    import source_service as ss

    db_dir = tmp_path / "sources"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "source_metadata.db"

    monkeypatch.setattr(ss, "SOURCES_DIR", db_dir)
    monkeypatch.setattr(ss, "SOURCES_DB", db_path)
    # Reset singleton
    ss._source_service = None
    yield
    ss._source_service = None


class TestArchetypeDefinitions:
    def test_list_archetypes_returns_two(self):
        from source_service import get_source_service
        svc = get_source_service()
        archs = svc.list_archetypes()
        assert len(archs) == 2
        labels = {a["archetype"] for a in archs}
        assert labels == {"new_grad", "experienced"}

    def test_get_archetype_new_grad(self):
        from source_service import get_source_service
        svc = get_source_service()
        arch = svc.get_archetype("new_grad")
        assert arch is not None
        assert arch["label"] == "New Graduate"
        assert any(f["field_id"] == "university" for f in arch["fields"])

    def test_get_archetype_experienced(self):
        from source_service import get_source_service
        svc = get_source_service()
        arch = svc.get_archetype("experienced")
        assert arch is not None
        assert any(f["field_id"] == "role_1" for f in arch["fields"])

    def test_get_archetype_unknown_returns_none(self):
        from source_service import get_source_service
        svc = get_source_service()
        assert svc.get_archetype("nonexistent") is None


class TestSourceRecordCRUD:
    def test_create_record_new_grad(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Test Grad Profile")
        assert rec.archetype == "new_grad"
        assert rec.label == "Test Grad Profile"
        assert rec.revision_count == 0
        assert len(rec.fields) > 0

    def test_create_record_experienced(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("experienced", "Senior Profile")
        assert rec.archetype == "experienced"
        assert len(rec.fields) > 0

    def test_create_record_invalid_archetype(self):
        from source_service import get_source_service
        svc = get_source_service()
        with pytest.raises(ValueError, match="Unknown archetype"):
            svc.create_record("invalid", "Nope")

    def test_list_records_empty(self):
        from source_service import get_source_service
        svc = get_source_service()
        assert svc.list_records() == []

    def test_list_records_after_create(self):
        from source_service import get_source_service
        svc = get_source_service()
        svc.create_record("new_grad", "A")
        svc.create_record("experienced", "B")
        records = svc.list_records()
        assert len(records) == 2

    def test_get_record(self):
        from source_service import get_source_service
        svc = get_source_service()
        created = svc.create_record("new_grad", "Profile")
        fetched = svc.get_record(created.record_id)
        assert fetched is not None
        assert fetched.record_id == created.record_id
        assert fetched.label == "Profile"

    def test_get_record_not_found(self):
        from source_service import get_source_service
        svc = get_source_service()
        assert svc.get_record("nonexistent") is None

    def test_update_record_fields(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        updated = svc.update_record(
            rec.record_id,
            label=None,
            fields=[
                {"field_id": "full_name", "value": "Alex Klick"},
                {"field_id": "email", "value": "alex@example.com"},
            ],
        )
        assert updated is not None
        assert updated.revision_count == 1
        name_field = next(f for f in updated.fields if f.field_id == "full_name")
        assert name_field.value == "Alex Klick"

    def test_update_record_creates_revision(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        svc.update_record(rec.record_id, label=None, fields=[
            {"field_id": "full_name", "value": "Test"},
        ])
        revisions = svc.list_revisions(rec.record_id)
        assert len(revisions) == 1
        assert revisions[0].provenance == "manual_edit"
        assert revisions[0].summary.startswith("Updated 1 field")

    def test_update_record_label(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Old Label")
        updated = svc.update_record(rec.record_id, label="New Label", fields=[])
        assert updated is not None
        assert updated.label == "New Label"

    def test_update_nonexistent_returns_none(self):
        from source_service import get_source_service
        svc = get_source_service()
        result = svc.update_record("nonexistent", label="X", fields=[])
        assert result is None

    def test_delete_record(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Delete Me")
        assert svc.delete_record(rec.record_id) is True
        assert svc.get_record(rec.record_id) is None

    def test_delete_nonexistent_returns_false(self):
        from source_service import get_source_service
        svc = get_source_service()
        assert svc.delete_record("nonexistent") is False


class TestRevisions:
    def test_revision_snapshot_preserves_old_values(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        svc.update_record(rec.record_id, label=None, fields=[
            {"field_id": "full_name", "value": "Updated Name"},
        ])
        revisions = svc.list_revisions(rec.record_id)
        assert len(revisions) == 1
        snapshot = json.loads(revisions[0].snapshot)
        # Snapshot should contain the old (empty) value for full_name
        name_in_snapshot = next(f for f in snapshot if f["field_id"] == "full_name")
        assert name_in_snapshot["value"] == ""

    def test_multiple_revisions(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        for i in range(3):
            svc.update_record(rec.record_id, label=None, fields=[
                {"field_id": "full_name", "value": f"Name {i}"},
            ])
        revisions = svc.list_revisions(rec.record_id)
        assert len(revisions) == 3
        # Most recent first
        assert revisions[0].created_at >= revisions[1].created_at


class TestNoteExtraction:
    def test_extract_suggestions_from_colon_format(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        svc.update_record(rec.record_id, label=None, fields=[
            {"field_id": "full_name", "value": "Old Name"},
        ])
        result = svc.extract_suggestions(rec.record_id, "Full Name: Alex Klick")
        assert len(result.suggestions) >= 1
        name_sug = next((s for s in result.suggestions if s.field_id == "full_name"), None)
        assert name_sug is not None
        assert name_sug.suggested_value == "Alex Klick"
        assert name_sug.current_value == "Old Name"

    def test_extract_suggestions_empty_note(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        result = svc.extract_suggestions(rec.record_id, "")
        assert result.suggestions == []

    def test_extract_suggestions_no_match(self):
        from source_service import get_source_service
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        result = svc.extract_suggestions(rec.record_id, "Random text that matches nothing")
        assert result.suggestions == []

    def test_extract_invalid_record_raises(self):
        from source_service import get_source_service
        svc = get_source_service()
        with pytest.raises(ValueError, match="Record not found"):
            svc.extract_suggestions("nonexistent", "some text")

    def test_apply_suggestion(self):
        from source_service import get_source_service
        from source_service import SourceSuggestionModel
        svc = get_source_service()
        rec = svc.create_record("new_grad", "Profile")
        suggestion = SourceSuggestionModel(
            suggestion_id="sug-test1234",
            record_id=rec.record_id,
            field_id="full_name",
            field_label="Full Name",
            current_value="",
            suggested_value="Alex Klick",
            confidence=0.8,
            source_note="Full Name: Alex Klick",
        )
        updated = svc.apply_suggestion(suggestion)
        assert updated is not None
        name_field = next(f for f in updated.fields if f.field_id == "full_name")
        assert name_field.value == "Alex Klick"
        revisions = svc.list_revisions(rec.record_id)
        assert len(revisions) == 1
        assert revisions[0].provenance == "note_extraction"
