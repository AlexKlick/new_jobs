"""Tests for search_store.py — preferences, runs, candidates, and deduplication."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Redirect the search DB to a temp path for each test."""
    import search_store as ss

    db_dir = tmp_path / "search"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "search.db"

    monkeypatch.setattr(ss, "SEARCH_DIR", db_dir)
    monkeypatch.setattr(ss, "SEARCH_DB", db_path)
    # Reset singleton so each test gets a fresh store
    ss._search_store = None
    yield
    ss._search_store = None


def monkeypatch_setattr(module, name, value):
    """Set a module-level attribute via monkeypatch."""
    import sys
    if hasattr(module, "__name__"):
        pass
    # Use direct setattr on the module
    setattr(module, name, value)


class TestPreferenceCRUD:
    def test_create_preference_returns_valid_model(self):
        from search_store import get_search_store

        store = get_search_store()
        pref = store.create_preference(
            label="SWE Search",
            archetype="experienced",
            keywords=["python", "golang"],
            locations=["Remote", "New York"],
            sources=["greenhouse", "lever"],
            experience_level="senior",
            remote_policy="remote",
            salary_min=150000,
        )

        assert pref.label == "SWE Search"
        assert pref.archetype == "experienced"
        assert pref.keywords == ["python", "golang"]
        assert pref.locations == ["Remote", "New York"]
        assert pref.sources == ["greenhouse", "lever"]
        assert pref.experience_level == "senior"
        assert pref.remote_policy == "remote"
        assert pref.salary_min == 150000
        assert pref.preference_id.startswith("pref-")
        assert pref.created_at is not None

    def test_list_preferences_returns_created(self):
        from search_store import get_search_store

        store = get_search_store()
        created = store.create_preference(
            label="List Test",
            archetype="new_grad",
            keywords=["rust"],
            locations=["Berlin"],
            sources=["lever"],
        )

        prefs = store.list_preferences()
        assert any(p.preference_id == created.preference_id for p in prefs)

    def test_get_preference_retrieves_by_id(self):
        from search_store import get_search_store

        store = get_search_store()
        created = store.create_preference(
            label="Get Test",
            archetype="experienced",
            keywords=["ml"],
            locations=["London"],
            sources=["greenhouse"],
        )

        retrieved = store.get_preference(created.preference_id)
        assert retrieved is not None
        assert retrieved.label == "Get Test"
        assert retrieved.keywords == ["ml"]

    def test_get_preference_unknown_returns_none(self):
        from search_store import get_search_store

        store = get_search_store()
        assert store.get_preference("pref-does-not-exist") is None

    def test_delete_preference_removes_it(self):
        from search_store import get_search_store

        store = get_search_store()
        created = store.create_preference(
            label="Delete Me",
            archetype="new_grad",
            keywords=["java"],
            locations=["Tokyo"],
            sources=["lever"],
        )

        deleted = store.delete_preference(created.preference_id)
        assert deleted is True
        assert store.get_preference(created.preference_id) is None


class TestRunIsolation:
    def test_create_run_returns_unique_run_ids(self):
        from search_store import get_search_store

        store = get_search_store()
        run1 = store.create_run(preference_id=None, preference_label="Run 1")
        run2 = store.create_run(preference_id=None, preference_label="Run 2")

        assert run1.run_id != run2.run_id
        assert run1.run_id.startswith("run-")
        assert run2.run_id.startswith("run-")
        assert run1.status == "pending"
        assert run2.status == "pending"

    def test_runs_have_isolated_candidate_sets(self):
        from search_store import get_search_store

        store = get_search_store()
        run1 = store.create_run(preference_id=None, preference_label="Run A")
        run2 = store.create_run(preference_id=None, preference_label="Run B")

        # Add a candidate to run1 only
        store.add_candidate(
            run_id=run1.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/stripe/jobs/1",
            company="Stripe",
            role="Software Engineer",
            location="Remote",
            salary=None,
            remote="yes",
            posted_date="2025-01-15",
            apply_url="https://apply.stripe.com",
        )

        # Run2 should have no candidates
        cands_run2 = store.list_candidates_for_run(run2.run_id)
        assert len(cands_run2) == 0


