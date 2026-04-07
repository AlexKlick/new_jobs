"""PostgreSQL schema definition for the denjobs database.

Covers all tables ported from the four SQLite stores (source, search,
research, profile) plus the two tables replacing JSON file stores
(`generation_state`, `job_posting_status`).

Usage::

    pool = await create_pool()
    await ensure_schema(pool)
"""

import asyncpg

# ── Source tables (from research/source_service.py) ─────────────────────────────

_SOURCE_DDL = """
CREATE TABLE IF NOT EXISTS source_records (
    record_id        TEXT PRIMARY KEY,
    archetype        TEXT NOT NULL,
    label            TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    revision_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_fields (
    record_id        TEXT NOT NULL REFERENCES source_records(record_id) ON DELETE CASCADE,
    field_id         TEXT NOT NULL,
    label            TEXT NOT NULL,
    value            TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL,
    field_order      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (record_id, field_id)
);

CREATE TABLE IF NOT EXISTS source_revisions (
    revision_id      TEXT PRIMARY KEY,
    record_id        TEXT NOT NULL REFERENCES source_records(record_id) ON DELETE CASCADE,
    created_at       TEXT NOT NULL,
    provenance       TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    field_count      INTEGER NOT NULL DEFAULT 0,
    snapshot         JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

_SOURCE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_source_fields_record     ON source_fields(record_id);
CREATE INDEX IF NOT EXISTS idx_source_revisions_record  ON source_revisions(record_id);
CREATE INDEX IF NOT EXISTS idx_source_revisions_created ON source_revisions(created_at);
"""

# ── Search tables (from search/search_store.py) ──────────────────────────────────

_SEARCH_DDL = """
CREATE TABLE IF NOT EXISTS search_preferences (
    preference_id       TEXT PRIMARY KEY,
    label               TEXT NOT NULL,
    archetype           TEXT NOT NULL,
    keywords            JSONB NOT NULL DEFAULT '[]'::jsonb,
    locations           JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources             JSONB NOT NULL DEFAULT '[]'::jsonb,
    experience_level    TEXT,
    remote_policy       TEXT,
    salary_min          INTEGER,
    discovery_strategy  TEXT NOT NULL DEFAULT 'search_and_career_pages',
    companies           JSONB NOT NULL DEFAULT '[]'::jsonb,
    max_results_per_source INTEGER NOT NULL DEFAULT 50,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_run_at         TEXT
);

CREATE TABLE IF NOT EXISTS search_runs (
    run_id              TEXT PRIMARY KEY,
    preference_id       TEXT REFERENCES search_preferences(preference_id),
    preference_label    TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    total_candidates    INTEGER NOT NULL DEFAULT 0,
    new_candidates      INTEGER NOT NULL DEFAULT 0,
    duplicate_count     INTEGER NOT NULL DEFAULT 0,
    warnings            JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message       TEXT
);

CREATE TABLE IF NOT EXISTS job_candidates (
    candidate_id                TEXT PRIMARY KEY,
    run_id                      TEXT NOT NULL REFERENCES search_runs(run_id),
    source                      TEXT NOT NULL,
    source_url                  TEXT NOT NULL,
    company                     TEXT NOT NULL,
    role                        TEXT NOT NULL,
    location                    TEXT,
    salary                      TEXT,
    remote                      TEXT,
    posted_date                 TEXT,
    apply_url                   TEXT,
    discovery_url               TEXT,
    extraction_method           TEXT NOT NULL DEFAULT 'ats_api',
    source_confidence           TEXT NOT NULL DEFAULT 'high',
    search_rank                 INTEGER NOT NULL DEFAULT 0,
    identity_key                TEXT NOT NULL,
    is_duplicate                BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_of_candidate_id   TEXT,
    ingested                    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_lists (
    list_id     TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES search_runs(run_id),
    label       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_list_items (
    item_id         TEXT PRIMARY KEY,
    list_id         TEXT NOT NULL REFERENCES job_lists(list_id),
    candidate_id    TEXT NOT NULL REFERENCES job_candidates(candidate_id),
    position        INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    priority        TEXT,
    status          TEXT,
    promoted        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TEXT NOT NULL,
    UNIQUE (list_id, candidate_id)
);
"""

