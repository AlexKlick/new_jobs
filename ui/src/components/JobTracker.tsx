import { useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { EnrichedJob, PostingStatusInfo } from '../types';

interface JobTrackerProps {
  jobs: EnrichedJob[];
}

const STATUS_COLORS: Record<string, string> = {
  COMPLETE: '#22c55e',
  PARTIAL_RESUME: '#f59e0b',
  MARKDOWN: '#3b82f6',
  MISSING: '#ef4444',
};

// Posting status colors
const POSTING_STATUS_COLORS: Record<string, string> = {
  ACTIVE: '#22c55e',
  CLOSED: '#ef4444',
  EXPIRED: '#f97316',
  ERROR: '#a855f7',
  UNKNOWN: '#6b7280',
};

const POSTING_STATUS_ICONS: Record<string, string> = {
  ACTIVE: '✓',
  CLOSED: '✗',
  EXPIRED: '⏰',
  ERROR: '⚠',
  UNKNOWN: '?',
};

type SortKey = 'index' | 'company' | 'role' | 'status' | 'score';
type SortDir = 'asc' | 'desc';

function getAvgScore(job: EnrichedJob): number | null {
  if (!job.rubricScores?.final) return null;
  const vals = Object.values(job.rubricScores.final);
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function formatRelativeTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  } catch {
    return isoString;
  }
}

const STATUS_ORDER: Record<string, number> = {
  COMPLETE: 0,
  PARTIAL_RESUME: 1,
  MARKDOWN: 2,
  MISSING: 3,
};

// API base URL - configure as needed
const API_BASE = '';