class TestCandidateDedupNew:
    def test_add_candidate_novel_returns_is_duplicate_false(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Dedup Test")

        cand = store.add_candidate(
            run_id=run.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            company="Acme",
            role="Backend Engineer",
            location="New York",
            salary=None,
            remote=None,
            posted_date="2025-02-01",
            apply_url="https://apply.acme.com",
        )

        assert cand.is_duplicate is False
        assert cand.duplicate_of_candidate_id is None
        assert cand.identity_key is not None


class TestCandidateDedupDuplicate:
    def test_add_candidate_same_company_role_returns_is_duplicate_true(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Dedup Test")

        cand1 = store.add_candidate(
            run_id=run.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            company="Acme",
            role="Backend Engineer",
            location="New York",
            salary=None,
            remote=None,
            posted_date="2025-02-01",
            apply_url="https://apply.acme.com",
        )

        cand2 = store.add_candidate(
            run_id=run.run_id,
            source="lever",
            source_url="https://jobs.lever.co/acme/2",
            company="Acme",
            role="Backend Engineer",
            location="New York",
            salary=None,
            remote=None,
            posted_date="2025-02-05",
            apply_url="https://apply.acme.com/v2",
        )

        assert cand2.is_duplicate is True
        assert cand2.duplicate_of_candidate_id == cand1.candidate_id


class TestCandidateDedupAcrossRuns:
    def test_duplicate_flagged_across_separate_runs(self):
        from search_store import get_search_store

        store = get_search_store()
        run1 = store.create_run(preference_id=None, preference_label="Run 1")
        run2 = store.create_run(preference_id=None, preference_label="Run 2")

        # Add to run1
        cand1 = store.add_candidate(
            run_id=run1.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/bootstore/jobs/1",
            company="BootStore",
            role="Frontend Developer",
            location="San Francisco",
            salary="$130k",
            remote=None,
            posted_date="2025-03-01",
            apply_url="https://apply.bootstore.com",
        )

        # Same company+role in run2
        cand2 = store.add_candidate(
            run_id=run2.run_id,
            source="lever",
            source_url="https://jobs.lever.co/bootstore/99",
            company="BootStore",
            role="Frontend Developer",
            location="San Francisco",
            salary=None,
            remote=None,
            posted_date="2025-03-10",
            apply_url="https://apply.bootstore.com/v2",
        )

        assert cand2.is_duplicate is True
        assert cand2.duplicate_of_candidate_id == cand1.candidate_id
        # Verify both candidates still exist in their respective runs
        cands_run1 = store.list_candidates_for_run(run1.run_id)
        cands_run2 = store.list_candidates_for_run(run2.run_id)
        assert len(cands_run1) == 1
        assert len(cands_run2) == 1


class TestComputeRunCounts:
    def test_compute_run_counts_returns_correct_totals(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Count Test")

        # Add 3 candidates: 2 new, 1 duplicate
        store.add_candidate(
            run_id=run.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company X",
            role="Engineer 1",
            location="NYC",
            salary=None,
            remote=None,
            posted_date="2025-01-01",
            apply_url="https://apply.x.com/1",
        )
        store.add_candidate(
            run_id=run.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/2",
            company="Company Y",
            role="Engineer 2",
            location="LA",
            salary=None,
            remote=None,
            posted_date="2025-01-02",
            apply_url="https://apply.y.com/2",
        )
        # This one is a duplicate of the first
        store.add_candidate(
            run_id=run.run_id,
            source="lever",
            source_url="https://jobs.lever.co/x/3",
            company="Company X",
            role="Engineer 1",  # Same company+role as first
            location="NYC",
            salary=None,
            remote=None,
            posted_date="2025-01-03",
            apply_url="https://apply.x.com/3",
        )

        total, new, dup = store.compute_run_counts(run.run_id)
        assert total == 3
        assert new == 2
        assert dup == 1


class TestMarkIngested:
    def test_mark_candidate_ingested_sets_flag(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Ingest Test")

        cand = store.add_candidate(
            run_id=run.run_id,
            source="greenhouse",
            source_url="https://boards.greenhouse.io/p/jobs/1",
            company="P Corp",
            role="Product Manager",
            location="Austin",
            salary=None,
            remote=None,
            posted_date="2025-04-01",
            apply_url="https://apply.p.com",
        )

        assert cand.ingested is False
        result = store.mark_candidate_ingested(cand.candidate_id)
        assert result is True

        # Verify the flag is persisted via list
        candidates = store.list_candidates_for_run(run.run_id)
        assert len(candidates) == 1
        assert candidates[0].ingested is True


class TestComputeIdentityKey:
    def test_identity_key_is_stable_and_normalized(self):
        from search_store import get_search_store, SearchStore

        key1 = SearchStore._compute_identity_key("Stripe", "Software Engineer")
        key2 = SearchStore._compute_identity_key("stripe", "software engineer")
        key3 = SearchStore._compute_identity_key("  STRIPE  ", "  SOFTWARE ENGINEER  ")

        # Same normalized input must produce same key
        assert key1 == key2 == key3
        # Key should contain both company and role
        assert "stripe" in key1
        assert "software engineer" in key1
        # Pipe-separated format
        assert "|" in key1


class TestListCreation:
    def test_create_list_for_run_returns_list_model(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="List Test Run")

        lst = store.create_list_for_run(run_id=run.run_id, label="My List")

        assert lst.list_id.startswith("list-")
        assert lst.run_id == run.run_id
        assert lst.label == "My List"
        assert lst.created_at is not None

    def test_get_list_for_run_returns_created_list(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Get List Test")
        created = store.create_list_for_run(run_id=run.run_id, label="Run Results")

        retrieved = store.get_list_for_run(run.run_id)

        assert retrieved is not None
        assert retrieved.list_id == created.list_id
        assert retrieved.label == "Run Results"

    def test_get_list_for_run_returns_none_for_unknown_run(self):
        from search_store import get_search_store

        store = get_search_store()
        assert store.get_list_for_run("run-does-not-exist") is None


class TestListPopulateFromRun:
    def test_add_candidates_to_list_from_run_adds_non_duplicates(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Populate Test")

        # Add two candidates - one new, one duplicate
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company X", role="Engineer A",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.x.com/1",
        )
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/2",
            company="Company Y", role="Engineer B",
            location="LA", salary=None, remote=None,
            posted_date="2025-01-02", apply_url="https://apply.y.com/2",
        )
        # Create list and populate
        store.create_list_for_run(run_id=run.run_id, label="Populated List")
        count = store.add_candidates_to_list_from_run(run.run_id)

        assert count == 2
        detail = store.get_list_detail(store.get_list_for_run(run.run_id).list_id)
        assert len(detail.items) == 2
        # Items should be ordered by original created_at
        assert detail.items[0].position == 0
        assert detail.items[1].position == 1


class TestListItemRemoval:
    def test_remove_item_deletes_item(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Remove Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Remove List")
        store.add_candidates_to_list_from_run(run.run_id)

        detail = store.get_list_detail(store.get_list_for_run(run.run_id).list_id)
        first_item_id = detail.items[0].item_id

        removed = store.remove_item(first_item_id)
        assert removed is True

        # Item should be gone
        assert store.get_item(first_item_id) is None

    def test_remove_item_returns_false_for_unknown(self):
        from search_store import get_search_store

        store = get_search_store()
        assert store.remove_item("item-unknown") is False


class TestListReorder:
    def test_reorder_items_changes_positions(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Reorder Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.add_candidate(
            run_id=run.run_id, source="lever",
            source_url="https://jobs.lever.co/x/2",
            company="Company B", role="Engineer Y",
            location="LA", salary=None, remote=None,
            posted_date="2025-01-02", apply_url="https://apply.b.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Reorder List")
        store.add_candidates_to_list_from_run(run.run_id)

        lst = store.get_list_for_run(run.run_id)
        detail = store.get_list_detail(lst.list_id)
        assert len(detail.items) == 2

        # Reverse the order
        reversed_ids = [detail.items[1].item_id, detail.items[0].item_id]
        store.reorder_items(lst.list_id, reversed_ids)

        # Re-fetch and verify
        updated = store.get_list_detail(lst.list_id)
        assert updated.items[0].item_id == detail.items[1].item_id
        assert updated.items[1].item_id == detail.items[0].item_id


class TestListItemMetadata:
    def test_update_item_notes(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Notes Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Notes List")
        store.add_candidates_to_list_from_run(run.run_id)

        lst = store.get_list_for_run(run.run_id)
        detail = store.get_list_detail(lst.list_id)
        item_id = detail.items[0].item_id

        result = store.update_item_notes(item_id, "Looks promising!")
        assert result is True

        updated = store.get_item(item_id)
        assert updated.notes == "Looks promising!"

    def test_update_item_priority(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Priority Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Priority List")
        store.add_candidates_to_list_from_run(run.run_id)

        lst = store.get_list_for_run(run.run_id)
        detail = store.get_list_detail(lst.list_id)
        item_id = detail.items[0].item_id

        store.update_item_priority(item_id, "high")
        updated = store.get_item(item_id)
        assert updated.priority == "high"

    def test_update_item_status(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Status Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Status List")
        store.add_candidates_to_list_from_run(run.run_id)

        lst = store.get_list_for_run(run.run_id)
        detail = store.get_list_detail(lst.list_id)
        item_id = detail.items[0].item_id

        store.update_item_status(item_id, "applied")
        updated = store.get_item(item_id)
        assert updated.status == "applied"

    def test_mark_item_promoted(self):
        from search_store import get_search_store

        store = get_search_store()
        run = store.create_run(preference_id=None, preference_label="Promote Test")
        store.add_candidate(
            run_id=run.run_id, source="greenhouse",
            source_url="https://boards.greenhouse.io/x/jobs/1",
            company="Company A", role="Engineer X",
            location="NYC", salary=None, remote=None,
            posted_date="2025-01-01", apply_url="https://apply.a.com",
        )
        store.create_list_for_run(run_id=run.run_id, label="Promote List")
        store.add_candidates_to_list_from_run(run.run_id)

        lst = store.get_list_for_run(run.run_id)
        detail = store.get_list_detail(lst.list_id)
        item_id = detail.items[0].item_id

        assert store.get_item(item_id).promoted is False
        store.mark_item_promoted(item_id)
        assert store.get_item(item_id).promoted is True
