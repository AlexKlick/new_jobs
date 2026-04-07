# TODO: v1.2 Audit And Execution Backlog

**Prepared:** 2026-04-04
**Updated:** 2026-04-04
**Scope:** Track execution order now that Search and Lists have been reconciled and re-closed with evidence.

## Summary

This file is the execution-order companion to the root planning docs.

- Phases `01-14` remain trusted through the shipped v1.0 and v1.1 milestone audits.
- Phase `15` remains outside the v1.2 execution line and should be treated as audit-only drift.
- Phases `16-18` are now the trusted v1.2 baseline.
- Phases `19-22` should execute from that verified foundation.

## Repo Truth Snapshot (2026-04-04)

- `.venv/bin/python -m pytest tests/test_search_store.py tests/test_search_service.py tests/test_search_api.py tests/test_source_service.py tests/test_source_api.py -q` -> `85 passed, 1 warning`
- `cd ui && npm run build` -> success
- `Search` and `Lists` runtime surfaces exist and now match their documented closure criteria.
- `Research` and graph-memory runtime surfaces do not exist yet.
- One residual warning remains in `tests/test_search_service.py` and should be cleaned up in Phase 22 if not earlier.

## Phase Status Matrix

| Phase | Name | Status | Why |
|------|------|--------|-----|
| 16 | Source Workspace | Complete | Implemented, tested, and verified |
| 17 | Job Search Discovery | Complete | Search/UI/API closure evidence captured on 2026-04-04 |
| 18 | Saved Lists + Ranking | Complete | List payload and canonical-promotion behavior verified on 2026-04-04 |
| 19 | Company Intelligence | Planned | No runtime implementation yet |
| 20 | LightRAG Career Memory | Planned | No worker/query implementation yet |
| 21 | UI/UX Integration | Planned | Depends on stable Research and graph foundations |
| 22 | Verification + Audit | Planned | Must close the milestone with evidence and final reconciliation |

## Hardening Gate

Gate status: complete on 2026-04-04.

### `DEN-001` Frontend Build Stabilization

**Status**

Complete.

**Evidence**

- `cd ui && npm run build` -> success

### `DEN-002` Shared API Base Migration

**Status**

Complete.

**Evidence**

- `ui/src/components/SearchPage.tsx` imports `API_BASE`
- `ui/src/components/SourcesWorkspace.tsx` imports `API_BASE`
- `ui/src/config.ts` defines the shared frontend API base

### `DEN-003` Phase 17 Closure

**Status**

Complete.

**Evidence**

- Search only exposes selectable `greenhouse` and `lever` connectors
- `generic` is labeled `coming later` in the create dialog and `generic (deferred)` in display paths
- `.venv/bin/python -m pytest tests/test_search_store.py tests/test_search_service.py tests/test_search_api.py tests/test_source_service.py tests/test_source_api.py -q` -> `85 passed, 1 warning`

### `DEN-004` Phase 18 Closure

**Status**

Complete.

**Evidence**

- `tests/test_search_api.py` verifies list detail returns denormalized candidate fields required by the UI
- `tests/test_search_api.py` verifies canonical ingest runs before list/item flags are marked
- `tests/test_search_store.py` verifies list mutation and promotion state behavior

## Phase 19 Execution Backlog

### `DEN-100` Research Domain And Storage

**Scope**

- Define `ResearchSnapshot`, `ResearchArtifact`, `ResearchClaim`, and `InterviewQuestionSnapshot` contracts.
- Add a local research store with timestamped snapshot history.

**Acceptance**

- Snapshot history is persisted independently from normalized read models.

### `DEN-101` Snapshot Refresh Pipeline

**Scope**

- Add refresh orchestration and background execution.
- Persist raw artifacts before normalization.
- Restrict acquisition to public or user-provided sources.

**Acceptance**

- Refresh creates new snapshots rather than mutating prior history.

### `DEN-102` Claim And Interview Normalization

**Scope**

- Normalize snapshots into claims and interview-question entries.
- Keep source URL, collected timestamp, and provenance metadata on every rendered item.

**Acceptance**

- Unsourced claims are not rendered as first-class research output.

### `DEN-103` Research APIs And UI

**Scope**

- Add `Research` route and read-model APIs.
- Deep-link into research from job and list surfaces.

**Acceptance**

- Research is reachable from the top-level route and contextual entry points.

## Phase 20 Execution Backlog

### `DEN-200` Career Event Contracts

**Scope**

- Define event payloads for source, search, list, research, and application actions.
- Add explicit idempotency keys and timestamps.

### `DEN-201` Graph Event Bus And Worker Boundary

**Scope**

- Add queue/storage for graph ingest events.
- Build worker-owned LightRAG initialization and ingest.
- Keep request handlers enqueue-only.

### `DEN-202` Query APIs And Degraded Mode

**Scope**

- Add graph-backed query APIs/read models.
- Return structured degraded-mode responses when the worker is unavailable.

### `DEN-203` UI Exposure

**Scope**

- Surface graph-backed read models inside Research/company contexts.
- A dedicated standalone Graph page is optional and should not block phase closure.

## Phase 21 Execution Backlog

### `DEN-300` Navigation And Route Integration

**Scope**

- Integrate `Documents > Sources`, `Search`, `Lists`, and `Research` into a coherent route model.

### `DEN-301` Shared Page-State Contract

**Scope**

- Standardize empty/loading/error/stale states across the new v1.2 surfaces.

### `DEN-302` Safe Interaction Pass

**Scope**

- Make remove, reorder, and promote flows understandable, keyboard-accessible, and safe.

### `DEN-303` Responsive And Build Integrity

**Scope**

- Keep the frontend build green while integrating all new surfaces.

## Phase 22 Execution Backlog

### `DEN-400` Validation Matrix

**Scope**

- Run and capture backend, frontend, and targeted browser checks.

### `DEN-401` End-To-End Evidence

**Scope**

- Document source update, search, list, research, and graph-memory flows with concrete evidence paths.

### `DEN-402` Audit Artifact And Root-Doc Reconciliation

**Scope**

- Publish a v1.2 audit artifact.
- Update roadmap, state, project, and requirement traceability to match implementation truth.

## Exit Criteria For v1.2

- `INTL-*`, `GRAPH-*`, `UX-*`, and `AUD-*` are either complete with evidence or explicitly deferred.
- Root planning docs agree with runtime behavior.
- No phase is marked closed without validation commands and verification evidence.
