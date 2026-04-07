import type { JobManifest, ApplicationStatus, EnrichedJob, RubricScores, ExternalEvaluation, PostingStatusInfo } from '../types';
// These three imports resolve through symlinks in the ui/ project root:
//   ui/jobs_manifest.json -> ../jobs_manifest.json
//   ui/APPLICATION_STATUS.md -> ../APPLICATION_STATUS.md
//   ui/applications/ -> ../applications/
// The symlinks allow Vite's import.meta.glob to stay within its project root.
import manifest from '../../jobs_manifest.json';
import postingStatusData from '../../job_posting_status.json';
import statusMd from '../../APPLICATION_STATUS.md?raw';

// Eager-load all application artifacts via glob.
// The glob keys are the source of truth for what actually exists on disk.
// We use symlinked paths (within ui/) so Vite allows the glob.
const rubricModules = import.meta.glob(
  '../../applications/all_jobs/*/rubric_scores.json',
  { eager: true }
) as Record<string, { default: RubricScores }>;

const evaluationModules = import.meta.glob(
  '../../applications/all_jobs/*/external_evaluation.json',
  { eager: true }
) as Record<string, { default: ExternalEvaluation }>;

const resumeModules = import.meta.glob(
  '../../applications/all_jobs/*/resume.md',
  { eager: true, query: '?raw', import: 'default' }
) as Record<string, string>;

const coverLetterModules = import.meta.glob(
  '../../applications/all_jobs/*/cover_letter.md',
  { eager: true, query: '?raw', import: 'default' }
) as Record<string, string>;

// Each entry in this map holds the ACTUAL glob keys emitted by Vite for a given
// job index, so artifact lookup is always exact — no path reconstruction needed.
interface ArtifactKeys {
  rubric: string | null;
  eval: string | null;
  resume: string | null;
  cl: string | null;
  bundlePath: string | null; // human-readable relative path for display / PDF links
}

function buildArtifactKeyMap(): Map<number, ArtifactKeys> {
  const map = new Map<number, ArtifactKeys>();

  // Extract job index from any glob key, e.g. .../all_jobs/05_remesh.../file.json → 5
  const indexFrom = (key: string): number | null => {
    const m = key.match(/all_jobs\/(\d+)_/);
    return m ? parseInt(m[1], 10) : null;
  };

  // Extract a clean human-readable bundle path from the key for display/PDF links
  const bundleFrom = (key: string): string | null => {
    const m = key.match(/(applications\/all_jobs\/\d+_[^/]+)/);
    return m ? m[1] : null;
  };

  const ensure = (index: number, key: string) => {
    if (!map.has(index)) {
      map.set(index, { rubric: null, eval: null, resume: null, cl: null, bundlePath: bundleFrom(key) });
    }
  };

  for (const key of Object.keys(rubricModules)) {
    const i = indexFrom(key); if (i === null) continue;
    ensure(i, key); map.get(i)!.rubric = key;
  }
  for (const key of Object.keys(evaluationModules)) {
    const i = indexFrom(key); if (i === null) continue;
    ensure(i, key); map.get(i)!.eval = key;
  }
  for (const key of Object.keys(resumeModules)) {
    const i = indexFrom(key); if (i === null) continue;
    ensure(i, key); map.get(i)!.resume = key;
    if (!map.get(i)!.bundlePath) map.get(i)!.bundlePath = bundleFrom(key);
  }
  for (const key of Object.keys(coverLetterModules)) {
    const i = indexFrom(key); if (i === null) continue;
    ensure(i, key); map.get(i)!.cl = key;
    if (!map.get(i)!.bundlePath) map.get(i)!.bundlePath = bundleFrom(key);
  }

  return map;
}

// Parse APPLICATION_STATUS.md table to get canonical status per job index.
// Format: | # | Company | Role | Source | Status | Apply URL | Bundle | ...
function parseStatusMd(): Map<number, ApplicationStatus> {
  const map = new Map<number, ApplicationStatus>();
  const validStatuses = new Set<string>(['COMPLETE', 'PARTIAL_RESUME', 'MARKDOWN', 'MISSING']);

  for (const line of statusMd.split('\n')) {
    if (!line.startsWith('|')) continue;
    const cols = line.split('|').map(c => c.trim()).filter(Boolean);
    if (cols.length < 5) continue;
    const index = parseInt(cols[0], 10);
    const status = cols[4];
    if (!isNaN(index) && validStatuses.has(status)) {
      map.set(index, status as ApplicationStatus);
    }
  }

  return map;
}

// Parse posting status JSON
interface PostingStatusStore {
  updated_at: string;
  statuses: PostingStatusInfo[];
}

function parsePostingStatus(): Map<number, PostingStatusInfo> {
  const map = new Map<number, PostingStatusInfo>();
  try {
    const data = postingStatusData as PostingStatusStore;
    for (const entry of data.statuses) {
      map.set(entry.index, entry);
    }
  } catch (e) {
    console.warn('Could not parse posting status:', e);
  }
  return map;
}

export function loadAllJobs(): EnrichedJob[] {
  const jobManifest = manifest as JobManifest;
  const statusMap = parseStatusMd();
  const artifactMap = buildArtifactKeyMap();
  const postingStatusMap = parsePostingStatus();

  return jobManifest.jobs.map(job => {
    const index = job.canonical_index;
    const keys = artifactMap.get(index) ?? null;

    // Look up each artifact using the ACTUAL glob key — no path reconstruction
    const rubricScores = keys?.rubric ? (rubricModules[keys.rubric]?.default ?? null) : null;
    const evaluation   = keys?.eval   ? (evaluationModules[keys.eval]?.default ?? null) : null;
    const resumeContent      = keys?.resume ? (resumeModules[keys.resume] ?? null) : null;
    const coverLetterContent = keys?.cl     ? (coverLetterModules[keys.cl] ?? null) : null;
    const bundlePath = keys?.bundlePath ?? null;

    // Use APPLICATION_STATUS.md as authoritative source; fall back to inference
    const status: ApplicationStatus = statusMap.get(index) ?? (
      rubricScores ? 'COMPLETE' : bundlePath ? 'MARKDOWN' : 'MISSING'
    );

    // Get posting status
    const postingStatus = postingStatusMap.get(index) ?? null;

    return {
      index,
      company: job.job.company,
      role: job.job.role,
      source: 'new_job_denjobs',
      status,
      applyUrl: job.job.apply_url,
      bundle: bundlePath,
      resumeMd: resumeContent,
      resumePdf: bundlePath ? `${bundlePath}/resume.pdf` : null,
      coverLetterMd: coverLetterContent,
      coverLetterPdf: bundlePath ? `${bundlePath}/cover_letter.pdf` : null,
      provenance: bundlePath ? `${bundlePath}/run_metadata.json` : null,
      job: job.job,
      rubricScores,
      evaluation,
      postingStatus,
    };
  });
}

export function getJobByIndex(jobs: EnrichedJob[], index: number): EnrichedJob | undefined {
  return jobs.find(j => j.index === index);
}

export function getJobsByStatus(jobs: EnrichedJob[], status: string): EnrichedJob[] {
  return jobs.filter(j => j.status === status);
}

export function searchJobs(jobs: EnrichedJob[], query: string): EnrichedJob[] {
  const lower = query.toLowerCase();
  return jobs.filter(j =>
    j.company.toLowerCase().includes(lower) ||
    j.role.toLowerCase().includes(lower) ||
    j.job.key_skills.some(s => s.toLowerCase().includes(lower))
  );
}
