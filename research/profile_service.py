"""
Profile service and compiler for resume-generation inputs.

Stores one active structured profile in SQLite, exposes a searchable skill
catalog, and compiles profile data into the generator's expected facts files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FACTS_DIR = PROJECT_ROOT / "facts"
PROFILE_DB = FACTS_DIR / "profile_metadata.db"
FACTS_YAML_PATH = FACTS_DIR / "career_facts.yaml"
BACKSTORY_PATH = FACTS_DIR / "backstory_dump.md"

SKILL_LEVELS = ("beginner", "intermediate", "advanced", "expert")

DEFAULT_SKILL_CATALOG = [
    "Python",
    "TypeScript",
    "JavaScript",
    "SQL",
    "FastAPI",
    "Pydantic",
    "React",
    "Node.js",
    "PostgreSQL",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "GCP",
    "LangChain",
    "LangGraph",
    "OpenAI API",
    "Prompt Engineering",
    "RAG",
    "Vector Databases",
    "LLM Evaluation",
    "Machine Learning",
    "NLP",
    "PyTorch",
    "Pandas",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    linkedin TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiences (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    experience_id TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    is_current INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, experience_id)
);

CREATE TABLE IF NOT EXISTS experience_bullets (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    experience_id TEXT NOT NULL,
    bullet_id TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, bullet_id)
);

CREATE TABLE IF NOT EXISTS skills (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    skill_entry_id TEXT NOT NULL,
    skill_catalog_id TEXT,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'catalog',
    level TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, skill_entry_id)
);

CREATE TABLE IF NOT EXISTS skill_experience_links (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    skill_entry_id TEXT NOT NULL,
    experience_id TEXT NOT NULL,
    PRIMARY KEY (profile_id, skill_entry_id, experience_id)
);

CREATE TABLE IF NOT EXISTS education_entries (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    education_id TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    degree TEXT NOT NULL DEFAULT '',
    field_of_study TEXT NOT NULL DEFAULT '',
    graduation_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, education_id)
);

CREATE TABLE IF NOT EXISTS certifications (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    certification_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    issuer TEXT NOT NULL DEFAULT '',
    issued_at TEXT NOT NULL DEFAULT '',
    credential_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, certification_id)
);

CREATE TABLE IF NOT EXISTS skill_catalog (
    skill_id TEXT PRIMARY KEY,
    normalized_name TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_catalog_name ON skill_catalog(normalized_name);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_skill_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _make_id(prefix: str, seed: str | None = None) -> str:
    if seed:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"{prefix}-{digest[:12]}"
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _fact_id(predicate: str, object_value: str) -> str:
    digest = hashlib.sha1(f"{predicate}|{object_value}".encode("utf-8")).hexdigest()
    return f"fact-{digest[:12]}"


def _get_db() -> sqlite3.Connection:
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROFILE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


class ProfileIdentityModel(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    headline: str = ""


class ExperienceEntryModel(BaseModel):
    id: str
    company: str = ""
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    current: bool = False
    bullets: list[str] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    @classmethod
    def _normalize_bullets(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class SkillEntryModel(BaseModel):
    id: str
    skill_id: str | None = None
    name: str
    source: str = "catalog"
    level: str = "intermediate"
    experience_ids: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SKILL_LEVELS:
            raise ValueError(f"Invalid skill level: {value}")
        return normalized


class EducationEntryModel(BaseModel):
    id: str
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    graduation_date: str = ""
    notes: str = ""


class CertificationEntryModel(BaseModel):
    id: str
    name: str = ""
    issuer: str = ""
    issued_at: str = ""
    credential_id: str = ""
    notes: str = ""


class ProfilePayloadModel(BaseModel):
    profile_id: str
    label: str = "Active Profile"
    is_active: bool = True
    identity: ProfileIdentityModel = Field(default_factory=ProfileIdentityModel)
    summary: str = ""
    experiences: list[ExperienceEntryModel] = Field(default_factory=list)
    skills: list[SkillEntryModel] = Field(default_factory=list)
    education: list[EducationEntryModel] = Field(default_factory=list)
    certifications: list[CertificationEntryModel] = Field(default_factory=list)
    created_at: str
    updated_at: str


class SkillCatalogEntryModel(BaseModel):
    skill_id: str
    name: str
    normalized_name: str
    source: str
    created_at: str
    updated_at: str


class ProfileCompileResultModel(BaseModel):
    facts_yaml_path: str
    backstory_dump_path: str
    fact_count: int
    compiled_at: str


def _parse_role_fact(value: str) -> dict[str, object]:
    match = re.match(r"^(?P<title>.+?)\s+@\s+(?P<company>.+?)\s+\((?P<dates>.+)\)$", value.strip())
    if not match:
        return {
            "company": "",
            "title": value.strip(),
            "start_date": "",
            "end_date": "",
            "current": False,
        }
    dates = match.group("dates").replace("—", "–")
    parts = [part.strip() for part in re.split(r"\s+[–-]\s+", dates, maxsplit=1)]
    start_date = parts[0] if parts else ""
    end_date = parts[1] if len(parts) > 1 else ""
    current = end_date.lower() == "present"
    return {
        "company": match.group("company").strip(),
        "title": match.group("title").strip(),
        "start_date": start_date,
        "end_date": "" if current else end_date,
        "current": current,
    }


def _load_existing_facts_payload() -> dict:
    if not FACTS_YAML_PATH.exists():
        return {}
    payload = yaml.safe_load(FACTS_YAML_PATH.read_text(encoding="utf-8"))
    return payload or {}


def _load_existing_backstory_summary() -> str:
    if not BACKSTORY_PATH.exists():
        return ""
    current_section = ""
    bullets: list[str] = []
    for raw_line in BACKSTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("##"):
            current_section = line.lstrip("#").strip().lower()
            continue
        if current_section == "elevator pitch" and line.startswith("-"):
            text = line.lstrip("-*+ ").strip()
            if text:
                bullets.append(text)
    return " ".join(bullets[:2]).strip()


class ProfileCompiler:
    """Compile a structured profile into facts YAML and backstory markdown."""

    def compile(self, profile: ProfilePayloadModel) -> ProfileCompileResultModel:
        compiled_at = _utc_now()
        facts_payload = self._build_facts_payload(profile, compiled_at)
        FACTS_DIR.mkdir(parents=True, exist_ok=True)
        FACTS_YAML_PATH.write_text(
            yaml.safe_dump(facts_payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        BACKSTORY_PATH.write_text(self._build_backstory(profile), encoding="utf-8")
        return ProfileCompileResultModel(
            facts_yaml_path=str(FACTS_YAML_PATH),
            backstory_dump_path=str(BACKSTORY_PATH),
            fact_count=len(facts_payload["facts"]),
            compiled_at=compiled_at,
        )

    def _build_facts_payload(self, profile: ProfilePayloadModel, compiled_at: str) -> dict:
        existing = _load_existing_facts_payload()
        person_id = "alex-klick"
        person_uri = "urn:career:person:alex-klick"
        identity = profile.identity
        facts: list[dict[str, object]] = []

        def append_fact(
            predicate: str,
            object_value: str,
            *,
            tags: list[str],
            excerpt: str | None = None,
            source_file: str = "backstory_dump.md",
        ) -> None:
            text = object_value.strip()
            if not text:
                return
            facts.append({
                "id": _fact_id(predicate, text),
                "subject": person_uri,
                "predicate": predicate,
                "object_value": text,
                "object_type": "literal",
                "confidence": 1.0,
                "evidence": [{
                    "source_file": source_file,
                    "excerpt": (excerpt or text)[:400],
                    "page": None,
                }],
                "tags": tags,
            })

        append_fact("career:hasName", identity.full_name, tags=["identity"], excerpt=identity.full_name)
        append_fact("career:hasEmail", identity.email, tags=["identity"], excerpt=identity.email)
        append_fact("career:hasPhone", identity.phone, tags=["identity"], excerpt=identity.phone)
        append_fact("career:hasLinkedIn", identity.linkedin, tags=["identity"], excerpt=identity.linkedin)
        append_fact("career:locatedIn", identity.location, tags=["identity"], excerpt=identity.location)
        append_fact("career:headline", identity.headline, tags=["identity", "positioning"], excerpt=identity.headline)
        append_fact("career:elevatorPitch", profile.summary, tags=["backstory", "positioning"], excerpt=profile.summary)

        for experience in profile.experiences:
            if not (experience.title or experience.company):
                continue
            date_text = experience.start_date or experience.end_date
            if experience.current:
                end_text = "Present"
            else:
                end_text = experience.end_date
            if experience.start_date or end_text:
                date_text = f"{experience.start_date} – {end_text}".strip(" –")
            role_text = " @ ".join(part for part in [experience.title.strip(), experience.company.strip()] if part)
            if date_text:
                role_text = f"{role_text} ({date_text})"
            append_fact("career:heldRoleAt", role_text, tags=["experience"], excerpt=role_text)
            for bullet in experience.bullets:
                append_fact(
                    "career:achievement",
                    bullet,
                    tags=["experience", "achievement"],
                    excerpt=f"{experience.title} @ {experience.company}: {bullet}",
                )

        for skill in profile.skills:
            used_for = self._used_for_text(profile, skill)
            excerpt_parts = [skill.name, skill.level]
            if used_for:
                excerpt_parts.append(used_for)
            if skill.notes.strip():
                excerpt_parts.append(skill.notes.strip())
            append_fact(
                "career:hasSkill",
                skill.name,
                tags=["skills"],
                excerpt=" | ".join(part for part in excerpt_parts if part),
            )

        for entry in profile.education:
            education_text = ", ".join(
                part for part in [
                    entry.institution.strip(),
                    entry.degree.strip(),
                    entry.field_of_study.strip(),
                    entry.graduation_date.strip(),
                ] if part
            )
            if not education_text and entry.notes.strip():
                education_text = entry.notes.strip()
            append_fact("career:education", education_text, tags=["education"], excerpt=education_text)

        for cert in profile.certifications:
            cert_text = ", ".join(
                part for part in [
                    cert.name.strip(),
                    cert.issuer.strip(),
                    cert.issued_at.strip(),
                ] if part
            )
            if cert.credential_id.strip():
                cert_text = f"{cert_text} ({cert.credential_id.strip()})" if cert_text else cert.credential_id.strip()
            if not cert_text and cert.notes.strip():
                cert_text = cert.notes.strip()
            append_fact("career:certification", cert_text, tags=["education", "certification"], excerpt=cert_text)

        return {
            "version": 1,
            "created_at": existing.get("created_at") or compiled_at,
            "updated_at": compiled_at,
            "person": {
                "id": person_id,
                "uri": person_uri,
                "name": identity.full_name or "Alex Klick",
                "location": identity.location or None,
                "phone": identity.phone or None,
                "email": identity.email or None,
                "linkedin": identity.linkedin or None,
            },
            "facts": facts,
        }

    def _build_backstory(self, profile: ProfilePayloadModel) -> str:
        identity = profile.identity
        lines = [
            "# Backstory Content Dump",
            "",
            f"Name: {identity.full_name}".rstrip(),
            f"Location: {identity.location}".rstrip(),
            f"Email: {identity.email}".rstrip(),
            f"Phone: {identity.phone}".rstrip(),
            f"LinkedIn: {identity.linkedin}".rstrip(),
            "",
            "## Elevator Pitch",
        ]
        if profile.summary.strip():
            lines.append(f"- {profile.summary.strip()}")
        elif identity.headline.strip():
            lines.append(f"- {identity.headline.strip()}")
        else:
            lines.append("-")

        lines.extend(["", "## Career Highlights"])
        highlight_lines: list[str] = []
        for experience in profile.experiences:
            role_prefix = " @ ".join(part for part in [experience.title.strip(), experience.company.strip()] if part)
            for bullet in experience.bullets:
                if role_prefix:
                    highlight_lines.append(f"- {role_prefix}: {bullet}")
                else:
                    highlight_lines.append(f"- {bullet}")
        lines.extend(highlight_lines or ["-"])

        leadership = [
            item for item in highlight_lines
            if any(token in item.lower() for token in ("lead", "mentor", "manage", "owner", "stakeholder"))
        ]
        lines.extend(["", "## Leadership"])
        lines.extend(leadership[:6] or ["-"])

        lines.extend(["", "## Target Roles"])
        lines.append(f"- {identity.headline.strip() or 'AI / software engineering roles'}")

        lines.extend(["", "## ATS Keywords"])
        keyword_lines = []
        for skill in profile.skills:
            used_for = self._used_for_text(profile, skill)
            skill_text = f"{skill.name} ({skill.level})"
            if used_for:
                skill_text = f"{skill_text}: {used_for}"
            elif skill.notes.strip():
                skill_text = f"{skill_text}: {skill.notes.strip()}"
            keyword_lines.append(f"- {skill_text}")
        lines.extend(keyword_lines or ["-"])
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _used_for_text(profile: ProfilePayloadModel, skill: SkillEntryModel) -> str:
        experiences_by_id = {experience.id: experience for experience in profile.experiences}
        labels: list[str] = []
        for experience_id in skill.experience_ids:
            experience = experiences_by_id.get(experience_id)
            if not experience:
                continue
            label = " @ ".join(part for part in [experience.title.strip(), experience.company.strip()] if part)
            if label:
                labels.append(label)
        if labels:
            return f"Used for {', '.join(labels[:4])}"
        return ""


class ProfileService:
    """One-active-profile service plus compile-to-facts behavior."""

    def __init__(self) -> None:
        with _get_db() as conn:
            self._seed_catalog(conn)

    def get_active_profile(self) -> ProfilePayloadModel:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return self._bootstrap_profile(conn)
            return self._load_profile(conn, row["profile_id"])

    def save_active_profile(self, payload: dict) -> tuple[ProfilePayloadModel, ProfileCompileResultModel]:
        with _get_db() as conn:
            current = self.get_active_profile()
            merged = {
                "profile_id": current.profile_id,
                "label": payload.get("label") or current.label,
                "is_active": True,
                "identity": payload.get("identity") or current.identity.model_dump(),
                "summary": payload.get("summary", current.summary),
                "experiences": payload.get("experiences", [item.model_dump() for item in current.experiences]),
                "skills": payload.get("skills", [item.model_dump() for item in current.skills]),
                "education": payload.get("education", [item.model_dump() for item in current.education]),
                "certifications": payload.get("certifications", [item.model_dump() for item in current.certifications]),
                "created_at": current.created_at,
                "updated_at": _utc_now(),
            }
            profile = ProfilePayloadModel.model_validate(merged)
            experience_ids = {item.id for item in profile.experiences}
            for skill in profile.skills:
                skill.experience_ids = [item for item in skill.experience_ids if item in experience_ids]
                catalog_entry = self._ensure_catalog_entry(conn, skill.name, preferred_source=skill.source)
                skill.skill_id = catalog_entry.skill_id
                skill.name = catalog_entry.name
                if skill.source == "catalog":
                    skill.source = catalog_entry.source

            self._persist_profile(conn, profile)
            compiler = ProfileCompiler()
            compile_result = compiler.compile(profile)
            return profile, compile_result

    def compile_active_profile(self) -> ProfileCompileResultModel:
        profile = self.get_active_profile()
        compiler = ProfileCompiler()
        return compiler.compile(profile)

    def search_skill_catalog(self, query: str = "", limit: int = 20) -> list[SkillCatalogEntryModel]:
        normalized_query = _normalize_skill_name(query)
        like = f"%{normalized_query}%"
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_catalog WHERE normalized_name LIKE ? ORDER BY normalized_name ASC LIMIT ?",
                (like or "%", limit),
            ).fetchall()
        return [self._catalog_row_to_model(row) for row in rows]

    def create_skill_catalog_entry(self, name: str) -> SkillCatalogEntryModel:
        with _get_db() as conn:
            entry = self._ensure_catalog_entry(conn, name, preferred_source="custom")
            return entry

    def build_profile_context(self) -> str:
        profile = self.get_active_profile()
        identity = profile.identity
        lines = ["ACTIVE PROFILE"]
        if identity.headline.strip():
            lines.append(f"Headline: {identity.headline.strip()}")
        if profile.summary.strip():
            lines.append(f"Summary: {profile.summary.strip()}")
        if profile.experiences:
            lines.append("Recent Experience:")
            for experience in profile.experiences[:3]:
                role = " @ ".join(part for part in [experience.title.strip(), experience.company.strip()] if part)
                if role:
                    lines.append(f"- {role}")
                for bullet in experience.bullets[:2]:
                    lines.append(f"  - {bullet}")
        if profile.skills:
            lines.append("Structured Skills:")
            for skill in profile.skills[:12]:
                used_for = ProfileCompiler._used_for_text(profile, skill)
                lines.append(f"- {skill.name} ({skill.level}){f'; {used_for}' if used_for else ''}")
        return "\n".join(lines)

    def _bootstrap_profile(self, conn: sqlite3.Connection) -> ProfilePayloadModel:
        payload = _load_existing_facts_payload()
        person = payload.get("person") or {}
        facts = payload.get("facts") or []
        profile_id = _make_id("profile", "active-profile")
        created_at = payload.get("created_at") or _utc_now()
        updated_at = payload.get("updated_at") or created_at

        experiences: list[ExperienceEntryModel] = []
        achievements: list[str] = []
        skills: list[SkillEntryModel] = []
        education: list[EducationEntryModel] = []
        certifications: list[CertificationEntryModel] = []
        summary = _load_existing_backstory_summary()

        for fact in facts:
            predicate = str(fact.get("predicate") or "")
            object_value = str(fact.get("object_value") or "").strip()
            if not object_value:
                continue
            if predicate == "career:heldRoleAt":
                parsed = _parse_role_fact(object_value)
                experiences.append(ExperienceEntryModel(
                    id=_make_id("exp", object_value),
                    company=str(parsed["company"]),
                    title=str(parsed["title"]),
                    start_date=str(parsed["start_date"]),
                    end_date=str(parsed["end_date"]),
                    current=bool(parsed["current"]),
                    bullets=[],
                ))
            elif predicate == "career:achievement":
                achievements.append(object_value)
            elif predicate == "career:hasSkill":
                normalized = _normalize_skill_name(object_value)
                if not normalized or any(_normalize_skill_name(skill.name) == normalized for skill in skills):
                    continue
                catalog_entry = self._ensure_catalog_entry(conn, object_value, preferred_source="import")
                skills.append(SkillEntryModel(
                    id=_make_id("skill", object_value),
                    skill_id=catalog_entry.skill_id,
                    name=catalog_entry.name,
                    source=catalog_entry.source,
                    level="advanced",
                    experience_ids=[],
                    notes="",
                ))
            elif predicate == "career:education":
                education.append(EducationEntryModel(
                    id=_make_id("edu", object_value),
                    institution=object_value,
                    degree="",
                    field_of_study="",
                    graduation_date="",
                    notes="",
                ))
            elif predicate == "career:certification":
                certifications.append(CertificationEntryModel(
                    id=_make_id("cert", object_value),
                    name=object_value,
                    issuer="",
                    issued_at="",
                    credential_id="",
                    notes="",
                ))
            elif predicate in {"career:elevatorPitch", "career:summary"} and not summary:
                summary = object_value

        if experiences and achievements:
            experiences[0].bullets = achievements[:8]

        profile = ProfilePayloadModel(
            profile_id=profile_id,
            label="Active Profile",
            is_active=True,
            identity=ProfileIdentityModel(
                full_name=str(person.get("name") or ""),
                email=str(person.get("email") or ""),
                phone=str(person.get("phone") or ""),
                location=str(person.get("location") or ""),
                linkedin=str(person.get("linkedin") or ""),
                headline="",
            ),
            summary=summary,
            experiences=experiences,
            skills=skills,
            education=education,
            certifications=certifications,
            created_at=created_at,
            updated_at=updated_at,
        )
        self._persist_profile(conn, profile)
        return profile

    def _persist_profile(self, conn: sqlite3.Connection, profile: ProfilePayloadModel) -> None:
        identity = profile.identity
        conn.execute("UPDATE profiles SET is_active = 0")
        conn.execute(
            """
            INSERT INTO profiles (
                profile_id, label, is_active, full_name, email, phone, location,
                linkedin, headline, summary, created_at, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                label=excluded.label,
                is_active=1,
                full_name=excluded.full_name,
                email=excluded.email,
                phone=excluded.phone,
                location=excluded.location,
                linkedin=excluded.linkedin,
                headline=excluded.headline,
                summary=excluded.summary,
                updated_at=excluded.updated_at
            """,
            (
                profile.profile_id,
                profile.label,
                identity.full_name,
                identity.email,
                identity.phone,
                identity.location,
                identity.linkedin,
                identity.headline,
                profile.summary,
                profile.created_at,
                profile.updated_at,
            ),
        )
        conn.execute("DELETE FROM experiences WHERE profile_id = ?", (profile.profile_id,))
        conn.execute("DELETE FROM experience_bullets WHERE profile_id = ?", (profile.profile_id,))
        conn.execute("DELETE FROM skills WHERE profile_id = ?", (profile.profile_id,))
        conn.execute("DELETE FROM skill_experience_links WHERE profile_id = ?", (profile.profile_id,))
        conn.execute("DELETE FROM education_entries WHERE profile_id = ?", (profile.profile_id,))
        conn.execute("DELETE FROM certifications WHERE profile_id = ?", (profile.profile_id,))

        for index, experience in enumerate(profile.experiences):
            conn.execute(
                """
                INSERT INTO experiences (
                    profile_id, experience_id, company, title, start_date, end_date,
                    is_current, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    experience.id,
                    experience.company,
                    experience.title,
                    experience.start_date,
                    experience.end_date,
                    1 if experience.current else 0,
                    index,
                ),
            )
            for bullet_index, bullet in enumerate(experience.bullets):
                conn.execute(
                    """
                    INSERT INTO experience_bullets (
                        profile_id, experience_id, bullet_id, text, sort_order
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        profile.profile_id,
                        experience.id,
                        _make_id("bullet", f"{experience.id}:{bullet_index}:{bullet}"),
                        bullet,
                        bullet_index,
                    ),
                )

        for index, skill in enumerate(profile.skills):
            conn.execute(
                """
                INSERT INTO skills (
                    profile_id, skill_entry_id, skill_catalog_id, name, source,
                    level, notes, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    skill.id,
                    skill.skill_id,
                    skill.name,
                    skill.source,
                    skill.level,
                    skill.notes,
                    index,
                ),
            )
            for experience_id in skill.experience_ids:
                conn.execute(
                    """
                    INSERT INTO skill_experience_links (profile_id, skill_entry_id, experience_id)
                    VALUES (?, ?, ?)
                    """,
                    (profile.profile_id, skill.id, experience_id),
                )

        for index, education in enumerate(profile.education):
            conn.execute(
                """
                INSERT INTO education_entries (
                    profile_id, education_id, institution, degree, field_of_study,
                    graduation_date, notes, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    education.id,
                    education.institution,
                    education.degree,
                    education.field_of_study,
                    education.graduation_date,
                    education.notes,
                    index,
                ),
            )

        for index, certification in enumerate(profile.certifications):
            conn.execute(
                """
                INSERT INTO certifications (
                    profile_id, certification_id, name, issuer, issued_at,
                    credential_id, notes, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    certification.id,
                    certification.name,
                    certification.issuer,
                    certification.issued_at,
                    certification.credential_id,
                    certification.notes,
                    index,
                ),
            )

    def _load_profile(self, conn: sqlite3.Connection, profile_id: str) -> ProfilePayloadModel:
        profile_row = conn.execute("SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
        if profile_row is None:
            raise ValueError(f"Profile not found: {profile_id}")

        experiences = []
        experience_rows = conn.execute(
            "SELECT * FROM experiences WHERE profile_id = ? ORDER BY sort_order ASC",
            (profile_id,),
        ).fetchall()
        for experience_row in experience_rows:
            bullet_rows = conn.execute(
                """
                SELECT text FROM experience_bullets
                WHERE profile_id = ? AND experience_id = ?
                ORDER BY sort_order ASC
                """,
                (profile_id, experience_row["experience_id"]),
            ).fetchall()
            experiences.append(ExperienceEntryModel(
                id=experience_row["experience_id"],
                company=experience_row["company"],
                title=experience_row["title"],
                start_date=experience_row["start_date"],
                end_date=experience_row["end_date"],
                current=bool(experience_row["is_current"]),
                bullets=[row["text"] for row in bullet_rows],
            ))

        skills = []
        skill_rows = conn.execute(
            "SELECT * FROM skills WHERE profile_id = ? ORDER BY sort_order ASC",
            (profile_id,),
        ).fetchall()
        for skill_row in skill_rows:
            link_rows = conn.execute(
                """
                SELECT experience_id FROM skill_experience_links
                WHERE profile_id = ? AND skill_entry_id = ?
                ORDER BY experience_id ASC
                """,
                (profile_id, skill_row["skill_entry_id"]),
            ).fetchall()
            skills.append(SkillEntryModel(
                id=skill_row["skill_entry_id"],
                skill_id=skill_row["skill_catalog_id"],
                name=skill_row["name"],
                source=skill_row["source"],
                level=skill_row["level"],
                experience_ids=[row["experience_id"] for row in link_rows],
                notes=skill_row["notes"],
            ))

        education_rows = conn.execute(
            "SELECT * FROM education_entries WHERE profile_id = ? ORDER BY sort_order ASC",
            (profile_id,),
        ).fetchall()
        education = [
            EducationEntryModel(
                id=row["education_id"],
                institution=row["institution"],
                degree=row["degree"],
                field_of_study=row["field_of_study"],
                graduation_date=row["graduation_date"],
                notes=row["notes"],
            )
            for row in education_rows
        ]

        certification_rows = conn.execute(
            "SELECT * FROM certifications WHERE profile_id = ? ORDER BY sort_order ASC",
            (profile_id,),
        ).fetchall()
        certifications = [
            CertificationEntryModel(
                id=row["certification_id"],
                name=row["name"],
                issuer=row["issuer"],
                issued_at=row["issued_at"],
                credential_id=row["credential_id"],
                notes=row["notes"],
            )
            for row in certification_rows
        ]

        return ProfilePayloadModel(
            profile_id=profile_row["profile_id"],
            label=profile_row["label"],
            is_active=bool(profile_row["is_active"]),
            identity=ProfileIdentityModel(
                full_name=profile_row["full_name"],
                email=profile_row["email"],
                phone=profile_row["phone"],
                location=profile_row["location"],
                linkedin=profile_row["linkedin"],
                headline=profile_row["headline"],
            ),
            summary=profile_row["summary"],
            experiences=experiences,
            skills=skills,
            education=education,
            certifications=certifications,
            created_at=profile_row["created_at"],
            updated_at=profile_row["updated_at"],
        )

    def _seed_catalog(self, conn: sqlite3.Connection) -> None:
        for name in DEFAULT_SKILL_CATALOG:
            self._ensure_catalog_entry(conn, name, preferred_source="seed")

    def _ensure_catalog_entry(
        self,
        conn: sqlite3.Connection,
        name: str,
        *,
        preferred_source: str,
    ) -> SkillCatalogEntryModel:
        cleaned = " ".join(name.split()).strip()
        if not cleaned:
            raise ValueError("Skill name cannot be empty")
        normalized = _normalize_skill_name(cleaned)
        now = _utc_now()
        row = conn.execute(
            "SELECT * FROM skill_catalog WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if row:
            return self._catalog_row_to_model(row)

        skill_id = _make_id("catalog-skill", normalized)
        conn.execute(
            """
            INSERT INTO skill_catalog (skill_id, normalized_name, name, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (skill_id, normalized, cleaned, preferred_source, now, now),
        )
        return SkillCatalogEntryModel(
            skill_id=skill_id,
            name=cleaned,
            normalized_name=normalized,
            source=preferred_source,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _catalog_row_to_model(row: sqlite3.Row) -> SkillCatalogEntryModel:
        return SkillCatalogEntryModel(
            skill_id=row["skill_id"],
            name=row["name"],
            normalized_name=row["normalized_name"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


_profile_service: Optional[ProfileService] = None


def get_profile_service() -> ProfileService:
    global _profile_service
    if _profile_service is None:
        _profile_service = ProfileService()
    return _profile_service
