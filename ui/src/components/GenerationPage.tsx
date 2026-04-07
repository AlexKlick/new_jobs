import { useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { GenerationProgress } from './GenerationProgress';
import { GenerationPreview } from './GenerationPreview';
import type { EnrichedJob } from '../types';

import { API_BASE } from '../config';

interface GenerationStatus {
  job_index: number;
  target: 'resume' | 'cover_letter' | 'both';
  status: 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'accepted' | 'rejected' | 'timed_out';
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

interface GenerationPageProps {
  jobs: EnrichedJob[];
}

type ViewState = 'select' | 'progress' | 'preview';

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

export function GenerationPage({ jobs }: GenerationPageProps) {
  const { index } = useParams<{ index: string }>();
  const navigate = useNavigate();

  const [viewState, setViewState] = useState<ViewState>('select');
  const [selectedJobIndex, setSelectedJobIndex] = useState<number | null>(
    index ? parseInt(index, 10) : null
  );
  const [generationStatus, setGenerationStatus] = useState<GenerationStatus | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [genError, setGenError] = useState<string | null>(null);
  const [showRegenDialog, setShowRegenDialog] = useState(false);

  const selectedJob = jobs.find(j => j.index === selectedJobIndex);

  const handleJobSelect = useCallback((jobIndex: number) => {
    setSelectedJobIndex(jobIndex);
  }, []);

  const handleStartGeneration = useCallback(async (target: 'resume' | 'cover_letter' | 'both' = 'both', provider: string = 'minimax') => {
    if (!selectedJob) return;
    setGenError(null);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${selectedJob.index}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, provider }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to start generation');
      setViewState('progress');
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Failed to start generation');
    }
  }, [selectedJob]);

  const handleGenerationComplete = useCallback((status: GenerationStatus) => {
    setGenerationStatus(status);
    setViewState('preview');
  }, []);

  const handleCancel = useCallback(() => {
    setViewState('select');
    setGenerationStatus(null);
  }, []);

  const handleAccept = useCallback(() => {
    // Refresh the jobs list and go back to tracker
    setRefreshKey(k => k + 1);
    navigate('/');
  }, [navigate]);

  const handleReject = useCallback(() => {
    setViewState('select');
    setGenerationStatus(null);
  }, []);

  const handleBack = useCallback(() => {
    setViewState('progress');
  }, []);

  // Show job selector if no job selected
  if (!selectedJob) {
    return (
      <div className="generation-select">
        <h2>Select a Job to Regenerate</h2>
        <div className="gen-job-list">
          {jobs.map(job => (
            <button
              key={job.index}
              className="gen-job-item"
              onClick={() => handleJobSelect(job.index)}
            >
              <span className="gen-job-index">#{job.index}</span>
              <span className="gen-job-company">{job.company}</span>
              <span className="gen-job-role">{job.role}</span>
              <span className={`gen-job-status status-${job.status.toLowerCase()}`}>
                {job.status}
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="generation-page" key={refreshKey}>
      {viewState === 'select' && (
        <div className="generation-select">
          <div className="gen-header">
            <button className="back-btn" onClick={() => navigate('/')}>
              &larr; Back to Tracker
            </button>
            <h2>Regenerate Documents</h2>
          </div>

          <div className="gen-job-card">
            <div className="gen-job-info">
              <h3>{selectedJob.company}</h3>
              <p>{selectedJob.role}</p>
              <span className="job-status-badge">{selectedJob.status}</span>
            </div>
          </div>

          <div className="gen-info-box">
            <p>
              You can regenerate the resume and/or cover letter for this job using an AI provider.
              This typically takes 5-15 minutes.
            </p>
          </div>

          <div className="gen-actions">
            {genError && (
              <div className="gen-error">
                {genError}
                <button onClick={() => setGenError(null)}>dismiss</button>
              </div>
            )}
            <button
              className="gen-start-btn"
              onClick={() => setShowRegenDialog(true)}
            >
              Start Generation
            </button>
          </div>
          {showRegenDialog && selectedJob && (
            <RegenerateDialog
              job={selectedJob}
              onClose={() => setShowRegenDialog(false)}
              onStart={handleStartGeneration}
            />
          )}
        </div>
      )}

      {viewState === 'progress' && selectedJob && (
        <div className="generation-progress-view">
          <GenerationProgress
            job={selectedJob}
            onComplete={handleGenerationComplete}
            onCancel={handleCancel}
          />
        </div>
      )}

      {viewState === 'preview' && selectedJob && generationStatus && (
        <GenerationPreview
          job={selectedJob}
          status={generationStatus}
          onAccept={handleAccept}
          onReject={handleReject}
          onBack={handleBack}
        />
      )}
    </div>
  );
}