_SEARCH_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_candidates_run      ON job_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_identity  ON job_candidates(identity_key);
CREATE INDEX IF NOT EXISTS idx_candidates_rank      ON job_candidates(run_id, search_rank);
CREATE INDEX IF NOT EXISTS idx_runs_status          ON search_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started         ON search_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_list_items_list      ON job_list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_list_items_position  ON job_list_items(list_id, position);
CREATE INDEX IF NOT EXISTS idx_prefs_keywords       ON search_preferences USING gin (keywords);
CREATE INDEX IF NOT EXISTS idx_prefs_companies      ON search_preferences USING gin (companies);
"""

# ── Research tables (from research/research_store.py) ────────────────────────────

_RESEARCH_DDL = """
CREATE TABLE IF NOT EXISTS research_companies (
    company_key    TEXT PRIMARY KEY,
    company_name   TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    company_key    TEXT NOT NULL REFERENCES research_companies(company_key),
    collected_at   TEXT NOT NULL,
    source_count   INTEGER NOT NULL DEFAULT 0,
    claim_count    INTEGER NOT NULL DEFAULT 0,
    question_count INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',
    error_message  TEXT,
    artifact_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_claims (
    claim_id           TEXT PRIMARY KEY,
    snapshot_id        TEXT NOT NULL REFERENCES research_snapshots(snapshot_id),
    company_key        TEXT NOT NULL REFERENCES research_companies(company_key),
    claim_text         TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    collected_at       TEXT NOT NULL,
    confidence         TEXT NOT NULL DEFAULT 'medium',
    themes             JSONB NOT NULL DEFAULT '[]'::jsonb,
    sentiment_score    DOUBLE PRECISION,
    role_applicability JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_interview_questions (
    question_id        TEXT PRIMARY KEY,
    snapshot_id        TEXT NOT NULL REFERENCES research_snapshots(snapshot_id),
    company_key        TEXT NOT NULL REFERENCES research_companies(company_key),
    question_text      TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    collected_at       TEXT NOT NULL,
    role_applicability JSONB NOT NULL DEFAULT '[]'::jsonb,
    themes             JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_refreshes (
    refresh_id        TEXT PRIMARY KEY,
    company_key       TEXT NOT NULL REFERENCES research_companies(company_key),
    status            TEXT NOT NULL DEFAULT 'pending',
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    current_source    TEXT,
    sources_total     INTEGER NOT NULL DEFAULT 0,
    sources_completed INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT
);
"""

_RESEARCH_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_snapshots_company   ON research_snapshots(company_key);
CREATE INDEX IF NOT EXISTS idx_snapshots_status    ON research_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_claims_snapshot     ON research_claims(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_claims_company      ON research_claims(company_key);
CREATE INDEX IF NOT EXISTS idx_claims_themes       ON research_claims USING gin (themes);
CREATE INDEX IF NOT EXISTS idx_questions_snapshot  ON research_interview_questions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_questions_company   ON research_interview_questions(company_key);
CREATE INDEX IF NOT EXISTS idx_refreshes_company   ON research_refreshes(company_key);
CREATE INDEX IF NOT EXISTS idx_refreshes_status    ON research_refreshes(status);
"""

# ── Profile tables (from research/profile_service.py) ────────────────────────────

_PROFILE_DDL = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_id  TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    full_name   TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    linkedin    TEXT NOT NULL DEFAULT '',
    headline    TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiences (
    profile_id     TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    experience_id  TEXT NOT NULL,
    company        TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    start_date     TEXT NOT NULL DEFAULT '',
    end_date       TEXT NOT NULL DEFAULT '',
    is_current     BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, experience_id)
);

CREATE TABLE IF NOT EXISTS experience_bullets (
    profile_id     TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    experience_id  TEXT NOT NULL,
    bullet_id      TEXT NOT NULL,
    text           TEXT NOT NULL DEFAULT '',
    sort_order     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, bullet_id)
);

CREATE TABLE IF NOT EXISTS skills (
    profile_id       TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    skill_entry_id   TEXT NOT NULL,
    skill_catalog_id TEXT,
    name             TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'catalog',
    level            TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    sort_order       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, skill_entry_id)
);

CREATE TABLE IF NOT EXISTS skill_experience_links (
    profile_id     TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    skill_entry_id TEXT NOT NULL,
    experience_id  TEXT NOT NULL,
    PRIMARY KEY (profile_id, skill_entry_id, experience_id)
);

CREATE TABLE IF NOT EXISTS education_entries (
    profile_id      TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    education_id    TEXT NOT NULL,
    institution     TEXT NOT NULL DEFAULT '',
    degree          TEXT NOT NULL DEFAULT '',
    field_of_study  TEXT NOT NULL DEFAULT '',
    graduation_date TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, education_id)
);

CREATE TABLE IF NOT EXISTS certifications (
    profile_id       TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    certification_id TEXT NOT NULL,
    name             TEXT NOT NULL DEFAULT '',
    issuer           TEXT NOT NULL DEFAULT '',
    issued_at        TEXT NOT NULL DEFAULT '',
    credential_id    TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    sort_order       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, certification_id)
);

CREATE TABLE IF NOT EXISTS skill_catalog (
    skill_id         TEXT PRIMARY KEY,
    normalized_name  TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'seed',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
"""

_PROFILE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_skill_catalog_name ON skill_catalog(normalized_name);
"""

# ── New tables (replacing JSON file stores) ──────────────────────────────────────

_NEW_DDL = """
CREATE TABLE IF NOT EXISTS generation_state (
    job_index            INTEGER PRIMARY KEY,
    target               TEXT NOT NULL DEFAULT 'both',
    status               TEXT NOT NULL DEFAULT 'idle',
    provider             TEXT NOT NULL DEFAULT '',
    started_at           TEXT,
    completed_at         TEXT,
    progress_pct         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    current_step         TEXT NOT NULL DEFAULT '',
    estimated_remaining_s DOUBLE PRECISION,
    error                TEXT,
    output_dir           TEXT,
    rubric_scores        JSONB,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_posting_status (
    index              INTEGER PRIMARY KEY,
    url                TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_checked       TEXT,
    error              TEXT,
    source             TEXT NOT NULL DEFAULT 'generic',
    http_status_code   INTEGER,
    response_time_ms   INTEGER,
    updated_at         TEXT NOT NULL
);
"""

_NEW_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_gen_state_status    ON generation_state(status);
CREATE INDEX IF NOT EXISTS idx_posting_status_val  ON job_posting_status(status);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Create all tables and indexes if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute(_SOURCE_DDL)
        await conn.execute(_SOURCE_INDEXES)
        await conn.execute(_SEARCH_DDL)
        await conn.execute(_SEARCH_INDEXES)
        await conn.execute(_RESEARCH_DDL)
        await conn.execute(_RESEARCH_INDEXES)
        await conn.execute(_PROFILE_DDL)
        await conn.execute(_PROFILE_INDEXES)
        await conn.execute(_NEW_DDL)
        await conn.execute(_NEW_INDEXES)
