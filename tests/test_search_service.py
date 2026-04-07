"""Tests for search_service.py — ATS query building, normalization, filtering, and run execution."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBuildQuery:
    def test_build_greenhouse_query_returns_string_with_boards_url(self):
        from search_service import build_greenhouse_query

        result = build_greenhouse_query(["python"], ["Remote"])
        assert isinstance(result, str)
        assert "boards.greenhouse.io" in result

    def test_build_lever_query_returns_string_with_api_url(self):
        from search_service import build_lever_query

        result = build_lever_query(["golang"], ["New York"])
        assert isinstance(result, str)
        assert "api.lever.co" in result


class TestURLBuilders:
    def test_greenhouse_search_url_returns_correct_format(self):
        from search_service import greenhouse_search_url

        url = greenhouse_search_url("stripe")
        assert url == "https://boards.greenhouse.io/stripe/jobs?content=true"

    def test_greenhouse_search_url_with_special_chars(self):
        from search_service import greenhouse_search_url

        url = greenhouse_search_url("notion")
        assert "notion" in url
        assert "boards.greenhouse.io" in url

    def test_lever_jobs_url_returns_correct_format(self):
        from search_service import lever_jobs_url

        url = lever_jobs_url("airbnb")
        assert url == "https://api.lever.co/v0/postings/airbnb?mode=json"


class TestNormalizeGreenhouse:
    def test_normalize_greenhouse_job_returns_correct_dict(self):
        from search_service import normalize_greenhouse_job

        raw = {
            "title": "Senior Software Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "id": 123,
            "metadata": [{"name": "Location", "value": ["San Francisco", "Remote"]}],
            "updated_at": "2025-06-15T10:00:00Z",
        }

        result = normalize_greenhouse_job(raw)

        assert result is not None
        assert result["company"] == "acme"
        assert result["role"] == "Senior Software Engineer"
        assert result["location"] == "San Francisco, Remote"
        assert result["source"] == "greenhouse"
        assert result["apply_url"] == "https://boards.greenhouse.io/acme/jobs/123"
        assert result["posted_date"] == "2025-06-15"

    def test_normalize_greenhouse_job_handles_missing_location(self):
        from search_service import normalize_greenhouse_job

        raw = {
            "title": "Engineer",
            "absolute_url": "https://boards.greenhouse.io/xyz/jobs/1",
            "metadata": [],
        }

        result = normalize_greenhouse_job(raw)
        assert result is not None
        assert result["location"] is None

    def test_normalize_greenhouse_job_returns_none_on_invalid_input(self):
        from search_service import normalize_greenhouse_job

        # Missing title (empty string) should return None
        assert normalize_greenhouse_job({"title": ""}) is None
        # None input should return None
        assert normalize_greenhouse_job(None) is None


class TestNormalizeLever:
    def test_normalize_lever_job_returns_correct_dict(self):
        from search_service import normalize_lever_job

        raw = {
            "text": "Product Designer",
            "company": "DesignCo",
            "urls": {"apply": "https://apply.designco.com/v2"},
            "categories": {"location": "Berlin"},
            "updatedAt": "2025-07-20T08:00:00Z",
        }

        result = normalize_lever_job(raw)

        assert result is not None
        assert result["company"] == "DesignCo"
        assert result["role"] == "Product Designer"
        assert result["location"] == "Berlin"
        assert result["source"] == "lever"
        assert result["apply_url"] == "https://apply.designco.com/v2"
        assert result["posted_date"] == "2025-07-20"

    def test_normalize_lever_job_uses_url_fallback_for_company(self):
        from search_service import normalize_lever_job

        raw = {
            "text": "Data Scientist",
            "urls": {"apply": "https://jobs.lever.co/datasci/42"},
            "categories": {"location": "London"},
        }

        result = normalize_lever_job(raw)
        assert result is not None
        assert result["company"] == "datasci"

    def test_normalize_lever_job_returns_none_on_invalid_input(self):
        from search_service import normalize_lever_job

        assert normalize_lever_job({}) is None
        assert normalize_lever_job(None) is None


class TestMatchesPreference:
    def test_matches_preference_keywords_match(self):
        from search_service import _matches_preference
        from search_store import SearchPreferenceModel
        from datetime import datetime, timezone

        pref = SearchPreferenceModel(
            preference_id="pref-test",
            label="Test",
            archetype="experienced",
            keywords=["python", "ml"],
            locations=[],
            sources=["greenhouse"],
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        cand = {
            "role": "ML Engineer",
            "company": "AI Corp",
            "location": "Remote",
        }

        assert _matches_preference(cand, pref) is True

    def test_matches_preference_location_match(self):
        from search_service import _matches_preference
        from search_store import SearchPreferenceModel
        from datetime import datetime, timezone

        pref = SearchPreferenceModel(
            preference_id="pref-test",
            label="Test",
            archetype="experienced",
            keywords=[],
            locations=["New York", "San Francisco"],
            sources=["greenhouse"],
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        cand = {
            "role": "Backend Dev",
            "company": "FinTech",
            "location": "New York",
        }

        assert _matches_preference(cand, pref) is True

    def test_matches_preference_no_match(self):
        from search_service import _matches_preference
        from search_store import SearchPreferenceModel
        from datetime import datetime, timezone

        pref = SearchPreferenceModel(
            preference_id="pref-test",
            label="Test",
            archetype="experienced",
            keywords=["rust"],
            locations=["Berlin"],
            sources=["lever"],
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Role doesn't match keywords and location doesn't match
        cand = {
            "role": "Python Developer",
            "company": "Web Co",
            "location": "London",
        }

        assert _matches_preference(cand, pref) is False


class TestExtractCompanyFromURL:
    def test_extract_greenhouse_company(self):
        from search_service import _extract_company_from_url

        company = _extract_company_from_url(
            "https://boards.greenhouse.io/stripe/jobs/123", "greenhouse"
        )
        assert company == "stripe"

    def test_extract_lever_company(self):
        from search_service import _extract_company_from_url

        company = _extract_company_from_url(
            "https://jobs.lever.co/airbnb/456", "lever"
        )
        assert company == "airbnb"

    def test_extract_falls_back_to_source_on_empty_url(self):
        from search_service import _extract_company_from_url

        company = _extract_company_from_url("", "unknown")
        assert company == "unknown"


class TestStartSearchRun:
    def test_start_search_run_calls_create_run(self):
        from search_service import start_search_run
        from search_store import SearchPreferenceModel
        from datetime import datetime, timezone
        from unittest.mock import patch, MagicMock

        pref = SearchPreferenceModel(
            preference_id="pref-start-test",
            label="Start Test",
            archetype="experienced",
            keywords=["python"],
            locations=["Remote"],
            sources=["greenhouse"],
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        mock_run = MagicMock()
        mock_run.run_id = "run-abc123"

        with patch("search_service.get_search_store") as mock_get_store, \
             patch("asyncio.create_task") as mock_create_task:
            mock_store = MagicMock()
            mock_store.create_run.return_value = mock_run
            mock_get_store.return_value = mock_store

            run_id = start_search_run(pref)

            assert run_id == "run-abc123"
            mock_store.create_run.assert_called_once()
            mock_create_task.assert_called_once()


class TestExecuteSearchRunEmptySources:
    @pytest.mark.asyncio
    async def test_execute_search_run_with_no_sources_completes_zero(self):
        from search_service import execute_search_run
        from search_store import SearchPreferenceModel
        from datetime import datetime, timezone
        from unittest.mock import patch, AsyncMock

        pref = SearchPreferenceModel(
            preference_id="pref-empty-test",
            label="Empty Sources Test",
            archetype="experienced",
            keywords=["python"],
            locations=["Remote"],
            sources=[],  # No sources — should complete without fetching
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        run_id = "run-empty-test"

        with patch("search_service.get_search_store") as mock_get_store:
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store

            # Should complete without raising
            await execute_search_run(run_id, pref)

            # Store update_run_status should have been called
            mock_store.update_run_status.assert_any_call(run_id, "running")
            # After completion, should update counts and status
            calls = mock_store.update_run_status.call_args_list
            statuses = [call[0][1] for call in calls]
            assert "completed" in statuses
