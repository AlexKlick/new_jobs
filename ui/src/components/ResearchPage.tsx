import { useState, useEffect, useCallback } from 'react';
import type {
  ResearchCompany,
  ResearchClaim,
  InterviewQuestion,
  ResearchSnapshotSummary,
  RefreshStatus,
} from '../types';
import { API_BASE } from '../config';
import { EmptyState, LoadingState, ErrorState } from './PageState';

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatRelativeTime(iso: string): string {
  if (!iso) return '';
  try {
    const now = new Date();
    const then = new Date(iso);
    const diffMs = now.getTime() - then.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays > 365) return `${Math.floor(diffDays / 365)}y ago`;
    if (diffDays > 30) return `${diffDays}d ago`;
    if (diffDays > 0) return `${diffDays}d ago`;
    return 'just now';
  } catch {
    return iso;
  }
}

function staleClass(days: number | null): string {
  if (days === null) return '';
  if (days >= 30) return 'very-stale';
  if (days >= 7) return 'stale';
  return '';
}

function staleLabel(days: number | null): string {
  if (days === null) return '';
  if (days >= 30) return `Very stale - ${days}d ago`;
  if (days >= 7) return `Stale - ${days}d ago`;
  return '';
}

// ── Stale Badge ────────────────────────────────────────────────────────────

interface StaleBadgeProps {
  days: number | null;
}

function StaleBadge({ days }: StaleBadgeProps) {
  const cls = staleClass(days);
  if (!cls) return null;
  return (
    <span className={`stale-badge ${cls}`}>
      {staleLabel(days)}
    </span>
  );
}

// ── Claim Card ──────────────────────────────────────────────────────────────

interface ClaimCardProps {
  claim: ResearchClaim;
}

