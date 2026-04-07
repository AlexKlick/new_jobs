---
phase: 20-lightrag-career-memory
plan: 01
subsystem: graph
tags: [lightrag, sqlite, event-sourcing, pydantic, fastapi, worker-pattern, degraded-mode, idempotency]

# Dependency graph
requires:
  - phase: 16-source-workspace
    provides: Source records and archetype-aware profile editing
  - phase: 17-job-search-discovery
    provides: Search preferences and ATS-first job discovery
  - phase: 18-saved-lists-ranking
    provides: Multi-list job curation with promote flow
  - phase: 19-company-intelligence
    provides: Company research snapshots with provenance
provides:
  - "SQLite-backed career event bus with idempotency keys covering all 5 service domains"
  - "Worker boundary isolating LightRAG initialization from request handlers"
  - "Typed Pydantic read models for company-history and search-history queries"
  - "Three FastAPI graph endpoints with degraded-mode fallback"
  - "35 passing tests (22 event layer + 13 worker/service/API)"
affects: [21-uiux-integration, 22-verification-audit]

# Tech tracking
tech-stack:
  added: [pydantic-event-models, sqlite-event-store, pydantic-read-models]
  patterns: [fire-and-forget-event-emission, idempotency-key-deduplication, worker-boundary, degraded-mode-fallback, lazy-lightrag-init]

key-files:
  created:
    - graph/__init__.py
    - graph/career_event_models.py
    - graph/career_event_store.py
    - graph/career_event_bus.py
    - graph/career_graph_read_models.py
    - graph/career_graph_worker.py
    - graph/career_graph_service.py
    - tests/test_career_event_store.py
    - tests/test_career_event_bus.py
    - tests/test_career_event_emission.py
    - tests/test_career_graph_worker.py
    - tests/test_career_graph_service.py
    - tests/test_graph_api.py
  modified:
    - research/source_service.py
    - search/search_service.py
    - search/search_store.py
    - research/company_research_service.py
    - canonical_ingest.py
    - api_server.py

key-decisions:
  - "Idempotency key auto-generated as category:entity_id:action:minute-bucket for automatic dedup"
  - "All emit_career_event calls wrapped in try/except so graph failures never break primary service flows"
  - "LightRAG import is lazy inside worker.initialize() so the module loads without LightRAG installed"
  - "Worker startup uses deprecated on_event pattern for consistency with existing api_server.py code"
  - "company_key validated with regex [a-zA-Z0-9_-]+ to prevent injection"
  - "limit parameter clamped to [1,100] via FastAPI Query validator"

patterns-established:
  - "Event emission pattern: import emit_career_event, call in try/except after mutation, never in critical path"
  - "Idempotency key pattern: category:entity_id:action:minute_bucket for automatic dedup"
  - "Worker boundary: LightRAG initialization runs only in worker.initialize(), never in request handlers"
  - "Degraded mode: When worker is unhealthy, service returns GraphDegradedResponse instead of raising errors"
  - "Health gating: All query methods check worker.is_healthy() before proceeding"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-03]

# Metrics
duration: 53min
completed: 2026-04-07
---

# Phase 20 Plan 01: LightRAG Career Memory Summary

**SQLite-backed career event bus with 5-domain emission hooks, worker-boundaried LightRAG integration, typed read models, and degraded-mode graph query endpoints**

## Performance

- **Duration:** ~53 min (across both sub-plans)
- **Started:** 2026-04-07T04:38:29Z
- **Completed:** 2026-04-07T19:29:07Z
- **Sub-plans:** 2 (20B-01 + 20C-02)
- **Files created/modified:** 18

## Acceptance Criteria Verification

### AC1: Source, search, list, research, and application actions all emit graph-ingest events
**Status: PASS** -- `emit_career_event` calls verified in all 5 service domains:
- `research/source_service.py`: 4 calls (create, update, delete, plus import)
- `search/search_service.py`: 4 calls (run started, completed, failed, plus import)
- `search/search_store.py`: 7 calls (reorder, remove, notes, priority, status, promote, plus import)
- `research/company_research_service.py`: 4 calls (refresh started, completed, failed, plus import)
- `canonical_ingest.py`: 2 calls (ingest for new and existing candidates)
- All 22 event-layer tests pass (12 store/bus + 10 emission)

### AC2: LightRAG runs behind a worker boundary instead of inside request handlers
**Status: PASS** -- `CareerGraphWorker` class in `graph/career_graph_worker.py`:
- LightRAG import is lazy, inside `async def initialize()` method (line 51), not at module level
- `is_healthy()` returns False before initialization, True after
- Request handlers call `CareerGraphService`, which delegates to worker -- never initializing LightRAG directly
- Worker tests pass (3/3)

### AC3: Query APIs return stable read models for company-history and search-history questions
**Status: PASS** -- Three API endpoints in `api_server.py`:
- `GET /api/graph/health` returns `GraphHealthResponse` with status, is_available, event counts
- `GET /api/graph/company/{company_key}/history` returns `CompanyHistoryReadModel` with entries, related_companies
- `GET /api/graph/search/history` returns `SearchHistoryReadModel` with entries, companies_seen
- Input validation: company_key regex validation, limit clamped to [1,100]
- API tests pass (5/5)

