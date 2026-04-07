export interface Job {
  canonical_index: number;
  identity_key: string;
  job: {
    index: number;
    heading: string;
    company: string;
    role: string;
    salary: string;
    remote: string;
    experience: string;
    key_skills: string[];
    apply: string;
    apply_url: string;
    why_fit: string;
    summary: string;
    company_context: string | null;
  };
}

export interface JobManifest {
  generated_at: string;
  primary_workspace: string;
  total_jobs: number;
  jobs: Job[];
}

export type ApplicationStatus = 'COMPLETE' | 'PARTIAL_RESUME' | 'MARKDOWN' | 'MISSING';

export interface ApplicationInfo {
  index: number;
  company: string;
  role: string;
  source: string;
  status: ApplicationStatus;
  applyUrl: string;
  bundle: string | null;
  resumeMd: string | null;
  resumePdf: string | null;
  coverLetterMd: string | null;
  coverLetterPdf: string | null;
  provenance: string | null;
}

export interface RubricScores {
  draft: Record<string, number>;
  final: Record<string, number>;
  rejected_claims: string[];
}

export interface ExternalEvaluation {
  verdict: 'NEEDS_REVISION' | 'APPROVED' | 'PENDING';
  scores: Record<string, number>;
  strengths: string[];
  weaknesses: string[];
  revision_suggestions: string[];
  human_review_checklist: HumanReviewItem[];
}

export interface HumanReviewItem {
  item: string;
  status: 'PASS' | 'FAIL' | 'WARN';
  note: string;
}

export interface EnrichedJob extends ApplicationInfo {
  job: Job['job'];
  rubricScores: RubricScores | null;
  evaluation: ExternalEvaluation | null;
  postingStatus: PostingStatusInfo | null;
}

// Job posting status (from job_status_checker)
export type PostingStatus = 'ACTIVE' | 'CLOSED' | 'EXPIRED' | 'ERROR' | 'UNKNOWN';
export type JobSource = 'greenhouse' | 'lever' | 'generic';

export interface PostingStatusInfo {
  index: number;
  url: string;
  status: PostingStatus;
  lastChecked: string | null;
  error: string | null;
  source: JobSource;
  httpStatusCode: number | null;
  responseTimeMs: number | null;
}

// ── Source Record Domain Types ────────────────────────────────────────────────

/** Archetype determines which field groups a source record contains. */
export type SourceArchetype = 'new_grad' | 'experienced';

/** A single field value inside a source record. */
export interface SourceFieldValue {
  field_id: string;
  label: string;
  value: string;
  category: string;       // e.g. "identity", "education", "experience", "skills"
  order: number;          // display order within the category
}

/** A revision snapshot created on every save. */
export interface SourceRevision {
  revision_id: string;
  record_id: string;
  created_at: string;     // ISO-8601
  provenance: string;     // "manual_edit" | "note_extraction" | "import"
  summary: string;        // human-readable diff summary
  field_count: number;
}

/** A source record: a structured collection of facts tied to an archetype. */
export interface SourceRecord {
  record_id: string;
  archetype: SourceArchetype;
  label: string;          // display name, e.g. "My Profile"
  fields: SourceFieldValue[];
  created_at: string;
  updated_at: string;
  revision_count: number;
}

/** Suggested update produced by note extraction. */
export interface SourceSuggestion {
  suggestion_id: string;
  record_id: string;
  field_id: string;
  field_label: string;
  current_value: string;
  suggested_value: string;
  confidence: number;     // 0..1
  source_note: string;    // the original freeform note text
}

/** Response from the note-extraction endpoint. */
export interface NoteExtractionResponse {
  suggestions: SourceSuggestion[];
  note_text: string;
  created_at: string;
}

/** Archetype field schema describing which fields an archetype contains. */
export interface ArchetypeFieldSchema {
  field_id: string;
  label: string;
  category: string;
  order: number;
  placeholder: string;
  required: boolean;
}

/** Full archetype definition. */
export interface ArchetypeDefinition {
  archetype: SourceArchetype;
  label: string;
  description: string;
  fields: ArchetypeFieldSchema[];
}

// ── Search Domain Types ────────────────────────────────────────────────────────

/** Status of a search run. */
export type SearchRunStatus = 'pending' | 'running' | 'completed' | 'failed';

/** A saved search preference preset. */
export interface SearchPreference {
  preference_id: string;
  label: string;                     // display name, e.g. "SWE Jobs Denver"
  archetype: SourceArchetype;        // which source archetype to use
  keywords: string[];               // search keywords/roles
  locations: string[];              // preferred locations (empty = all)
  sources: JobSource[];             // which ATS platforms to target
  experience_level: string | null;   // e.g. "mid", "senior", "entry"
  remote_policy: string | null;     // "remote", "hybrid", "onsite"
  salary_min: number | null;        // minimum salary (optional filter)
  created_at: string;
  updated_at: string;
  last_run_at: string | null;       // ISO-8601, when this pref was last used
}