function ClaimCard({ claim }: ClaimCardProps) {
  return (
    <div className="research-claim-card">
      <div className="claim-text">{claim.claim_text}</div>
      <div className="claim-meta">
        <a
          href={claim.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="claim-source"
          title={claim.source_url}
        >
          {claim.source_url.replace(/^https?:\/\//, '').split('/')[0]}
        </a>
        <span className="claim-time">{formatRelativeTime(claim.collected_at)}</span>
        <span className={`claim-confidence confidence-${claim.confidence}`}>
          {claim.confidence} confidence
        </span>
        {claim.themes.length > 0 && (
          <div className="claim-themes">
            {claim.themes.map(t => (
              <span key={t} className="theme-tag">{t}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Interview Question Item ──────────────────────────────────────────────────

interface QuestionItemProps {
  question: InterviewQuestion;
}

function QuestionItem({ question }: QuestionItemProps) {
  return (
    <div className="research-question-item">
      <div className="question-text">{question.question_text}</div>
      <div className="question-meta">
        <a
          href={question.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="claim-source"
          title={question.source_url}
        >
          {question.source_url.replace(/^https?:\/\//, '').split('/')[0]}
        </a>
        {question.role_applicability.length > 0 && (
          <div className="question-roles">
            {question.role_applicability.map(r => (
              <span key={r} className="role-chip">{r}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Refresh Button ────────────────────────────────────────────────────────────

interface RefreshButtonProps {
  onClick: () => void;
  disabled: boolean;
  loading: boolean;
  progress?: RefreshStatus | null;
}

function RefreshButton({ onClick, disabled, loading, progress }: RefreshButtonProps) {
  return (
    <button
      className="btn-refresh"
      onClick={onClick}
      disabled={disabled}
    >
      {loading ? (
        <>
          <span className="refresh-spinner" />
          {progress ? `Refreshing (${progress.sources_completed}/${progress.sources_total})...` : 'Refreshing...'}
        </>
      ) : (
        'Refresh Research'
      )}
    </button>
  );
}

// ── Research Page ────────────────────────────────────────────────────────────

export function ResearchPage() {
  const [companies, setCompanies] = useState<ResearchCompany[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [activeTab, setActiveTab] = useState<'claims' | 'questions'>('claims');
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load companies on mount
  useEffect(() => {
    loadCompanies();
  }, []);

  const loadCompanies = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/research/companies`);
      if (resp.ok) {
        const data: ResearchCompany[] = await resp.json();
        setCompanies(data);
      }
    } catch {
      setCompanies([]);
    }
  }, []);

  const loadDetail = useCallback(async (companyKey: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/api/research/company/${companyKey}`);
      if (resp.ok) {
        const data = await resp.json();
        setDetail(data);
        setSelectedKey(companyKey);
      } else {
        setError('Company not found');
        setDetail(null);
      }
    } catch {
      setError('Failed to load research');
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll refresh status
  useEffect(() => {
    if (!refreshStatus || refreshStatus.status === 'completed' || refreshStatus.status === 'failed') {
      return;
    }
    const pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/research/refresh/${refreshStatus.refresh_id}`);
        if (resp.ok) {
          const data: RefreshStatus = await resp.json();
          setRefreshStatus(data);
          if (data.status === 'completed' && selectedKey) {
            loadDetail(selectedKey);
          }
        }
      } catch {
        // Polling error - stop polling
      }
    }, 2000);
    return () => clearInterval(pollInterval);
  }, [refreshStatus]);

  const handleRefresh = useCallback(async () => {
    if (!selectedKey) return;
    try {
      const resp = await fetch(
        `${API_BASE}/api/research/company/${selectedKey}/refresh`,
        { method: 'POST' },
      );
      if (resp.ok) {
        const data = await resp.json();
        setRefreshStatus(data);
      }
    } catch {
      setError('Failed to start refresh');
    }
  }, [selectedKey]);

  return (
    <div className="research-page">
      {/* Left Rail */}
      <div className="research-left-rail">
        <div className="rail-header">
          <h3>Companies</h3>
          <div className="rail-search">
            <input
              type="text"
              placeholder="Filter companies..."
              className="company-filter-input"
            />
          </div>
        </div>
        <div className="company-list">
          {companies.length === 0 ? (
            <div className="research-empty-hint">
              No companies researched yet. Click Refresh Research to get started.
            </div>
          ) : (
            companies.map(c => (
              <button
                key={c.company_key}
                className={`company-row ${selectedKey === c.company_key ? 'active' : ''}`}
                onClick={() => loadDetail(c.company_key)}
              >
                <span className="company-name">{c.company_name}</span>
                <div className="company-meta">
                  {c.last_refreshed_at && (
                    <span className="company-time">{formatRelativeTime(c.last_refreshed_at)}</span>
                  )}
                  <StaleBadge days={c.is_stale ? 7 : null} />
                  <span className="company-counts">
                    {c.claim_count} claims, {c.question_count} questions
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main Panel */}
      <div className="research-main">
        {!selectedKey ? (
          <EmptyState
            icon="?"
            title="No company selected"
            description="Select a company from the left panel to view research data."
          />
        ) : loading ? (
          <LoadingState message="Loading research..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => { if (selectedKey) loadDetail(selectedKey); }} />
        ) : detail ? (
          <>
            <div className="research-header">
              <div className="header-info">
                <h2>{detail.company_name}</h2>
                <div className="header-meta">
                  {detail.last_refreshed_at && (
                    <span className="last-refreshed">
                      Last refreshed {formatRelativeTime(detail.last_refreshed_at)}
                    </span>
                  )}
                  <StaleBadge days={detail.stale_days} />
                </div>
              </div>
              <RefreshButton
                onClick={handleRefresh}
                disabled={!!refreshStatus && refreshStatus.status !== 'completed' && refreshStatus.status !== 'failed'}
                loading={!!refreshStatus && refreshStatus.status === 'running'}
                progress={refreshStatus}
              />
            </div>

            {/* Tab bar */}
            <div className="research-tabs">
              <button
                className={`research-tab ${activeTab === 'claims' ? 'active' : ''}`}
                onClick={() => setActiveTab('claims')}
              >
                Claims ({detail.claims?.length || 0})
              </button>
              <button
                className={`research-tab ${activeTab === 'questions' ? 'active' : ''}`}
                onClick={() => setActiveTab('questions')}
              >
                Questions ({detail.questions?.length || 0})
              </button>
            </div>

            {/* Tab content */}
            <div className="research-tab-content">
              {activeTab === 'claims' ? (
                detail.claims?.length > 0 ? (
                  <div className="claims-list">
                    {detail.claims.map((claim: ResearchClaim) => (
                      <ClaimCard key={claim.claim_id} claim={claim} />
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No claims collected yet" description="Refresh research to gather company claims." />
                )
              ) : (
                detail.questions?.length > 0 ? (
                  <div className="questions-list">
                    {detail.questions.map((q: InterviewQuestion) => (
                      <QuestionItem key={q.question_id} question={q} />
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No interview questions collected yet" description="Refresh research to gather interview questions." />
                )
              )}
            </div>

            {/* Snapshots sidebar */}
            {detail.snapshots && detail.snapshots.length > 0 && (
              <div className="research-sidebar">
                <h4>Snapshot History</h4>
                <div className="snapshot-list">
                  {detail.snapshots.map((s: ResearchSnapshotSummary) => (
                    <div key={s.snapshot_id} className="snapshot-item">
                      <span className="snapshot-time">{formatRelativeTime(s.collected_at)}</span>
                      <span className="snapshot-counts">
                        {s.claim_count} claims, {s.question_count} questions
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <EmptyState title="Company not found" description="This company may have been removed." />
        )}
      </div>
    </div>
  );
}