### AC4: Worker outage degrades gracefully rather than breaking the main app
**Status: PASS** -- Degraded-mode handling:
- `CareerGraphService.query_company_history()` returns `GraphDegradedResponse` when worker is unhealthy
- `CareerGraphService.query_search_history()` returns `GraphDegradedResponse` when worker is unhealthy
- `GraphDegradedResponse` carries `is_degraded=True`, a user-facing message, and `total_events` from store
- Startup hook wraps `worker.initialize()` in try/except -- init failure logs warning, does not crash app
- All `emit_career_event` calls in service domains are fire-and-forget with try/except
- Degraded-mode tests pass (3/3)

## Sub-Plan Cross-References

| Sub-Plan | Deliverable | Commits | Tests | Requirements |
|----------|-------------|---------|-------|--------------|
| 20B-01 | Event contracts, SQLite bus, 5-domain emission hooks | 7694ae5b, a28f8ead, 7294ed37 | 22 | GRAPH-01 |
| 20C-02 | Graph worker, service, read models, API endpoints | ec1b59c4, d874f5a1, e358a083 | 13 | GRAPH-02, GRAPH-03 |

### 20B-01: Graph Event Contracts
- CareerEventEnvelope with 5 typed payload models (Source, Search, List, Research, Application)
- SQLite append-only CareerEventStore with UNIQUE idempotency key constraint
- CareerEventBus with auto-generated idempotency keys (minute-bucket dedup)
- Event emission wired into all 5 domains
- Deviations: Reconstructed corrupted search_service.py (Rule 1), added source_service.py shim (Rule 1), added existing-match emission path (Rule 2)
- See: [20B-01-SUMMARY.md](./20B-01-SUMMARY.md)

### 20C-02: Graph Worker, Service, and API Endpoints
- CareerGraphWorker with async event processing, lazy LightRAG initialization, health checks
- CareerGraphService with health-gated queries returning GraphDegradedResponse when unavailable
- Typed Pydantic read models (GraphHealthResponse, CompanyHistoryReadModel, SearchHistoryReadModel, GraphDegradedResponse)
- Three API endpoints with input validation (company_key regex, limit clamping)
- Worker startup hook with graceful failure handling
- Deviations: Added company_key input validation from threat model (Rule 2)
- See: [20C-02-SUMMARY.md](./20C-02-SUMMARY.md)

## Combined Metrics

| Metric | 20B-01 | 20C-02 | Total |
|--------|--------|--------|-------|
| Files created | 7 | 6 | 13 |
| Files modified | 5 | 1 | 6* |
| Tests added | 22 | 13 | 35 |
| Commits | 3 (+1 docs) | 3 (+1 docs) | 8 |
| Duration | ~45 min | ~8 min | ~53 min |

*api_server.py modified by 20C-02 only; 20B-01 modified the 5 service files.

## Deviations from Plan

### Sub-Plan 20B-01

**1. [Rule 1 - Bug] Reconstructed corrupted search_service.py**
- search/search_service.py had garbled merge artifacts (181 lines of repeated fragments)
- Reconstructed from test expectations, preserving all 23 existing tests
- Committed in: a28f8ead

**2. [Rule 1 - Bug] Added source_service.py root shim**
- Root-level source_service.py was deleted during prior phase migration, breaking 24 tests
- Created re-export shim matching search_service.py pattern
- Committed in: a28f8ead

**3. [Rule 2 - Missing Critical] canonical_ingest emits on existing-match path**
- Original plan placed emit only after bridge.ingest(), missing early-return path
- Restructured so events emit for both new and existing candidates
- Committed in: 7294ed37

### Sub-Plan 20C-02

**4. [Rule 2 - Missing Critical] Added company_key input validation**
- Threat model T-20C-01 specified validation but plan action code did not include it
- Added regex validation `^[a-zA-Z0-9_-]+$` with 400 response
- Committed in: e358a083

---

**Total deviations:** 4 auto-fixed (2 bugs, 2 missing critical)
**Impact on plan:** All auto-fixes necessary for correctness and security. No scope creep.

## Issues Encountered

- Pre-existing test failures in test_search_api.py (5 tests fail due to missing `SearchStore.get_candidate` method) -- not caused by Phase 20 changes, confirmed by sub-plan executor
- search_service.py was completely corrupted from prior work -- required full reconstruction
- source_service.py root import shim was missing from prior phase migration

## User Setup Required

None - no external service configuration required. LightRAG initialization gracefully degrades when the library is not installed.

## Next Phase Readiness

- Graph event contract layer complete with all 5 domains emitting events
- CareerGraphWorker provides the foundation for LightRAG ingestion; initializes when library is installed
- Read models provide stable typed surfaces for the UI layer to consume in Phase 21
- Degraded mode ensures the application runs correctly even without LightRAG
- The 5 pre-existing test_search_api failures should be tracked for Phase 22 verification
- API endpoints ready for UI integration: /api/graph/health, /api/graph/company/{key}/history, /api/graph/search/history

---
*Phase: 20-lightrag-career-memory*
*Completed: 2026-04-07*

## Self-Check: PASSED

All 13 created files verified present. All 7 sub-plan commit hashes verified in git log. All 35 tests pass. SUMMARY.md exists.
