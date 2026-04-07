# Requirements: Job Application Tracker

**Defined:** 2026-03-27
**Last updated:** 2026-04-04

## Core Value

Ship a local-first career workspace that keeps application materials, reusable source data, discovery work, company research, and long-term memory organized without fragmenting the existing canonical job pipeline.

## Status Language

- **Complete**: implemented and verified with trusted evidence
- **Reopened**: implementation exists, but closure criteria or verification truth are not yet satisfied
- **Planned**: not yet implemented or not yet ready to claim implementation

## v1.1 Requirements

Requirements for the v1.1 Assistant Integration milestone. Each maps to shipped roadmap phases.

### Reporting

- [x] **RPT-01**: System has complete capability catalog documenting all features
- [x] **RPT-02**: System has documented performance benchmark results
- [x] **RPT-03**: All fixes from verification/gap-closure phases are documented with rationale
- [x] **RPT-04**: Recommendations for future work are documented

### Voice & Text Chat

- [x] **CHAT-01**: User can use push-to-talk voice input — press-to-record, release-to-send, VAD handles silence detection
- [x] **CHAT-02**: User can type text chat as fallback when voice is inappropriate
- [x] **CHAT-03**: LLM responds conversationally via vLLM Nanbeige (OpenAI-compatible API on port 8000)
- [x] **CHAT-04**: User sees visual feedback during processing (activity indicator, transcription display, "thinking..." state)

### Document Grounding

- [x] **DOCS-01**: Chat system injects resume/cover letter content as context when discussing specific job applications
- [x] **DOCS-02**: User can switch between job applications in chat context

### Text-to-Speech Output

- [x] **TTS-01**: LLM responses are read aloud using VibeVoice or MOSS TTS (reuse existing infrastructure)
- [x] **TTS-02**: User can toggle TTS on/off

### Skills & Prompts Editor

- [x] **SKLS-01**: User can edit skills/prompts YAML files in-app with CodeMirror editor and schema validation
- [x] **SKLS-02**: Skills editor supports backup on save (`.bak` files)
- [x] **SKLS-03**: Skills/prompts are versioned and can be reviewed/diffed

### Claude Code Agent

- [x] **AGNT-01**: User can request file modifications via natural language ("make my resume emphasize Python")
- [x] **AGNT-02**: Agent is sandboxed to `applications/{job_id}/`, `facts/`, `skills/` directories only
- [x] **AGNT-03**: Agent operations have rollback enabled with checkpoint tracking
- [x] **AGNT-04**: Agent has circuit breaker for escalation loops (threshold=3, window=300s)
- [x] **AGNT-05**: Agent operations have execution timeouts and iteration limits
- [x] **AGNT-06**: Agent path allowlisting is enforced (denied: `../`, `./.env`)

## v1.2 Requirements

Requirements for the v1.2 Career Workspace And Search Intelligence milestone.

### Source Workspace

- [x] **SRC-01**: User can switch between application documents and reusable source records inside `Documents`
- [x] **SRC-02**: User can maintain structured source records for built-in `new_grad` and `experienced` archetypes
- [x] **SRC-03**: Source record edits create revision history with timestamps and provenance
- [x] **SRC-04**: Freeform notes can be normalized into suggested structured source updates

### Job Search Discovery

- [x] **SRCH-01**: User can save ATS-first search preferences and run them on demand
- [x] **SRCH-02**: Search results are sourced from supported ATS-first/public connectors before broader generic web search
- [x] **SRCH-03**: Each execution persists an immutable `SearchRun` snapshot
- [x] **SRCH-04**: Duplicate jobs are recognized across runs and sources without mutating prior snapshots

### Saved Lists + Ranking

- [x] **LIST-01**: Every `SearchRun` creates a default curated `JobList`
- [x] **LIST-02**: User can reorder and remove `JobListItem` entries without mutating raw `JobCandidate` history
- [x] **LIST-03**: List items can store ranking metadata such as notes, priority, and status
- [x] **LIST-04**: Promoting a curated item flows into the existing canonical application ingest pipeline

### Company Intelligence

- [ ] **INTL-01**: Refreshing company research creates a persisted timestamped snapshot
- [ ] **INTL-02**: Normalized research claims and interview questions retain source provenance
- [ ] **INTL-03**: Every rendered research claim includes freshness and provenance metadata
- [ ] **INTL-04**: Research is accessible from company, job, and list surfaces

### LightRAG Career Memory

- [ ] **GRAPH-01**: Source, search, list, research, and application actions emit graph-ingest events
- [ ] **GRAPH-02**: LightRAG ingestion and query execution run behind a worker/service boundary rather than inside request handlers
- [ ] **GRAPH-03**: Graph query APIs can answer cross-company and cross-search career-memory questions and degrade gracefully when the worker is unavailable