/** A single job candidate extracted from a search run. */
export interface JobCandidate {
  candidate_id: string;             // stable identity key for dedup
  run_id: string;                   // which search run produced this
  source: JobSource;                // greenhouse | lever | generic
  source_url: string;               // original job posting URL
  company: string;
  role: string;
  location: string | null;
  salary: string | null;
  remote: string | null;
  posted_date: string | null;       // ISO-8601 date string
  apply_url: string | null;
  identity_key: string;             // computed dedup key (company + role normalized)
  is_duplicate: boolean;            // true if this role+company appeared in a prior run
  duplicate_of_candidate_id: string | null;  // if duplicate, which candidate it dups
  ingested: boolean;                // whether this was promoted to canonical inventory
  created_at: string;
}

/** A single search execution run. */
export interface SearchRun {
  run_id: string;
  preference_id: string | null;     // null if ad-hoc run
  preference_label: string | null; // denormalized label for display
  status: SearchRunStatus;
  started_at: string;              // ISO-8601
  completed_at: string | null;      // ISO-8601
  total_candidates: number;
  new_candidates: number;           // non-duplicate count
  duplicate_count: number;
  error_message: string | null;
}

/** Response when creating a new run. */
export interface SearchRunCreated {
  run_id: string;
  status: SearchRunStatus;
  started_at: string;
}

/** Detailed view of a run including its candidates. */
export interface SearchRunDetail extends SearchRun {
  candidates: JobCandidate[];
}

/** Summary of a run for list display (no candidates array). */
export interface SearchRunSummary {
  run_id: string;
  preference_id: string | null;
  preference_label: string | null;
  status: SearchRunStatus;
  started_at: string;
  completed_at: string | null;
  total_candidates: number;
  new_candidates: number;
  duplicate_count: number;
  error_message: string | null;
}

// ── Job List Domain Types ───────────────────────────────────────────────────

/** A curated job list attached to a search run. */
export interface JobList {
  list_id: string;
  run_id: string;
  label: string;
  created_at: string;
  updated_at: string;
}

/** Priority level for a list item. */
export type ListItemPriority = 'low' | 'medium' | 'high';

/** Application status for a list item. */
export type ListItemStatus = 'wishlist' | 'applied' | 'rejected';

/** A single item within a curated job list. */
export interface JobListItem {
  item_id: string;
  list_id: string;
  candidate_id: string;
  position: number;
  notes: string | null;
  priority: ListItemPriority | null;
  status: ListItemStatus | null;
  promoted: boolean;
  created_at: string;
}

/** A list item with denormalized candidate data for display. */
export interface JobListItemDisplay extends JobListItem {
  source: string;
  source_url: string;
  company: string;
  role: string;
  location: string | null;
  salary: string | null;
  remote: string | null;
  posted_date: string | null;
  apply_url: string | null;
  identity_key: string;
  is_duplicate: boolean;
  ingested: boolean;
  fit_score?: number;
  research_summary?: {
    has_research: boolean;
    claim_count: number;
    question_count: number;
    last_refreshed_at: string | null;
    is_stale: boolean;
  };
}

/** A list with its full ordered items and denormalized candidate data. */
export interface JobListDetail extends JobList {
  items: JobListItemDisplay[];
}

// ── Research Domain Types ────────────────────────────────────────────────

/** Confidence level for a research claim. */
export type ResearchConfidence = 'high' | 'medium' | 'low';

/** Stale tier for freshness indicator. */
export type ResearchStaleTier = 'fresh' | 'stale' | 'very_stale';

/** A research claim extracted from a snapshot. */
export interface ResearchClaim {
  claim_id: string;
  snapshot_id: string;
  company_key: string;
  claim_text: string;
  source_url: string;
  collected_at: string;
  confidence: ResearchConfidence;
  themes: string[];
  sentiment_score: number | null;
  role_applicability: string[];
}

/** An interview question extracted from a snapshot. */
export interface InterviewQuestion {
  question_id: string;
  snapshot_id: string;
  company_key: string;
  question_text: string;
  source_url: string;
  collected_at: string;
  role_applicability: string[];
  themes: string[];
}

/** Summary of a research snapshot. */
export interface ResearchSnapshotSummary {
  snapshot_id: string;
  collected_at: string;
  source_count: number;
  claim_count: number;
  question_count: number;
}

/** Full company research response. */
export interface CompanyResearch {
  company_key: string;
  company_name: string;
  last_refreshed_at: string | null;
  is_stale: boolean;
  stale_days: number | null;
  claims: ResearchClaim[];
  questions: InterviewQuestion[];
  snapshots: ResearchSnapshotSummary[];
}

/** Company list item from GET /api/research/companies. */
export interface ResearchCompanySummary {
  company_key: string;
  company_name: string;
  last_refreshed_at: string | null;
  is_stale: boolean;
  claim_count: number;
  question_count: number;
  latest_snapshot_id: string | null;
}

/** Convenience alias matching the company list item shape used in ResearchPage. */
export type ResearchCompany = ResearchCompanySummary;

/** Refresh lifecycle status. */
export type ResearchRefreshStatus = 'pending' | 'running' | 'completed' | 'failed';

/** Response from POST /api/research/company/{key}/refresh. */
export interface RefreshCreated {
  refresh_id: string;
  company_key: string;
  status: 'pending';
  started_at: string;
}

/** Response from GET /api/research/refresh/{id}. */
export interface RefreshStatus {
  refresh_id: string;
  company_key: string;
  status: ResearchRefreshStatus;
  started_at: string;
  completed_at: string | null;
  current_source: string | null;
  sources_total: number;
  sources_completed: number;
  error_message: string | null;
}
