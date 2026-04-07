"""API tests for the active profile workflow."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_profile_storage(monkeypatch, tmp_path):
    import research.profile_service as ps

    dummy_sdk = types.ModuleType("claude_agent_sdk")
    dummy_sdk.query = lambda *args, **kwargs: None
    dummy_sdk.ClaudeAgentOptions = object
    dummy_sdk.ClaudeSDKClient = object
    dummy_sdk.AgentDefinition = object
    dummy_sdk.HookMatcher = object
    dummy_sdk.ThinkingConfig = object
    dummy_sdk.SdkBeta = object
    dummy_sdk_types = types.ModuleType("claude_agent_sdk.types")
    dummy_sdk_types.McpServerConfig = object
    sys.modules["claude_agent_sdk"] = dummy_sdk
    sys.modules["claude_agent_sdk.types"] = dummy_sdk_types

    dummy_jobs = types.ModuleType("jobs")
    dummy_job_status_checker = types.ModuleType("jobs.job_status_checker")
    dummy_jobs.job_status_checker = dummy_job_status_checker
    sys.modules["jobs"] = dummy_jobs
    sys.modules["jobs.job_status_checker"] = dummy_job_status_checker

    dummy_pdf = types.ModuleType("pdf")
    dummy_pdf_generator = types.ModuleType("pdf.pdf_generator")
    dummy_pdf.pdf_generator = dummy_pdf_generator
    sys.modules["pdf"] = dummy_pdf
    sys.modules["pdf.pdf_generator"] = dummy_pdf_generator

    facts_dir = tmp_path / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ps, "FACTS_DIR", facts_dir)
    monkeypatch.setattr(ps, "PROFILE_DB", facts_dir / "profile_metadata.db")
    monkeypatch.setattr(ps, "FACTS_YAML_PATH", facts_dir / "career_facts.yaml")
    monkeypatch.setattr(ps, "BACKSTORY_PATH", facts_dir / "backstory_dump.md")
    ps._profile_service = None
    yield
    ps._profile_service = None


@pytest.fixture()
def client():
    from api_server import app

    return TestClient(app)


def test_get_profile_bootstraps_active_profile(client):
    response = client.get("/api/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["label"] == "Active Profile"
    assert data["skills"] == []


def test_put_profile_saves_and_compiles(client):
    current = client.get("/api/profile").json()

    response = client.put(
        "/api/profile",
        json={
            "profile_id": current["profile_id"],
            "label": current["label"],
            "identity": {
                "full_name": "Alex Klick",
                "email": "alex@example.com",
                "phone": "",
                "location": "Denver, CO",
                "linkedin": "linkedin.com/in/alex-klick",
                "headline": "Senior AI Engineer",
            },
            "summary": "Focuses on agentic AI and production-quality LLM systems.",
            "experiences": [
                {
                    "id": "exp-1",
                    "company": "ExampleCo",
                    "title": "Senior AI Engineer",
                    "start_date": "Jan 2024",
                    "end_date": "",
                    "current": True,
                    "bullets": ["Built an internal platform for LLM workflows."],
                },
            ],
            "skills": [
                {
                    "id": "skill-1",
                    "skill_id": None,
                    "name": "Python",
                    "source": "catalog",
                    "level": "expert",
                    "experience_ids": ["exp-1"],
                    "notes": "Primary language for APIs and services.",
                },
            ],
            "education": [],
            "certifications": [],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["profile"]["identity"]["headline"] == "Senior AI Engineer"
    assert data["compile_result"]["fact_count"] >= 4


def test_skill_catalog_endpoints(client):
    search_response = client.get("/api/profile/skills/catalog?q=py")
    assert search_response.status_code == 200
    assert any(item["name"] == "Python" for item in search_response.json())

    create_response = client.post("/api/profile/skills/catalog", json={"name": "MCP"})
    assert create_response.status_code == 200
    assert create_response.json()["name"] == "MCP"


def test_generation_compiles_profile_before_orchestrator(client, monkeypatch, tmp_path):
    import api_server

    bundle_dir = tmp_path / "applications" / "all_jobs" / "01_example__role"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    compiled = {"called": False}

    class StubProfileService:
        def compile_active_profile(self):
            compiled["called"] = True

    class StubProgress:
        def to_dict(self):
            return {
                "job_index": 1,
                "target": "both",
                "status": "starting",
                "provider": "minimax",
                "started_at": None,
                "completed_at": None,
                "progress_pct": 0.0,
                "current_step": "Preparing generation request",
                "estimated_remaining_s": None,
                "error": None,
                "output_dir": None,
                "rubric_scores": None,
            }

    class StubOrchestrator:
        async def start_generation(self, **kwargs):
            return StubProgress()

    monkeypatch.setattr(api_server, "get_profile_service", lambda: StubProfileService())
    monkeypatch.setattr(api_server, "get_bundle_dir", lambda index: bundle_dir if index == 1 else None)
    monkeypatch.setattr(api_server, "get_orchestrator", lambda: StubOrchestrator())

    response = client.post("/api/jobs/1/generate", json={"target": "both", "provider": "minimax"})

    assert response.status_code == 200
    assert compiled["called"] is True
