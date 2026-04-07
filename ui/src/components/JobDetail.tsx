import { Link } from 'react-router-dom';
import { useState, useCallback, useEffect } from 'react';
import type { EnrichedJob, ResearchClaim, InterviewQuestion, CompanyResearch } from '../types';
import { apiUrl } from '../config';

interface JobDetailProps {
  job: EnrichedJob;
  onBack: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  COMPLETE: '#22c55e',
  PARTIAL_RESUME: '#f59e0b',
  MARKDOWN: '#3b82f6',
  MISSING: '#ef4444',
};

type GenerationTarget = 'resume' | 'cover_letter' | 'both';

interface RegenerateDialogProps {
  job: EnrichedJob;
  onClose: () => void;
  onStart: (target: GenerationTarget, provider: string) => void;
}

function RegenerateDialog({ job, onClose, onStart }: RegenerateDialogProps) {
  const [target, setTarget] = useState<GenerationTarget>('both');
  const [provider, setProvider] = useState('minimax');

  const handleStart = () => {
    onStart(target, provider);
    onClose();
  };

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content" onClick={e => e.stopPropagation()}>
        <h2>Regenerate Documents</h2>
        <p>Job #{job.index}: {job.company} — {job.role}</p>

        <div className="dialog-field">
          <label htmlFor="gen-target">What to regenerate:</label>
          <select
            id="gen-target"
            value={target}
            onChange={e => setTarget(e.target.value as GenerationTarget)}
          >
            <option value="both">Resume + Cover Letter</option>
            <option value="resume">Resume only</option>
            <option value="cover_letter">Cover Letter only</option>
          </select>
        </div>

        <div className="dialog-field">
          <label htmlFor="gen-provider">LLM Provider:</label>
          <select
            id="gen-provider"
            value={provider}
            onChange={e => setProvider(e.target.value)}
          >
            <option value="minimax">MiniMax (faster)</option>
            <option value="zai">Z.AI (GLM-5, higher quality)</option>
          </select>
        </div>

        <div className="dialog-info">
          <p>
            <strong>Note:</strong> Generation typically takes 5-15 minutes.
            You will see a progress indicator once started.
          </p>
        </div>

        <div className="dialog-actions">
          <button className="btn-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleStart}>Start Generation</button>
        </div>
      </div>
    </div>
  );
}

