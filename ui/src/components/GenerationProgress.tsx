import { useState, useEffect, useCallback, useRef } from 'react';
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

interface GenerationProgressProps {
  job: EnrichedJob;
  onComplete: (status: GenerationStatus) => void;
  onCancel: () => void;
}

const STATUS_ICONS: Record<string, string> = {
  idle: '○',
  starting: '◐',
  running: '◑',
  completed: '✓',
  failed: '✗',
  accepted: '✓',
  rejected: '✗',
  timed_out: '⏱',
};

const STATUS_COLORS: Record<string, string> = {
  idle: '#64748b',
  starting: '#3b82f6',
  running: '#3b82f6',
  completed: '#22c55e',
  failed: '#ef4444',
  accepted: '#22c55e',
  rejected: '#ef4444',
  timed_out: '#f59e0b',
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

function formatElapsed(startedAt: string | null): string {
  if (!startedAt) return '—';
  const start = new Date(startedAt).getTime();
  const now = Date.now();
  const elapsed = (now - start) / 1000;
  return formatDuration(elapsed);
}

export function GenerationProgress({ job, onComplete, onCancel }: GenerationProgressProps) {
  const [status, setStatus] = useState<GenerationStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${job.index}/generate/status`);
      if (!response.ok) throw new Error('Failed to fetch status');
      const data: GenerationStatus = await response.json();
      setStatus(data);
      setError(null);

      // Check if generation is done
      if (['completed', 'failed', 'accepted', 'rejected', 'timed_out'].includes(data.status)) {
        setIsPolling(false);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        if (['completed', 'failed', 'timed_out'].includes(data.status)) {
          onComplete(data);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch status');
    }
  }, [job.index, onComplete]);

  const startPolling = useCallback(() => {
    setIsPolling(true);
    fetchStatus(); // Immediate fetch
    pollIntervalRef.current = setInterval(fetchStatus, 3000); // Poll every 3s
  }, [fetchStatus]);

  const stopPolling = useCallback(() => {
    setIsPolling(false);
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const handleCancel = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/jobs/${job.index}/generate/cancel`, { method: 'POST' });
      stopPolling();
      onCancel();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel');
    }
  }, [job.index, stopPolling, onCancel]);

  const handleRetry = useCallback(() => {
    setError(null);
    startPolling();
  }, [startPolling]);

  const statusColor = status ? STATUS_COLORS[status.status] : '#64748b';
  const statusIcon = status ? STATUS_ICONS[status.status] : '○';

  return (
    <div className="generation-progress">
      <div className="progress-header">
        <h3>Generation Progress</h3>
        <span className="progress-job">
          Job #{job.index}: {job.company}
        </span>
      </div>

      <div className="progress-status-bar">
        <div className="status-indicator" style={{ color: statusColor }}>
          <span className="status-icon">{statusIcon}</span>
          <span className="status-text">
            {status ? status.status.replace('_', ' ').toUpperCase() : 'LOADING...'}
          </span>
        </div>

        <div className="provider-badge">
          {status?.provider || '—'}
        </div>
      </div>

      <div className="progress-bar-container">
        <div
          className="progress-bar-fill"
          style={{
            width: `${status?.progress_pct || 0}%`,
            backgroundColor: statusColor,
          }}
        />
      </div>

      <div className="progress-details">
        <div className="progress-step">
          <span className="step-label">Current step:</span>
          <span className="step-value">{status?.current_step || 'Initializing...'}</span>
        </div>

        <div className="progress-stats">
          <div className="stat-item">
            <span className="stat-label">Progress</span>
            <span className="stat-value">{status?.progress_pct || 0}%</span>
          </div>

          <div className="stat-item">
            <span className="stat-label">Elapsed</span>
            <span className="stat-value">{formatElapsed(status?.started_at || null)}</span>
          </div>

          {status?.estimated_remaining_s !== null && status?.estimated_remaining_s !== undefined && (
            <div className="stat-item">
              <span className="stat-label">ETA</span>
              <span className="stat-value">{formatDuration(status.estimated_remaining_s)}</span>
            </div>
          )}

          <div className="stat-item">
            <span className="stat-label">Target</span>
            <span className="stat-value">
              {status?.target === 'both' ? 'Resume + CL' : status?.target === 'resume' ? 'Resume' : 'Cover Letter'}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="progress-error">
          <span className="error-icon">!</span>
          <span className="error-message">{error}</span>
          <button className="retry-btn" onClick={handleRetry}>Retry</button>
        </div>
      )}

      {status?.status === 'failed' && status.error && (
        <div className="progress-error">
          <span className="error-icon">✗</span>
          <div className="error-content">
            <span className="error-title">Generation Failed</span>
            <pre className="error-details">{status.error}</pre>
          </div>
          <button className="retry-btn" onClick={handleRetry}>Retry</button>
        </div>
      )}

      {status?.status === 'timed_out' && (
        <div className="progress-error">
          <span className="error-icon">⏱</span>
          <div className="error-content">
            <span className="error-title">Generation Timed Out</span>
            <span className="error-message">The operation took longer than 30 minutes.</span>
          </div>
          <button className="retry-btn" onClick={handleRetry}>Retry</button>
        </div>
      )}

      {status?.status === 'completed' && (
        <div className="progress-success">
          <span className="success-icon">✓</span>
          <span className="success-message">Generation complete! Review the results.</span>
        </div>
      )}

      {isPolling && status?.status !== 'completed' && (
        <div className="progress-actions">
          <button className="cancel-btn" onClick={handleCancel}>
            Cancel Generation
          </button>
        </div>
      )}

      <div className="progress-footer">
        <span className="polling-indicator">
          {isPolling ? 'Live updates active' : 'Waiting...'}
        </span>
      </div>
    </div>
  );
}
