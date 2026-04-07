# Roadmap: Career Workspace And Search Intelligence

## Milestones

- [x] **v1.0 MVP** -- Core tracker, document editing, PDF regeneration, generation workflow
- [x] **v1.1 Assistant Integration** -- Voice/text chat, TTS, skills editor, agent, persistence
- [ ] **v1.2 Career Workspace And Search Intelligence** -- In progress, reconciled on 2026-04-04

## Current Milestone: v1.2

**Goal:** Turn the existing application tracker into a reusable career workspace with source maintenance, ATS-first job discovery, curated lists, company intelligence, and graph-backed memory.

## Phase Status

- [x] **Phase 16: Source Workspace** -- complete and trusted baseline
- [x] **Phase 17: Job Search Discovery** -- complete, re-closed with 2026-04-04 evidence
- [x] **Phase 18: Saved Lists + Ranking** -- complete, re-closed with 2026-04-04 evidence
- [x] **Phase 19: Company Intelligence** -- planned (completed 2026-04-06)
- [x] **Phase 20: LightRAG Career Memory** -- planned (completed 2026-04-07)
- [ ] **Phase 21: UI/UX Integration** -- planned
- [ ] **Phase 22: Verification + Audit** -- planned

## Execution Rules

1. Root status documents must reflect repo truth, not historical summary files.
2. Only supported connectors may be selectable in shipped UI flows.
3. New v1.2 UI work must use shared API-base handling and keep `ui` buildable.
4. Every phase closes with explicit validation commands and manual verification evidence.

## Search/List Hardening Gate

Cleared on 2026-04-04.

- Frontend TypeScript build failures were cleared and `npm run build` now passes.
- Search and Sources use shared `API_BASE` handling instead of hardcoded per-page localhost URLs.
- Unsupported `generic` search is clearly deferred, not offered as a working connector.
- Lists now return the candidate fields the UI renders, and promote routes bridge through canonical ingest before flags are set.

## Phase Details

### Phase 17: Job Search Discovery

**Goal:** Add ATS-first saved search preferences and persisted search runs.

**Requirements:** `SRCH-01` through `SRCH-04`

**Verified Closure**

1. User can save search preferences and run them on demand.
2. Only supported connectors are selectable in the UI; `generic` is clearly deferred.
3. Each run persists as an immutable `SearchRun` snapshot.
4. Duplicate jobs are recognized across runs and sources.
5. Shared frontend API configuration is used instead of page-local localhost assumptions.

### Phase 18: Saved Lists + Ranking

**Goal:** Give each search run its own curated list with reorder/remove and promotion into the application pipeline.

**Requirements:** `LIST-01` through `LIST-04`

**Verified Closure**

1. A curated list exists for each search run.
2. The list detail payload includes the candidate display fields the UI needs.
3. Reorder/remove/edit operations mutate only `JobListItem` state, not raw `JobCandidate` history.
4. Promotion bridges into canonical ingest before `ingested` and `promoted` are marked.

### Phase 19: Company Intelligence

**Goal:** Collect and present browser-snapshot-backed research claims and interview questions with provenance.

**Requirements:** `INTL-01` through `INTL-04`

**Closure Criteria**

1. Research refresh persists a timestamped snapshot and does not mutate history in place.
2. Normalized claims and interview questions retain source provenance.
3. UI shows freshness, provenance, and refresh state explicitly.
4. Research is reachable from the `Research` route and from job/list entry points.

### Phase 20: LightRAG Career Memory

**Goal:** Build the event and query layer that turns career activity into long-lived graph memory.

**Requirements:** `GRAPH-01` through `GRAPH-03`

**Plans:** 3/3 plans complete

Plans:
- [x] 20B-01-PLAN.md -- Event contracts, event bus, and emission hooks (GRAPH-01)
- [x] 20C-02-PLAN.md -- Graph worker, query service, read models, and API endpoints (GRAPH-02, GRAPH-03)
- [ ] 20-PLAN.md -- Phase-level planning document (reference)

**Closure Criteria**

1. Source, search, list, research, and application actions emit graph-ingest events.
2. LightRAG initialization and ingest run behind a worker/service boundary.
3. Query APIs return stable read models and degrade gracefully when the worker is unavailable.
4. A dedicated Graph page is optional; graph-backed read models are required.

### Phase 21: UI/UX Integration

**Goal:** Integrate all new user-facing v1.2 surfaces into a coherent navigation and state model.

**Requirements:** `UX-01` through `UX-03`

**Closure Criteria**

1. Navigation exposes `Documents > Sources`, `Search`, `Lists`, and `Research` coherently.
2. Empty/loading/error/stale states are consistent across the new surfaces.
3. Remove, reorder, and promote actions are understandable, keyboard-accessible, and safe.
4. The frontend builds cleanly after the integration work.

### Phase 22: Verification + Audit

**Goal:** Close the milestone with validation coverage, evidence, and reconciled milestone docs.

**Requirements:** `AUD-01` through `AUD-03`

**Closure Criteria**

1. Phase-level validation and verification docs are complete for every v1.2 phase.
2. End-to-end v1.2 flows are exercised and documented with concrete evidence.
3. Root planning docs and the final audit artifact match implementation truth.

---

*Last updated: 2026-04-06*