### UI/UX Integration

- [ ] **UX-01**: Navigation exposes `Documents > Sources`, `Search`, `Lists`, and `Research` coherently
- [ ] **UX-02**: Empty, loading, error, and stale states are deliberate and consistent across new v1.2 surfaces
- [ ] **UX-03**: Reorder, remove, and promote actions are understandable, keyboard-accessible, and safe

### Verification + Audit

- [ ] **AUD-01**: Phase-level validation and verification docs are complete for every v1.2 phase
- [ ] **AUD-02**: End-to-end v1.2 flows are exercised and documented with concrete evidence
- [ ] **AUD-03**: Root planning docs and milestone audit artifacts are internally consistent with implementation truth

## Deferred / Future Requirements

Tracked but not part of the current execution backlog.

### Multi-Application Support

- **MULT-01**: Skill templates per job type (SWE vs ML vs consulting)
- **MULT-02**: Generation history with ability to revisit past outputs
- **MULT-03**: Cross-document discussion — discuss multiple job applications in one conversation

### Advanced Voice

- **VOIC-01**: Real-time continuous voice listening (battery, privacy concerns — not v1.1)
- **VOIC-02**: Voice activity detection calibration at startup

### Advanced Agent

- **AGNT-07**: Multi-step agent reasoning with checkpointing
- **AGNT-08**: Agent audit log with full operation history

## Out of Scope

Explicitly excluded to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Real-time continuous voice listening | Battery drain, privacy issues, accidental activations |
| Multi-user collaborative editing | Complexity explosion, not core value |
| Fully autonomous job-applying agent | High risk of embarrassment, LinkedIn ToS violations |
| Unlimited context window | Nanbeige has finite context; performance degrades |
| Mobile native app | PWA works well; native not needed |
| Video chat integration | External tools; not core to document management |
| Replacing the existing application-generation pipeline | The canonical ingest and application bundle flow remains authoritative |

## Traceability

Which phases cover which requirements.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RPT-01 | Phase 12 | Complete |
| RPT-02 | Phase 12 | Complete |
| RPT-03 | Phase 12 | Complete |
| RPT-04 | Phase 12 | Complete |
| CHAT-01 | Phase 8 | Complete |
| CHAT-02 | Phase 8 | Complete |
| CHAT-03 | Phase 8 | Complete |
| CHAT-04 | Phase 8 | Complete |
| DOCS-01 | Phase 8 | Complete |
| DOCS-02 | Phase 8 | Complete |
| TTS-01 | Phase 8 | Complete |
| TTS-02 | Phase 8 | Complete |
| SKLS-01 | Phase 9 | Complete |
| SKLS-02 | Phase 9 | Complete |
| SKLS-03 | Phase 9 | Complete |
| AGNT-01 | Phase 10 | Complete |
| AGNT-02 | Phase 10 | Complete |
| AGNT-03 | Phase 10 | Complete |
| AGNT-04 | Phase 10 | Complete |
| AGNT-05 | Phase 10 | Complete |
| AGNT-06 | Phase 10 | Complete |
| SRC-01 | Phase 16 | Complete |
| SRC-02 | Phase 16 | Complete |
| SRC-03 | Phase 16 | Complete |
| SRC-04 | Phase 16 | Complete |
| SRCH-01 | Phase 17 | Complete |
| SRCH-02 | Phase 17 | Complete |
| SRCH-03 | Phase 17 | Complete |
| SRCH-04 | Phase 17 | Complete |
| LIST-01 | Phase 18 | Complete |
| LIST-02 | Phase 18 | Complete |
| LIST-03 | Phase 18 | Complete |
| LIST-04 | Phase 18 | Complete |
| INTL-01 | Phase 19 | Planned |
| INTL-02 | Phase 19 | Planned |
| INTL-03 | Phase 19 | Planned |
| INTL-04 | Phase 19 | Planned |
| GRAPH-01 | Phase 20 | Planned |
| GRAPH-02 | Phase 20 | Planned |
| GRAPH-03 | Phase 20 | Planned |
| UX-01 | Phase 21 | Planned |
| UX-02 | Phase 21 | Planned |
| UX-03 | Phase 21 | Planned |
| AUD-01 | Phase 22 | Planned |
| AUD-02 | Phase 22 | Planned |
| AUD-03 | Phase 22 | Planned |

## Coverage

- v1.1 requirements: 21 total, all mapped
- v1.2 requirements: 25 total, all mapped
- unmapped requirements: 0