async function checkJobStatus(index: number): Promise<PostingStatusInfo> {
  const response = await fetch(`${API_BASE}/api/jobs/${index}/check-status`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to check status: ${response.statusText}`);
  }
  return response.json();
}

async function checkAllJobs(): Promise<void> {
  await fetch(`${API_BASE}/api/jobs/check-all`, {
    method: 'POST',
  });
}

export function JobTracker({ jobs }: JobTrackerProps) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [sortKey, setSortKey] = useState<SortKey>('index');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  // Local posting status state (overrides loaded data)
  const [localPostingStatus, setLocalPostingStatus] = useState<Record<number, PostingStatusInfo | null>>({});
  const [checkingJobs, setCheckingJobs] = useState<Record<number, boolean>>({});
  const [checkingAll, setCheckingAll] = useState(false);
  const [batchCheckStarted, setBatchCheckStarted] = useState(false);

  // Merge local posting status with loaded posting status
  const getPostingStatus = useCallback((job: EnrichedJob): PostingStatusInfo | null => {
    return localPostingStatus[job.index] ?? job.postingStatus;
  }, [localPostingStatus]);

  // Check single job status
  const handleCheckStatus = useCallback(async (index: number) => {
    setCheckingJobs(prev => ({ ...prev, [index]: true }));
    try {
      const result = await checkJobStatus(index);
      setLocalPostingStatus(prev => ({ ...prev, [index]: result }));
    } catch (error) {
      console.error(`Failed to check status for job ${index}:`, error);
    } finally {
      setCheckingJobs(prev => ({ ...prev, [index]: false }));
    }
  }, []);

  // Check all jobs
  const handleCheckAll = useCallback(async () => {
    setCheckingAll(true);
    setBatchCheckStarted(true);
    try {
      await checkAllJobs();
      // Poll for updates after batch check starts
      // In a real app, you'd use WebSocket or polling
    } catch (error) {
      console.error('Failed to start batch check:', error);
    } finally {
      setCheckingAll(false);
    }
  }, []);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  const filteredJobs = useMemo(() => {
    let result = jobs;

    if (statusFilter !== 'ALL') {
      result = result.filter(j => j.status === statusFilter);
    }

    if (search.trim()) {
      const lower = search.toLowerCase();
      result = result.filter(j =>
        j.company.toLowerCase().includes(lower) ||
        j.role.toLowerCase().includes(lower) ||
        j.job.key_skills.some(s => s.toLowerCase().includes(lower))
      );
    }

    return [...result].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'index':   cmp = a.index - b.index; break;
        case 'company': cmp = a.company.localeCompare(b.company); break;
        case 'role':    cmp = a.role.localeCompare(b.role); break;
        case 'status':  cmp = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9); break;
        case 'score': {
          const sa = getAvgScore(a) ?? -1;
          const sb = getAvgScore(b) ?? -1;
          cmp = sa - sb;
          break;
        }
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [jobs, search, statusFilter, sortKey, sortDir]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: jobs.length };
    jobs.forEach(j => { counts[j.status] = (counts[j.status] || 0) + 1; });
    return counts;
  }, [jobs]);

  // Posting status counts
  const postingStatusCounts = useMemo(() => {
    const counts: Record<string, number> = { checked: 0, unchecked: 0 };
    jobs.forEach(j => {
      const ps = getPostingStatus(j);
      if (ps && ps.status !== 'UNKNOWN') {
        counts.checked = (counts.checked || 0) + 1;
      } else {
        counts.unchecked = (counts.unchecked || 0) + 1;
      }
    });
    return counts;
  }, [jobs, getPostingStatus]);

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="sort-icon neutral">⇅</span>;
    return <span className="sort-icon active">{sortDir === 'asc' ? '↑' : '↓'}</span>;
  }

  function th(label: string, col: SortKey) {
    return (
      <th className="sortable-th" onClick={() => handleSort(col)}>
        {label} <SortIcon col={col} />
      </th>
    );
  }

  return (
    <div className="job-tracker">
      <div className="tracker-header">
        <h2>Application Tracker</h2>
        <div className="tracker-stats">
          <span className="stat">{jobs.length} Total Jobs</span>
          <span className="stat complete">{statusCounts.COMPLETE || 0} Complete</span>
          <span className="stat partial">{statusCounts.PARTIAL_RESUME || 0} Partial</span>
          <span className="stat missing">{statusCounts.MISSING || 0} Missing</span>
          <span className="stat posting-checked">{postingStatusCounts.checked || 0} Checked</span>
          <span className="stat posting-unchecked">{postingStatusCounts.unchecked || 0} Unchecked</span>
        </div>
      </div>

      <div className="filter-bar">
        <input
          type="text"
          placeholder="Search by company, role, or skill..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="search-input"
        />
        <div className="status-filters">
          {['ALL', 'COMPLETE', 'PARTIAL_RESUME', 'MARKDOWN', 'MISSING'].map(status => (
            <button
              key={status}
              className={`filter-btn ${statusFilter === status ? 'active' : ''}`}
              onClick={() => setStatusFilter(status)}
              style={statusFilter === status && status !== 'ALL' ? { backgroundColor: STATUS_COLORS[status] } : {}}
            >
              {status === 'ALL' ? 'All' : status.replace('_', ' ')}
              <span className="count">{statusCounts[status] || 0}</span>
            </button>
          ))}
        </div>
        <button
          className={`check-all-btn ${checkingAll ? 'checking' : ''}`}
          onClick={handleCheckAll}
          disabled={checkingAll}
        >
          {checkingAll ? 'Starting Batch Check...' : 'Check All Status'}
        </button>
      </div>

      {batchCheckStarted && (
        <div className="batch-check-notice">
          Batch check started. Status will update as jobs are checked.
          Refresh the page to see updated results.
        </div>
      )}

      <div className="posting-legend">
        <span className="legend-title">Posting Status:</span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: POSTING_STATUS_COLORS.ACTIVE }}></span>
          ACTIVE - Still accepting applications
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: POSTING_STATUS_COLORS.CLOSED }}></span>
          CLOSED - Position filled or removed
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: POSTING_STATUS_COLORS.EXPIRED }}></span>
          EXPIRED - Posting has expired
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: POSTING_STATUS_COLORS.ERROR }}></span>
          ERROR - Could not check (blocked/rate-limited)
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: POSTING_STATUS_COLORS.UNKNOWN }}></span>
          UNKNOWN - Not yet checked
        </span>
      </div>

      <div className="job-table-container">
        <table className="job-table">
          <thead>
            <tr>
              {th('#', 'index')}
              {th('Company', 'company')}
              {th('Role', 'role')}
              <th>Salary</th>
              {th('Status', 'status')}
              <th>Posting</th>
              {th('Score', 'score')}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.map(job => {
              const avgScore = getAvgScore(job);
              const postingStatus = getPostingStatus(job);
              const isChecking = checkingJobs[job.index];

              return (
                <tr key={job.index}>
                  <td className="index-cell">{job.index}</td>
                  <td className="company-cell">
                    <strong>{job.company}</strong>
                  </td>
                  <td className="role-cell">{job.role}</td>
                  <td className="salary-cell" title={job.job.salary}>
                    {job.job.salary ? job.job.salary.replace(/\u2013/g, '–') : '—'}
                  </td>
                  <td className="status-cell">
                    <span
                      className="status-badge"
                      style={{ backgroundColor: STATUS_COLORS[job.status] }}
                    >
                      {job.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="posting-status-cell">
                    {postingStatus && postingStatus.status !== 'UNKNOWN' ? (
                      <div className="posting-status">
                        <span
                          className="posting-badge"
                          style={{ backgroundColor: POSTING_STATUS_COLORS[postingStatus.status] }}
                          title={postingStatus.error || `HTTP ${postingStatus.httpStatusCode}`}
                        >
                          {POSTING_STATUS_ICONS[postingStatus.status]} {postingStatus.status}
                        </span>
                        {postingStatus.lastChecked && (
                          <span className="last-checked" title={`Checked: ${postingStatus.lastChecked}${postingStatus.responseTimeMs ? ` (${postingStatus.responseTimeMs}ms)` : ''}`}>
                            {formatRelativeTime(postingStatus.lastChecked)}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="posting-unknown">Not checked</span>
                    )}
                    <button
                      className={`check-status-btn ${isChecking ? 'checking' : ''}`}
                      onClick={() => handleCheckStatus(job.index)}
                      disabled={isChecking}
                      title="Check if job posting is still active"
                    >
                      {isChecking ? '...' : '↻'}
                    </button>
                  </td>
                  <td className="score-cell">
                    {avgScore !== null ? (
                      <span className={`score ${avgScore >= 4.5 ? 'high' : avgScore >= 4.0 ? 'medium' : 'low'}`}>
                        {avgScore.toFixed(1)}
                      </span>
                    ) : (
                      <span className="no-score">—</span>
                    )}
                  </td>
                  <td className="actions-cell">
                    <Link to={`/job/${job.index}`} className="view-btn">View</Link>
                    {job.applyUrl && (
                      <a href={job.applyUrl} target="_blank" rel="noopener noreferrer" className="apply-btn">
                        Apply
                      </a>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {filteredJobs.length === 0 && (
        <div className="no-results">
          No jobs match your filters.
          {search && <button className="clear-search" onClick={() => setSearch('')}>Clear search</button>}
        </div>
      )}
    </div>
  );
}
