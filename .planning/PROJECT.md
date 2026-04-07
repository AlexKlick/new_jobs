# PROJECT.md -- Career Workspace And Search Intelligence

## What This Is

A local-first career operating system that:

1. Tracks jobs, applications, and generated application materials.
2. Maintains editable source documents tailored to the user's profile archetype.
3. Discovers new jobs from saved preferences and organizes them into reusable lists.
4. Researches companies, review signals, and likely interview questions with provenance.
5. Builds long-lived career memory through a LightRAG-backed knowledge graph.

## Core Value

**Keep career knowledge structured, reusable, and compounding over time.**

## Current Milestone: v1.2 Career Workspace And Search Intelligence

**Goal:** Expand the existing application tracker into a full career workspace with source-document maintenance, ATS-first job discovery, saved job lists, company intelligence, and graph-backed memory.

### Planned v1.2 phases

- **Phase 16:** Source Workspace
- **Phase 17:** Job Search Discovery
- **Phase 18:** Saved Lists + Ranking
- **Phase 19:** Company Intelligence
- **Phase 20:** LightRAG Career Memory
- **Phase 21:** UI/UX Integration
- **Phase 22:** Verification + Audit

## Validated Requirements

### v1.0 MVP

- Job status checking with persisted cached results
- Markdown editing, backup, preview, and PDF regeneration
- Generation workflow with progress, accept/reject, and quality views

### v1.1 Assistant Integration

- Voice/text chat grounded in job documents
- TTS output and session persistence
- Skills editor with YAML validation and versioning
- Sandboxed agent workflow with rollback and circuit breaker
- Tech-debt cleanup for ports, structured response fields, and API URL consistency

### Validated in v1.2

- `SRC-*` Source workspace and archetype-aware profile editing (Phase 16)
- `LIST-*` Multi-list job curation with remove, reorder, and promote (Phase 18)
- `GRAPH-*` Event-driven graph memory with worker boundary, typed read models, and degraded mode (Phase 20)

## Active Requirements (v1.2)

- `SRCH-*` Saved search preferences and ATS-first job discovery
- `INTL-*` Company intelligence with review and interview-question evidence
- `UX-*` Unified navigation and high-signal UI states across all new flows
- `AUD-*` Verification, audit trail, and planning/reporting closure

## Context

### Existing stack

- Frontend: React 18 + Vite + TypeScript
- Backend: FastAPI + Python 3.12+
- Generation: `agents_sdk.resume_agent` pipeline
- Persistence: file-based artifacts plus SQLite session storage
- Facts: `facts/` markdown, YAML, and TTL material already exist

### Existing product surfaces

- `Tracker` for existing application inventory
- `Documents` for per-job application docs
- `Quality`, `Generate`, `Chat`, `Agent`, and `Skills`

### New v1.2 product surfaces

- `Documents > Sources` for source-record maintenance
- `Search` for saved job discovery runs
- `Lists` for curated per-search job sets
- `Research` for company intelligence snapshots
- `Graph` for long-term career memory and cross-company tracking

## Key Decisions

| Decision | Outcome |
|----------|---------|
| User profile system | Build a configurable engine with at least `new_grad` and `experienced` archetypes on day one |
| Search strategy | ATS-first discovery from public/company-friendly sources before broad web search |
| Saved results model | Every search execution creates a new `SearchRun` and a corresponding curated `JobList` |
| Research ingestion | Use browser-plus-snapshot acquisition with provenance-backed normalized claims |
| Graph strategy | LightRAG is foundational, but isolated behind a worker boundary due to local nested-session fragility documented in `agents_sdk` |
| Application promotion | Accepted discovered jobs flow back into the existing canonical ingestion/application pipeline rather than a parallel store |

## Tech Debt / Known Risks

- Existing `Documents` view is application-centric and needs a sub-navigation model.
- The repo already contains LightRAG integration, but local docs note fragility for nested-session execution.
- Search/discovery data and research artifacts will need a clearer storage boundary than the current manifest-only model.
- Public-review aggregation requires provenance and freshness controls to avoid stale or unverifiable claims.

## Out Of Scope

- Multi-user support and authentication
- Autonomous application submission
- Premium API dependencies as a hard requirement for MVP
- Replacing the existing application-generation pipeline
- Broad social/profile scraping without explicit user-provided or public input paths

---

*Last updated: 2026-04-07 for Phase 20 completion*
