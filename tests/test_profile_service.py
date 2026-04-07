"""Tests for structured profile storage and compilation."""

from __future__ import annotations

from pathlib import Path

import yaml


def _configure_profile_paths(monkeypatch, tmp_path):
    import research.profile_service as ps

    facts_dir = tmp_path / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ps, "FACTS_DIR", facts_dir)
    monkeypatch.setattr(ps, "PROFILE_DB", facts_dir / "profile_metadata.db")
    monkeypatch.setattr(ps, "FACTS_YAML_PATH", facts_dir / "career_facts.yaml")
    monkeypatch.setattr(ps, "BACKSTORY_PATH", facts_dir / "backstory_dump.md")
    ps._profile_service = None
    return ps


def test_bootstrap_from_existing_facts(monkeypatch, tmp_path):
    ps = _configure_profile_paths(monkeypatch, tmp_path)

    payload = {
        "version": 1,
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
        "person": {
            "name": "Alex Klick",
            "email": "alex@example.com",
            "location": "Denver, CO",
        },
        "facts": [
            {
                "id": "fact-role",
                "subject": "urn:career:person:alex-klick",
                "predicate": "career:heldRoleAt",
                "object_value": "Senior AI Engineer @ ExampleCo (Jan 2024 – Present)",
            },
            {
                "id": "fact-skill",
                "subject": "urn:career:person:alex-klick",
                "predicate": "career:hasSkill",
                "object_value": "Python",
            },
            {
                "id": "fact-achievement",
                "subject": "urn:career:person:alex-klick",
                "predicate": "career:achievement",
                "object_value": "Built a production RAG system for customer support.",
            },
        ],
    }
    ps.FACTS_YAML_PATH.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    ps.BACKSTORY_PATH.write_text(
        "# Backstory Content Dump\n\n## Elevator Pitch\n- Staff-level AI engineer focused on LLM systems.\n",
        encoding="utf-8",
    )

    service = ps.get_profile_service()
    profile = service.get_active_profile()

    assert profile.identity.full_name == "Alex Klick"
    assert profile.identity.email == "alex@example.com"
    assert profile.summary == "Staff-level AI engineer focused on LLM systems."
    assert len(profile.experiences) == 1
    assert profile.experiences[0].company == "ExampleCo"
    assert profile.experiences[0].current is True
    assert profile.experiences[0].bullets == ["Built a production RAG system for customer support."]
    assert [skill.name for skill in profile.skills] == ["Python"]


def test_save_profile_compiles_facts_and_backstory(monkeypatch, tmp_path):
    ps = _configure_profile_paths(monkeypatch, tmp_path)
    service = ps.get_profile_service()
    current = service.get_active_profile()

    profile, compile_result = service.save_active_profile({
        "profile_id": current.profile_id,
        "label": current.label,
        "identity": {
            "full_name": "Alex Klick",
            "email": "alex@example.com",
            "phone": "+1-555-100-2000",
            "location": "Denver, CO",
            "linkedin": "linkedin.com/in/alex-klick",
            "headline": "Principal AI Engineer",
        },
        "summary": "Builds high-signal ATS-ready resumes grounded in shipped LLM systems.",
        "experiences": [
            {
                "id": "exp-main",
                "company": "ExampleCo",
                "title": "Principal AI Engineer",
                "start_date": "Jan 2024",
                "end_date": "",
                "current": True,
                "bullets": [
                    "Led the rollout of an internal agent platform used across multiple teams.",
                ],
            },
        ],
        "skills": [
            {
                "id": "skill-python",
                "name": "Python",
                "level": "expert",
                "experience_ids": ["exp-main"],
                "notes": "Primary implementation language for APIs and pipelines.",
            },
            {
                "id": "skill-rag",
                "name": "RAG",
                "level": "advanced",
                "experience_ids": ["exp-main"],
                "notes": "",
            },
        ],
        "education": [
            {
                "id": "edu-1",
                "institution": "Eastern Michigan University",
                "degree": "B.A.",
                "field_of_study": "Economics",
                "graduation_date": "2019",
                "notes": "",
            },
        ],
        "certifications": [],
    })

    compiled_yaml = yaml.safe_load(ps.FACTS_YAML_PATH.read_text(encoding="utf-8"))
    compiled_backstory = ps.BACKSTORY_PATH.read_text(encoding="utf-8")

    assert profile.identity.headline == "Principal AI Engineer"
    assert compile_result.fact_count >= 5
    assert compiled_yaml["person"]["email"] == "alex@example.com"
    assert any(fact["predicate"] == "career:heldRoleAt" for fact in compiled_yaml["facts"])
    assert any(fact["object_value"] == "Python" for fact in compiled_yaml["facts"])
    assert "## ATS Keywords" in compiled_backstory
    assert "Python (expert): Used for Principal AI Engineer @ ExampleCo" in compiled_backstory


def test_skill_catalog_search_and_create(monkeypatch, tmp_path):
    ps = _configure_profile_paths(monkeypatch, tmp_path)
    service = ps.get_profile_service()

    matches = service.search_skill_catalog("py")
    assert any(item.name == "Python" for item in matches)

    created = service.create_skill_catalog_entry("MCP")
    matches = service.search_skill_catalog("mcp")

    assert created.name == "MCP"
    assert any(item.name == "MCP" for item in matches)
