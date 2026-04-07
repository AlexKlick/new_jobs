"""Tests for research_store.py -- companies, snapshots, claims, questions, and refreshes."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Redirect the research DB to a temp path for each test."""
    import research_store as rs

    db_dir = tmp_path / "research"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "research.db"

    monkeypatch.setattr(rs, "RESEARCH_DIR", db_dir)
    monkeypatch.setattr(rs, "RESEARCH_DB", db_path)
    # Reset singleton so each test gets a fresh store
    rs._research_store = None
    yield
    rs._research_store = None


# ── Company Tests ────────────────────────────────────────────────────────────────


class TestCompanyCRUD:
    def test_ensure_company_creates_record(self):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")

        name = store.get_company_name("acme-corp")
        assert name == "Acme Corp"

    def test_ensure_company_idempotent(self):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        store.ensure_company("acme-corp", "Acme Corp Updated")

        # Name should NOT change on re-ensure
        name = store.get_company_name("acme-corp")
        assert name == "Acme Corp"

    def test_get_company_name_returns_none_for_unknown(self):
        from research_store import get_research_store

        store = get_research_store()
        assert store.get_company_name("no-such-company") is None

    def test_list_companies_returns_empty(self):
        from research_store import get_research_store

        store = get_research_store()
        assert store.list_companies() == []

    def test_list_companies_returns_created(self):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        store.ensure_company("beta-inc", "Beta Inc")

        companies = store.list_companies()
        assert len(companies) == 2
        keys = {c["company_key"] for c in companies}
        assert keys == {"acme-corp", "beta-inc"}

    def test_get_company_detail_returns_none_for_unknown(self):
        from research_store import get_research_store

        store = get_research_store()
        assert store.get_company_detail("no-such-company") is None


# ── Snapshot Tests ───────────────────────────────────────────────────────────────