function computeCompanyKey(name: string): string {
  return name.toLowerCase().replace(/[^\w\s-]/g, '').replace(/[\s_]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || 'unknown';
}

export function JobDetail({ job, onBack }: JobDetailProps) {
  const [activeTab, setActiveTab] = useState<'details' | 'research'>('details');
  const [showRegenDialog, setShowRegenDialog] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // Research state
  const [research, setResearch] = useState<CompanyResearch | null>(null);
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState<string | null>(null);
  const [researchRefreshing, setResearchRefreshing] = useState(false);

  const companyKey = computeCompanyKey(job.company);

  const fetchResearch = useCallback(async () => {
    setResearchLoading(true);
    setResearchError(null);
    try {
      const resp = await fetch(apiUrl(`/api/research/company/${companyKey}`));
      if (resp.ok) {
        const data = await resp.json();
        setResearch(data);
      } else {
        setResearch(null);
      }
    } catch { setResearchError('Failed to load research'); }
    finally { setResearchLoading(false); }
  }, [companyKey]);

  useEffect(() => {
    if (activeTab === 'research') fetchResearch();
  }, [activeTab, fetchResearch]);

  const handleRefresh = async () => {
    setResearchRefreshing(true);
    setResearchError(null);
    try {
      const resp = await fetch(apiUrl(`/api/research/company/${companyKey}/refresh`), { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Refresh failed');
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const sr = await fetch(apiUrl(`/api/research/refresh/${data.refresh_id}`));
          const sd = await sr.json();
          if (sd.status === 'completed') { clearInterval(poll); setResearchRefreshing(false); fetchResearch(); }
          else if (sd.status === 'failed') { clearInterval(poll); setResearchRefreshing(false); setResearchError(sd.error_message || 'Refresh failed'); }
        } catch { clearInterval(poll); setResearchRefreshing(false); }
      }, 2000);
    } catch (err) {
      setResearchError(err instanceof Error ? err.message : 'Refresh failed');
      setResearchRefreshing(false);
    }
  };

  const avgScore = job.rubricScores?.final
    ? Object.values(job.rubricScores.final).reduce((a, b) => a + b, 0) / Object.keys(job.rubricScores.final).length
    : null;

  const handleStartGeneration = useCallback(async (target: GenerationTarget, provider: string) => {
    setIsGenerating(true);
    setGenError(null);
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.index}/generate`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, provider }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to start generation');
      window.location.hash = `generation/${job.index}`;
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Failed to start generation');
      setIsGenerating(false);
    }
  }, [job.index]);

  return (
    <div className="job-detail">
      {showRegenDialog && (
        <RegenerateDialog job={job} onClose={() => setShowRegenDialog(false)} onStart={handleStartGeneration} />
      )}

      <button onClick={onBack} className="back-btn">&larr; Back to Tracker</button>

      <div className="detail-tabs">
        <button className={`detail-tab ${activeTab === 'details' ? 'active' : ''}`} onClick={() => setActiveTab('details')}>Details</button>
        <button className={`detail-tab ${activeTab === 'research' ? 'active' : ''}`} onClick={() => setActiveTab('research')}>Research</button>
      </div>

      {activeTab === 'research' ? (
        <div className="research-inline-panel">
          {researchError && <div className="error-banner">{researchError}<button onClick={() => setResearchError(null)}>dismiss</button></div>}
          {researchLoading && !research ? (
            <div className="research-loading">Loading company research...</div>
          ) : !research ? (
            <div className="research-empty">
              <p>No research yet for {job.company}.</p>
              <button className="action-btn primary" onClick={handleRefresh} disabled={researchRefreshing}>
                {researchRefreshing ? 'Refreshing...' : 'Refresh Research'}
              </button>
            </div>
          ) : (
            <>
              <div className="research-inline-header">
                <h3>Company Research: {research.company_name}</h3>
                <button className="action-btn" onClick={handleRefresh} disabled={researchRefreshing}>
                  {researchRefreshing ? 'Refreshing...' : 'Refresh Research'}
                </button>
              </div>
              {research.is_stale && <span className="stale-badge stale">Stale — {research.stale_days}d ago</span>}
              {research.claims.length > 0 && (
                <div className="research-section">
                  <h4>Claims</h4>
                  {research.claims.map((c: ResearchClaim) => (
                    <div key={c.claim_id} className="research-claim-card">
                      <div className="claim-text">{c.claim_text}</div>
                      <div className="claim-meta">
                        <a href={c.source_url} target="_blank" rel="noopener noreferrer" className="claim-source">
                          {c.source_url.replace(/^https?:\/\//, '').split('/')[0]}
                        </a>
                        <span className="claim-time">{c.collected_at}</span>
                        <span className={`claim-confidence confidence-${c.confidence}`}>{c.confidence}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {research.questions.length > 0 && (
                <div className="research-section">
                  <h4>Interview Questions</h4>
                  {research.questions.map((q: InterviewQuestion) => (
                    <div key={q.question_id} className="research-question-item">
                      <div className="question-text">{q.question_text}</div>
                      <div className="question-meta">
                        <a href={q.source_url} target="_blank" rel="noopener noreferrer" className="claim-source">
                          {q.source_url.replace(/^https?:\/\//, '').split('/')[0]}
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      ) : (
      <>
      <div className="detail-header">
        <h1>{job.job.heading}</h1>
        <span className="status-badge large" style={{ backgroundColor: STATUS_COLORS[job.status] }}>{job.status}</span>
      </div>

      {genError && (
        <div className="error-banner">
          {genError}
          <button onClick={() => setGenError(null)}>dismiss</button>
        </div>
      )}

      {isGenerating && (
        <div className="generating-banner">
          Generation started. Check progress in the Generation Progress tab.
          <button onClick={() => setIsGenerating(false)}>dismiss</button>
        </div>
      )}

      <div className="detail-meta">
        <div className="meta-item"><strong>Company</strong><span>{job.company}</span></div>
        <div className="meta-item"><strong>Role</strong><span>{job.role}</span></div>
        <div className="meta-item"><strong>Salary</strong><span>{job.job.salary}</span></div>
        <div className="meta-item"><strong>Remote</strong><span>{job.job.remote}</span></div>
        <div className="meta-item"><strong>Experience</strong><span>{job.job.experience}</span></div>
        {avgScore !== null && (
          <div className="meta-item">
            <strong>Quality Score</strong>
            <span className={`score ${avgScore >= 4.5 ? 'high' : avgScore >= 4.0 ? 'medium' : 'low'}`}>
              {avgScore.toFixed(2)} / 5.0
            </span>
          </div>
        )}
      </div>

      <div className="detail-section">
        <h3>Key Skills</h3>
        <div className="skills-list">
          {job.job.key_skills.map((skill, i) => (
            <span key={i} className="skill-tag">{skill}</span>
          ))}
        </div>
      </div>

      <div className="detail-section">
        <h3>Why This Role Fits</h3>
        <p className="why-fit">{job.job.why_fit}</p>
      </div>

      <div className="detail-section">
        <h3>Company Summary</h3>
        <p>{job.job.summary}</p>
      </div>

      <div className="detail-actions">
        {job.applyUrl && (
          <a href={job.applyUrl} target="_blank" rel="noopener noreferrer" className="action-btn primary">Apply Now</a>
        )}
        {job.resumeMd && (
          <Link to={`/documents/${job.index}?doc=resume`} className="action-btn">View Resume</Link>
        )}
        {job.coverLetterMd && (
          <Link to={`/documents/${job.index}?doc=cover_letter`} className="action-btn">View Cover Letter</Link>
        )}
        {job.rubricScores && (
          <Link to={`/quality/${job.index}`} className="action-btn">View Quality Analysis</Link>
        )}
        <button className="action-btn regenerate-btn" onClick={() => setShowRegenDialog(true)}>Regenerate</button>
      </div>

      {job.evaluation && (
        <div className="detail-section evaluation-summary">
          <h3>Evaluation Summary</h3>
          <div className={`verdict ${job.evaluation.verdict.toLowerCase()}`}>{job.evaluation.verdict}</div>
          <div className="checklist-summary">
            {job.evaluation.human_review_checklist.slice(0, 3).map((item, i) => (
              <div key={i} className={`checklist-item ${item.status.toLowerCase()}`}>
                <span className="check-status">{item.status === 'PASS' ? '✓' : item.status === 'FAIL' ? '✗' : '!'}</span>
                <span>{item.item}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}
