import { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { EnrichedJob } from '../types';

import { API_BASE } from '../config';

interface GenerationStatus {
  job_index: number;
  target: 'resume' | 'cover_letter' | 'both';
  status: string;
  provider: string;
  started_at: string | null;
  completed_at: string | null;
  progress_pct: number;
  current_step: string;
  estimated_remaining_s: number | null;
  error: string | null;
  output_dir: string | null;
  rubric_scores: Record<string, number> | null;
}

interface GenerationPreviewProps {
  job: EnrichedJob;
  status: GenerationStatus;
  onAccept: () => void;
  onReject: () => void;
  onBack: () => void;
}

function ScoreBar({ score, label }: { score: number; label: string }) {
  const color = score >= 4.5 ? '#22c55e' : score >= 4.0 ? '#f59e0b' : '#ef4444';
  return (
    <div className="score-bar-item">
      <span className="score-bar-label">{label}</span>
      <div className="score-bar-container">
        <div className="score-bar-fill" style={{ width: `${(score / 5) * 100}%`, backgroundColor: color }} />
      </div>
      <span className="score-bar-value" style={{ color }}>{score.toFixed(1)}</span>
    </div>
  );
}

export function GenerationPreview({ job, status, onAccept, onReject, onBack }: GenerationPreviewProps) {
  const [newResume, setNewResume] = useState<string | null>(null);
  const [newCoverLetter, setNewCoverLetter] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAccepting, setIsAccepting] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [activeTab, setActiveTab] = useState<'resume' | 'cover_letter'>('resume');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status.output_dir && status.status === 'completed') {
      loadGeneratedContent();
    }
  }, [status.output_dir, status.status]);

  const loadGeneratedContent = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.index}/generate/content`);
      if (!response.ok) throw new Error('Failed to load generated content');
      const data = await response.json();
      setNewResume(data.content.resume || 'No resume generated');
      setNewCoverLetter(data.content.cover_letter || 'No cover letter generated');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load generated content');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAccept = useCallback(async () => {
    setIsAccepting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.index}/generate/accept`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to accept');
      onAccept();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to accept');
      setIsAccepting(false);
    }
  }, [job.index, onAccept]);

  const handleReject = useCallback(async () => {
    setIsRejecting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.index}/generate/reject`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to reject');
      onReject();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject');
      setIsRejecting(false);
    }
  }, [job.index, onReject]);

  const rubricScores = status.rubric_scores;

  return (
    <div className="generation-preview">
      <div className="preview-header">
        <button className="back-btn" onClick={onBack}>&larr; Back</button>
        <h2>Generation Complete</h2>
        <span className="preview-job">Job #{job.index}: {job.company}</span>
      </div>

      {error && (
        <div className="preview-error">
          {error}
          <button onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {rubricScores && (
        <div className="rubric-scores">
          <h3>Quality Scores</h3>
          <div className="scores-grid">
            {Object.entries(rubricScores).map(([key, value]) => (
              <ScoreBar key={key} label={key.replace(/_/g, ' ')} score={value} />
            ))}
          </div>
          {rubricScores.final && (
            <div className="total-score">
              <span>Overall:</span>
              <strong>
                {(Object.values(rubricScores.final || rubricScores).reduce((a, b) => a + b, 0) /
                  Object.keys(rubricScores.final || rubricScores).length).toFixed(2)} / 5.0
              </strong>
            </div>
          )}
        </div>
      )}

      <div className="preview-tabs">
        <button
          className={`preview-tab ${activeTab === 'resume' ? 'active' : ''}`}
          onClick={() => setActiveTab('resume')}
        >
          Resume
        </button>
        <button
          className={`preview-tab ${activeTab === 'cover_letter' ? 'active' : ''}`}
          onClick={() => setActiveTab('cover_letter')}
        >
          Cover Letter
        </button>
      </div>

      <div className="preview-content">
        {isLoading ? (
          <div className="preview-loading">Loading generated content...</div>
        ) : (
          <>
            <div className="preview-panel old">
              <div className="panel-header">
                <span className="panel-label">Current</span>
              </div>
              <div className="panel-content">
                <ReactMarkdown>
                  {activeTab === 'resume' ? (job.resumeMd || '*No current resume*') : (job.coverLetterMd || '*No current cover letter*')}
                </ReactMarkdown>
              </div>
            </div>

            <div className="preview-divider">
              <span>vs</span>
            </div>

            <div className="preview-panel new">
              <div className="panel-header">
                <span className="panel-label new-label">New</span>
                <span className="provider-tag">{status.provider}</span>
              </div>
              <div className="panel-content">
                <ReactMarkdown>
                  {activeTab === 'resume' ? (newResume || '*No resume generated*') : (newCoverLetter || '*No cover letter generated*')}
                </ReactMarkdown>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="preview-actions">
        <button
          className="reject-btn"
          onClick={handleReject}
          disabled={isAccepting || isRejecting}
        >
          {isRejecting ? 'Rejecting...' : 'Keep Current'}
        </button>
        <button
          className="accept-btn"
          onClick={handleAccept}
          disabled={isAccepting || isRejecting}
        >
          {isAccepting ? 'Accepting...' : 'Accept New Version'}
        </button>
      </div>

      <div className="preview-footer">
        <p>
          Accepting will replace your current documents with the newly generated versions.
          Rejecting will keep your current documents.
        </p>
      </div>
    </div>
  );
}