class TestSnapshotCRUD:
    def _seed_company(self, store):
        store.ensure_company("acme-corp", "Acme Corp")

    def test_create_snapshot(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        snap = store.create_snapshot("acme-corp", source_count=2)
        assert snap.snapshot_id.startswith("snap-")
        assert snap.company_key == "acme-corp"
        assert snap.source_count == 2
        assert snap.status == "pending"

    def test_complete_snapshot(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        snap = store.create_snapshot("acme-corp")
        store.complete_snapshot(snap.snapshot_id, claim_count=3, question_count=2)

        snapshots = store.list_snapshots("acme-corp")
        assert len(snapshots) == 1
        assert snapshots[0].status == "completed"
        assert snapshots[0].claim_count == 3
        assert snapshots[0].question_count == 2

    def test_fail_snapshot(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        snap = store.create_snapshot("acme-corp")
        store.fail_snapshot(snap.snapshot_id, "Network error")

        snapshots = store.list_snapshots("acme-corp")
        assert snapshots[0].status == "failed"
        assert snapshots[0].error_message == "Network error"

    def test_list_snapshots_ordered_newest_first(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        snap1 = store.create_snapshot("acme-corp")
        snap2 = store.create_snapshot("acme-corp")

        snapshots = store.list_snapshots("acme-corp")
        assert len(snapshots) == 2
        assert snapshots[0].snapshot_id == snap2.snapshot_id
        assert snapshots[1].snapshot_id == snap1.snapshot_id


# ── Claim Tests ──────────────────────────────────────────────────────────────────


class TestClaimCRUD:
    def _seed_with_snapshot(self, store):
        store.ensure_company("acme-corp", "Acme Corp")
        snap = store.create_snapshot("acme-corp")
        return snap.snapshot_id

    def test_add_claim(self):
        from research_store import get_research_store

        store = get_research_store()
        snap_id = self._seed_with_snapshot(store)

        claim = store.add_claim(
            snapshot_id=snap_id,
            company_key="acme-corp",
            claim_text="Acme uses Python for backend",
            source_url="https://glassdoor.com/acme",
            collected_at="2026-01-01T00:00:00Z",
            confidence="high",
            themes=["engineering", "culture"],
            role_applicability=["SWE", "Backend"],
        )

        assert claim.claim_id.startswith("claim-")
        assert claim.claim_text == "Acme uses Python for backend"
        assert claim.confidence == "high"
        assert claim.themes == ["engineering", "culture"]

    def test_claims_appear_in_company_detail(self):
        from research_store import get_research_store

        store = get_research_store()
        snap_id = self._seed_with_snapshot(store)

        store.add_claim(
            snapshot_id=snap_id,
            company_key="acme-corp",
            claim_text="Claim A",
            source_url="https://example.com/a",
            collected_at="2026-01-01T00:00:00Z",
        )
        store.add_claim(
            snapshot_id=snap_id,
            company_key="acme-corp",
            claim_text="Claim B",
            source_url="https://example.com/b",
            collected_at="2026-01-02T00:00:00Z",
        )

        detail = store.get_company_detail("acme-corp")
        assert detail is not None
        assert len(detail["claims"]) == 2

    def test_get_claims_for_snapshot(self):
        from research_store import get_research_store

        store = get_research_store()
        snap_id = self._seed_with_snapshot(store)

        store.add_claim(
            snapshot_id=snap_id,
            company_key="acme-corp",
            claim_text="Snapshot claim",
            source_url="https://example.com",
            collected_at="2026-01-01T00:00:00Z",
        )

        claims = store.get_claims_for_snapshot(snap_id)
        assert len(claims) == 1
        assert claims[0].claim_text == "Snapshot claim"


# ── Interview Question Tests ─────────────────────────────────────────────────────


class TestInterviewQuestionCRUD:
    def _seed_with_snapshot(self, store):
        store.ensure_company("acme-corp", "Acme Corp")
        snap = store.create_snapshot("acme-corp")
        return snap.snapshot_id

    def test_add_interview_question(self):
        from research_store import get_research_store

        store = get_research_store()
        snap_id = self._seed_with_snapshot(store)

        q = store.add_interview_question(
            snapshot_id=snap_id,
            company_key="acme-corp",
            question_text="Tell me about a time you dealt with ambiguity",
            source_url="https://glassdoor.com/acme/interview",
            collected_at="2026-01-01T00:00:00Z",
            role_applicability=["SWE"],
            themes=["behavioral"],
        )

        assert q.question_id.startswith("iq-")
        assert q.question_text == "Tell me about a time you dealt with ambiguity"
        assert q.role_applicability == ["SWE"]

    def test_questions_appear_in_company_detail(self):
        from research_store import get_research_store

        store = get_research_store()
        snap_id = self._seed_with_snapshot(store)

        store.add_interview_question(
            snapshot_id=snap_id,
            company_key="acme-corp",
            question_text="Q1",
            source_url="https://example.com",
            collected_at="2026-01-01T00:00:00Z",
        )

        detail = store.get_company_detail("acme-corp")
        assert detail is not None
        assert len(detail["questions"]) == 1
        assert detail["questions"][0]["question_text"] == "Q1"


# ── Refresh Tests ────────────────────────────────────────────────────────────────


class TestRefreshCRUD:
    def _seed_company(self, store):
        store.ensure_company("acme-corp", "Acme Corp")

    def test_create_refresh(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        refresh = store.create_refresh("acme-corp", sources_total=2)
        assert refresh.refresh_id.startswith("refresh-")
        assert refresh.company_key == "acme-corp"
        assert refresh.status == "pending"
        assert refresh.sources_total == 2

    def test_update_refresh_to_running(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        refresh = store.create_refresh("acme-corp")
        store.update_refresh(refresh.refresh_id, status="running", current_source="glassdoor")

        updated = store.get_refresh(refresh.refresh_id)
        assert updated is not None
        assert updated.status == "running"
        assert updated.current_source == "glassdoor"

    def test_update_refresh_to_completed(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        refresh = store.create_refresh("acme-corp")
        store.update_refresh(
            refresh.refresh_id,
            status="completed",
            sources_completed=2,
        )

        updated = store.get_refresh(refresh.refresh_id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.completed_at is not None

    def test_update_refresh_to_failed(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        refresh = store.create_refresh("acme-corp")
        store.update_refresh(
            refresh.refresh_id,
            status="failed",
            error_message="Connection timeout",
        )

        updated = store.get_refresh(refresh.refresh_id)
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message == "Connection timeout"
        assert updated.completed_at is not None

    def test_get_refresh_returns_none_for_unknown(self):
        from research_store import get_research_store

        store = get_research_store()
        assert store.get_refresh("refresh-nonexistent") is None

    def test_get_active_refresh(self):
        from research_store import get_research_store

        store = get_research_store()
        self._seed_company(store)

        # No active refresh initially
        assert store.get_active_refresh("acme-corp") is None

        # Create one
        refresh = store.create_refresh("acme-corp")
        active = store.get_active_refresh("acme-corp")
        assert active is not None
        assert active.refresh_id == refresh.refresh_id

        # Complete it - no longer active
        store.update_refresh(refresh.refresh_id, status="completed")
        assert store.get_active_refresh("acme-corp") is None


# ── Company Detail Integration ───────────────────────────────────────────────────


class TestCompanyDetailIntegration:
    def test_full_company_detail_with_snapshots_claims_questions(self):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")

        snap = store.create_snapshot("acme-corp", source_count=2)

        store.add_claim(
            snapshot_id=snap.snapshot_id,
            company_key="acme-corp",
            claim_text="Fast-paced culture",
            source_url="https://glassdoor.com/acme",
            collected_at="2026-01-01T00:00:00Z",
            confidence="medium",
            themes=["culture"],
        )

        store.add_interview_question(
            snapshot_id=snap.snapshot_id,
            company_key="acme-corp",
            question_text="Describe your leadership style",
            source_url="https://glassdoor.com/acme/interview",
            collected_at="2026-01-01T00:00:00Z",
            themes=["behavioral"],
        )

        store.complete_snapshot(snap.snapshot_id, claim_count=1, question_count=1)

        detail = store.get_company_detail("acme-corp")
        assert detail is not None
        assert detail["company_key"] == "acme-corp"
        assert detail["company_name"] == "Acme Corp"
        assert len(detail["claims"]) == 1
        assert len(detail["questions"]) == 1
        assert len(detail["snapshots"]) == 1
        assert detail["snapshots"][0]["claim_count"] == 1

    def test_company_list_with_counts(self):
        from research_store import get_research_store

        store = get_research_store()
        store.ensure_company("acme-corp", "Acme Corp")
        store.ensure_company("beta-inc", "Beta Inc")

        # Only Acme has data
        snap = store.create_snapshot("acme-corp")
        store.add_claim(
            snapshot_id=snap.snapshot_id,
            company_key="acme-corp",
            claim_text="Some claim",
            source_url="https://example.com",
            collected_at="2026-01-01T00:00:00Z",
        )
        store.complete_snapshot(snap.snapshot_id, claim_count=1, question_count=0)

        companies = store.list_companies()
        acme = next(c for c in companies if c["company_key"] == "acme-corp")
        beta = next(c for c in companies if c["company_key"] == "beta-inc")

        assert acme["claim_count"] == 1
        assert beta["claim_count"] == 0


# ── Helper Tests ─────────────────────────────────────────────────────────────────


class TestComputeCompanyKey:
    def test_basic_slug(self):
        from research_store import compute_company_key

        assert compute_company_key("Acme Corp") == "acme-corp"

    def test_special_characters_removed(self):
        from research_store import compute_company_key

        assert compute_company_key("Acme, Inc.") == "acme-inc"

    def test_spaces_collapsed(self):
        from research_store import compute_company_key

        assert compute_company_key("Big  Tech  Corp") == "big-tech-corp"

    def test_empty_returns_unknown(self):
        from research_store import compute_company_key

        assert compute_company_key("") == "unknown-company"
        assert compute_company_key("!!!") == "unknown-company"
