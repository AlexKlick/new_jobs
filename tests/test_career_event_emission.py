"""Tests for career event emission from all 5 upstream service domains.

Verifies that mutation points in source, search, list, research, and application
services emit graph-ingest events with correct category, action, and entity_id.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from graph.career_event_bus import emit_career_event, CareerEventBus
from graph.career_event_store import CareerEventStore


@pytest.fixture()
def event_store(tmp_path: Path) -> CareerEventStore:
    """Create a temp-backed event store for each test."""
    db_path = tmp_path / "test_events.db"
    store = CareerEventStore(db_path=db_path)
    # Patch the bus singleton to use this store
    bus = CareerEventBus(store=store)
    import graph.career_event_bus as bus_mod
    bus_mod._bus = bus
    yield store
    bus_mod._bus = None


# ── Test 1: Source create emits event ──────────────────────────────────────────


class TestSourceEmission:
    def test_create_source_record_emits_source_created_event(self, event_store, tmp_path):
        from research.source_service import SourceService

        db_dir = tmp_path / "sources"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "source_metadata.db"

        import research.source_service as ss
        with patch.object(ss, "SOURCES_DIR", db_dir), \
             patch.object(ss, "SOURCES_DB", db_path):
            service = SourceService()
            record = service.create_record("new_grad", "Test Record")

        events = event_store.list_events(category="source")
        assert len(events) >= 1
        created_events = [e for e in events if e.action == "source_record_created"]
        assert len(created_events) == 1
        assert created_events[0].entity_id == record.record_id
        assert created_events[0].entity_type == "source_record"

    def test_update_source_record_emits_source_updated_event(self, event_store, tmp_path):
        from research.source_service import SourceService

        db_dir = tmp_path / "sources"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "source_metadata.db"

        import research.source_service as ss
        with patch.object(ss, "SOURCES_DIR", db_dir), \
             patch.object(ss, "SOURCES_DB", db_path):
            service = SourceService()
            record = service.create_record("new_grad", "Test Record")
            service.update_record(
                record.record_id,
                label=None,
                fields=[{"field_id": "full_name", "value": "Alex"}],
            )

        events = event_store.list_events(category="source")
        updated_events = [e for e in events if e.action == "source_record_updated"]
        assert len(updated_events) == 1
        assert updated_events[0].entity_id == record.record_id


# ── Test 3: Search run started emits event ─────────────────────────────────────


class TestSearchEmission:
    def test_start_search_run_emits_search_run_started_event(self, event_store):
        from search.search_service import start_search_run
        from search.search_store import SearchPreferenceModel

        pref = SearchPreferenceModel(
            preference_id="pref-test",
            label="Test",
            archetype="experienced",
            keywords=["python"],
            locations=["Remote"],
            sources=["greenhouse"],
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        with patch("search.search_service.get_search_store") as mock_get_store, \
             patch("asyncio.create_task"):
            mock_store = MagicMock()
            mock_run = MagicMock()
            mock_run.run_id = "run-test123"
            mock_store.create_run.return_value = mock_run
            mock_get_store.return_value = mock_store

            run_id = start_search_run(pref)

        events = event_store.list_events(category="search")
        started_events = [e for e in events if e.action == "search_run_started"]
        assert len(started_events) == 1
        assert started_events[0].entity_id == "run-test123"

    @pytest.mark.asyncio
    async def test_execute_search_run_emits_search_run_completed_event(self, event_store):
        from search.search_service import execute_search_run
        from search.search_store import SearchPreferenceModel

        pref = SearchPreferenceModel(
            preference_id="pref-test",
            label="Test",
            archetype="experienced",
            keywords=["python"],
            locations=["Remote"],
            sources=[],  # Empty sources for quick test
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        mock_store = MagicMock()
        mock_store.compute_run_counts.return_value = (0, 0, 0)

        with patch("search.search_service.get_search_store", return_value=mock_store):
            await execute_search_run("run-complete-test", pref)

        events = event_store.list_events(category="search")
        completed_events = [e for e in events if e.action == "search_run_completed"]
        assert len(completed_events) == 1
        assert completed_events[0].entity_id == "run-complete-test"


# ── Test 5-7: List mutation emissions ──────────────────────────────────────────


class TestListEmission:
    def test_reorder_items_emits_list_item_reordered_event(self, event_store):
        from search.search_store import SearchStore

        with patch("search.search_store.SearchStore.__init__", lambda self, db_path=None: None):
            store = SearchStore()

        mock_conn = MagicMock()
        mock_conn.execute.return_value = MagicMock(rowcount=1)
        with patch("search.search_store._get_db", return_value=mock_conn):
            store.reorder_items("list-1", ["item-a", "item-b"])

        events = event_store.list_events(category="list")
        reordered_events = [e for e in events if e.action == "list_item_reordered"]
        assert len(reordered_events) == 1
        assert reordered_events[0].entity_id == "list-1"

    def test_remove_item_emits_list_item_removed_event(self, event_store, tmp_path):
        from search.search_store import SearchStore, _get_db

        # Use a real database to avoid mock complexity with context managers
        db_path = tmp_path / "search_test.db"
        import search.search_store as store_mod
        with patch.object(store_mod, "SEARCH_DB", db_path):
            store = SearchStore()
            # Create a run, candidate, list, and list item to test with
            pref = store.create_preference("Test", "experienced", ["py"], ["Remote"], ["greenhouse"])
            run = store.create_run(pref.preference_id, "Test")
            cand = store.add_candidate(run.run_id, "greenhouse", "https://gh.io/x/jobs/1", "Co", "Role", None, None, None, None, "https://gh.io/x/jobs/1")
            lst = store.create_list_for_run(run.run_id, "Test List")
            store.add_candidates_to_list_from_run(run.run_id)
            # Get the item_id
            detail = store.get_list_detail(lst.list_id)
            assert detail is not None and len(detail.items) > 0
            item_id = detail.items[0].item_id

            result = store.remove_item(item_id)

        assert result is True
        events = event_store.list_events(category="list")
        removed_events = [e for e in events if e.action == "list_item_removed"]
        assert len(removed_events) == 1
        assert removed_events[0].entity_id == item_id

    def test_mark_item_promoted_emits_list_item_promoted_event(self, event_store, tmp_path):
        from search.search_store import SearchStore

        db_path = tmp_path / "search_test2.db"
        import search.search_store as store_mod
        with patch.object(store_mod, "SEARCH_DB", db_path):
            store = SearchStore()
            pref = store.create_preference("Test", "experienced", ["py"], ["Remote"], ["greenhouse"])
            run = store.create_run(pref.preference_id, "Test")
            cand = store.add_candidate(run.run_id, "greenhouse", "https://gh.io/x/jobs/2", "Co", "Role", None, None, None, None, "https://gh.io/x/jobs/2")
            lst = store.create_list_for_run(run.run_id, "Test List")
            store.add_candidates_to_list_from_run(run.run_id)
            detail = store.get_list_detail(lst.list_id)
            assert detail is not None and len(detail.items) > 0
            item_id = detail.items[0].item_id

            result = store.mark_item_promoted(item_id)

        assert result is True
        events = event_store.list_events(category="list")
        promoted_events = [e for e in events if e.action == "list_item_promoted"]
        assert len(promoted_events) == 1
        assert promoted_events[0].entity_id == item_id


# ── Test 8-9: Research refresh emissions ───────────────────────────────────────


class TestResearchEmission:
    def test_start_research_refresh_emits_research_refresh_started_event(self, event_store):
        from research.company_research_service import start_research_refresh

        with patch("research.company_research_service.get_research_store") as mock_get_store, \
             patch("asyncio.create_task"):
            mock_store = MagicMock()
            mock_refresh = MagicMock()
            mock_refresh.refresh_id = "refresh-test123"
            mock_store.create_refresh.return_value = mock_refresh
            mock_get_store.return_value = mock_store

            refresh_id = start_research_refresh("test-company", "Test Company")

        assert refresh_id == "refresh-test123"
        events = event_store.list_events(category="research")
        started_events = [e for e in events if e.action == "research_refresh_started"]
        assert len(started_events) == 1
        assert started_events[0].entity_id == "refresh-test123"

    @pytest.mark.asyncio
    async def test_execute_research_refresh_emits_completed_event(self, event_store):
        from research.company_research_service import execute_research_refresh

        mock_store = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.snapshot_id = "snap-1"
        mock_store.create_snapshot.return_value = mock_snapshot
        mock_store.get_company_name.return_value = "Test Company"

        with patch("research.company_research_service.get_research_store", return_value=mock_store), \
             patch("research.company_research_service.acquire_artifacts", new_callable=AsyncMock, return_value=[]), \
             patch("research.company_research_service.persist_raw_artifacts", return_value=[]), \
             patch("research.company_research_service.normalize_artifacts", return_value={"claims": [], "questions": []}):
            await execute_research_refresh("refresh-complete-test", "test-company")

        events = event_store.list_events(category="research")
        completed_events = [e for e in events if e.action == "research_refresh_completed"]
        assert len(completed_events) == 1
        assert completed_events[0].entity_id == "refresh-complete-test"


# ── Test 10: Application (canonical ingest) emission ───────────────────────────


class TestApplicationEmission:
    @pytest.mark.asyncio
    async def test_ingest_emits_application_ingested_event(self, event_store):
        from canonical_ingest import ingest_candidate_into_canonical_inventory, CanonicalIngestResult

        candidate = MagicMock()
        candidate.candidate_id = "cand-ingest-1"
        candidate.company = "Acme Corp"
        candidate.role = "Senior Engineer"
        candidate.apply_url = "https://example.com/apply"
        candidate.source_url = "https://example.com/job"

        # The function will find an existing match and return it
        manifest = [{"job": {"apply_url": "https://example.com/apply", "company": "Acme Corp", "role": "Senior Engineer"}, "canonical_index": 5}]

        result = await ingest_candidate_into_canonical_inventory(
            candidate,
            settings=MagicMock(),
            load_jobs_manifest=lambda: manifest,
        )

        events = event_store.list_events(category="application")
        ingested_events = [e for e in events if e.action == "application_ingested"]
        assert len(ingested_events) == 1
        assert ingested_events[0].entity_id == "cand-ingest-1"
