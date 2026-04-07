import { useState, useEffect, useCallback } from 'react';
import type {
  SearchPreference,
  SearchRunSummary,
  JobCandidate,
  SearchRunStatus,
} from '../types';
import { API_BASE } from '../config';
import { EmptyState, LoadingState } from './PageState';

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusBadgeClass(status: SearchRunStatus): string {
  return `search-status-badge ${status}`;
}

function sourceLabel(source: string): string {
  return source === 'generic' ? 'generic (deferred)' : source;
}

// ── Create Preference Dialog ───────────────────────────────────────────────────

interface CreatePrefDialogProps {
  onClose: () => void;
  onCreated: (pref: SearchPreference) => void;
}

function CreatePrefDialog({ onClose, onCreated }: CreatePrefDialogProps) {
  const [label, setLabel] = useState('');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState('');
  const [locations, setLocations] = useState<string[]>([]);
  const [locationInput, setLocationInput] = useState('');
  const [sources, setSources] = useState<Set<string>>(new Set(['greenhouse', 'lever']));
  const [archetype, setArchetype] = useState<'new_grad' | 'experienced'>('new_grad');
  const [isSaving, setIsSaving] = useState(false);

  const addKeyword = useCallback(() => {
    const trimmed = keywordInput.trim();
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords(prev => [...prev, trimmed]);
      setKeywordInput('');
    }
  }, [keywordInput, keywords]);

  const removeKeyword = useCallback((kw: string) => {
    setKeywords(prev => prev.filter(k => k !== kw));
  }, []);

  const addLocation = useCallback(() => {
    const trimmed = locationInput.trim();
    if (trimmed && !locations.includes(trimmed)) {
      setLocations(prev => [...prev, trimmed]);
      setLocationInput('');
    }
  }, [locationInput, locations]);

  const removeLocation = useCallback((loc: string) => {
    setLocations(prev => prev.filter(l => l !== loc));
  }, []);

  const toggleSource = useCallback((src: string) => {
    setSources(prev => {
      const next = new Set(prev);
      if (next.has(src)) next.delete(src);
      else next.add(src);
      return next;
    });
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!label.trim() || keywords.length === 0) return;
    setIsSaving(true);
    try {
      const resp = await fetch(`${API_BASE}/api/search/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: label.trim(),
          archetype,
          keywords,
          locations,
          sources: Array.from(sources),
          experience_level: null,
          remote_policy: null,
          salary_min: null,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        onCreated(data);
        onClose();
      }
    } finally {
      setIsSaving(false);
    }
  }, [label, archetype, keywords, locations, sources, onCreated, onClose]);

  return (
    <div className="create-pref-overlay" onClick={onClose}>
      <div className="create-pref-dialog" onClick={e => e.stopPropagation()}>
        <h3>Create Search Preference</h3>

        <div className="pref-form-field">
          <label>Preset Name</label>
          <input
            type="text"
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="e.g. SWE Jobs Denver"
          />
        </div>

        <div className="pref-form-field">
          <label>Profile Archetype</label>
          <div className="source-checkboxes">
            <label className="source-checkbox">
              <input
                type="radio"
                name="archetype"
                checked={archetype === 'new_grad'}
                onChange={() => setArchetype('new_grad')}
              />
              New Graduate
            </label>
            <label className="source-checkbox">
              <input
                type="radio"
                name="archetype"
                checked={archetype === 'experienced'}
                onChange={() => setArchetype('experienced')}
              />
              Experienced
            </label>
          </div>
        </div>

        <div className="pref-form-field">
          <label>Keywords / Roles</label>
          <div className="chip-input">
            {keywords.map(kw => (
              <span key={kw} className="chip">
                {kw}
                <button className="chip-remove" onClick={() => removeKeyword(kw)}>×</button>
              </span>
            ))}
            <input
              type="text"
              value={keywordInput}
              onChange={e => setKeywordInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addKeyword(); } }}
              placeholder="Add keyword..."
            />
          </div>
        </div>

        <div className="pref-form-field">
          <label>Locations (optional)</label>
          <div className="chip-input">
            {locations.map(loc => (
              <span key={loc} className="chip">
                {loc}
                <button className="chip-remove" onClick={() => removeLocation(loc)}>×</button>
              </span>
            ))}
            <input
              type="text"
              value={locationInput}
              onChange={e => setLocationInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addLocation(); } }}
              placeholder="Add location..."
            />
          </div>
        </div>

        <div className="pref-form-field">
          <label>Job Sources</label>
          <div className="source-checkboxes">
            <label className="source-checkbox">
              <input
                type="checkbox"
                checked={sources.has('greenhouse')}
                onChange={() => toggleSource('greenhouse')}
              />
              Greenhouse
            </label>
            <label className="source-checkbox">
              <input
                type="checkbox"
                checked={sources.has('lever')}
                onChange={() => toggleSource('lever')}
              />
              Lever
            </label>
            <label className="source-checkbox">
              <input
                type="checkbox"
                checked={sources.has('generic')}
                onChange={() => toggleSource('generic')}
                disabled
              />
              Generic (coming later)
            </label>
          </div>
        </div>

        <div className="dialog-actions">
          <button className="btn-dialog-cancel" onClick={onClose}>Cancel</button>
          <button
            className="btn-dialog-create"
            onClick={handleSubmit}
            disabled={!label.trim() || keywords.length === 0 || isSaving}
          >
            {isSaving ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Search Page ────────────────────────────────────────────────────────────────

export function SearchPage() {
  const [preferences, setPreferences] = useState<SearchPreference[]>([]);
  const [runs, setRuns] = useState<SearchRunSummary[]>([]);
  const [selectedPrefId, setSelectedPrefId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<JobCandidate[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  const selectedPref = preferences.find(p => p.preference_id === selectedPrefId) || null;
  const selectedRun = runs.find(r => r.run_id === selectedRunId) || null;

  // Load preferences and runs on mount
  useEffect(() => {
    loadPreferences();
    loadRuns();
  }, []);

  const loadPreferences = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/preferences`);
      if (resp.ok) {
        const data = await resp.json();
        setPreferences(data);
      }
    } catch {
      // API not available yet
    }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/runs`);
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data);
      }
    } catch {
      // API not available yet
    }
  }, []);

  const loadRunDetail = useCallback(async (runId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/runs/${runId}`);
      if (resp.ok) {
        const data = await resp.json();
        setCandidates(data.candidates || []);
      }
    } catch {
      setCandidates([]);
    }
  }, []);

  // When selecting a run, load its candidates
  useEffect(() => {
    if (selectedRunId) {
      loadRunDetail(selectedRunId);
    } else {
      setCandidates([]);
    }
  }, [selectedRunId, loadRunDetail]);

  const handleRunSearch = useCallback(async () => {
    if (!selectedPrefId) return;
    setIsRunning(true);
    try {
      const resp = await fetch(`${API_BASE}/api/search/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preference_id: selectedPrefId }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSelectedRunId(data.run_id);
        await loadRuns();
        // Poll for completion
        pollRunStatus(data.run_id);
      }
    } finally {
      setIsRunning(false);
    }
  }, [selectedPrefId, loadRuns]);

  const pollRunStatus = useCallback(async (runId: string) => {
    const poll = async () => {
      const resp = await fetch(`${API_BASE}/api/search/runs/${runId}`);
      if (resp.ok) {
        const data: SearchRunSummary = await resp.json();
        if (data.status === 'completed' || data.status === 'failed') {
          await loadRuns();
          await loadRunDetail(runId);
          return;
        }
      }
      // Poll again after 2 seconds
      setTimeout(poll, 2000);
    };
    poll();
  }, [loadRuns, loadRunDetail]);

  const handleSelectRun = useCallback((runId: string) => {
    setSelectedRunId(runId);
  }, []);

  const handleIngest = useCallback(async (candidateId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/candidates/${candidateId}/ingest`, {
        method: 'POST',
      });
      if (resp.ok) {
        setCandidates(prev =>
          prev.map(c => c.candidate_id === candidateId ? { ...c, ingested: true } : c)
        );
      }
    } catch {
      // silently fail
    }
  }, []);

  return (
    <div className="search-page">
      {/* Left Rail: preferences + run history */}
      <div className="search-left-rail">
        <div>
          <h3>Saved Preferences</h3>
          {preferences.map(pref => (
            <button
              key={pref.preference_id}
              className={`search-pref-item ${selectedPrefId === pref.preference_id ? 'active' : ''}`}
              onClick={() => setSelectedPrefId(pref.preference_id)}
            >
              <span className="search-pref-label">{pref.label}</span>
              <span className="search-pref-meta">
                {pref.keywords.join(', ')}
              </span>
              <div className="search-pref-tags">
                {pref.sources.map(src => (
                  <span key={src} className="search-tag">{sourceLabel(src)}</span>
                ))}
                {pref.locations.map(loc => (
                  <span key={loc} className="search-tag">{loc}</span>
                ))}
              </div>
            </button>
          ))}
          <button className="btn-create-pref" onClick={() => setShowCreate(true)}>
            + New Preference
          </button>
        </div>

        <div style={{ marginTop: 'var(--space-4)' }}>
          <h3>Run History</h3>
          {runs.length === 0 ? (
            <div className="search-pref-meta" style={{ padding: 'var(--space-2) 0' }}>
              No runs yet. Select a preference and run a search.
            </div>
          ) : (
            <div className="run-history-list">
              {runs.map(run => (
                <button
                  key={run.run_id}
                  className={`run-history-item ${selectedRunId === run.run_id ? 'active' : ''}`}
                  onClick={() => handleSelectRun(run.run_id)}
                >
                  <span className={statusBadgeClass(run.status)}>{run.status}</span>
                  <span className="run-history-label">
                    {run.preference_label || 'Ad-hoc search'}
                  </span>
                  <span className="run-history-time">{formatTime(run.started_at)}</span>
                  <span className="run-history-count">{run.total_candidates}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {selectedPref && (
          <div style={{ marginTop: 'var(--space-4)' }}>
            <button
              className="btn-run-search"
              onClick={handleRunSearch}
              disabled={isRunning}
            >
              {isRunning ? 'Running...' : 'Run Search'}
            </button>
          </div>
        )}
      </div>

      {/* Main: run summary + candidates */}
      <div className="search-main">
        {!selectedRun ? (
          <EmptyState
            icon="?"
            title="No search selected"
            description="Select a saved preference and run a search, or pick a run from history to review results."
          />
        ) : (
          <>
            <div className="search-run-header">
              <h2>{selectedRun.preference_label || 'Ad-hoc Search'}</h2>
              <span className={statusBadgeClass(selectedRun.status)}>{selectedRun.status}</span>
            </div>

            <div className="run-stats">
              <div className="run-stat">
                <span className="run-stat-value">{selectedRun.total_candidates}</span>
                <span className="run-stat-label">Total</span>
              </div>
              <div className="run-stat">
                <span className="run-stat-value new">{selectedRun.new_candidates}</span>
                <span className="run-stat-label">New</span>
              </div>
              <div className="run-stat">
                <span className="run-stat-value dup">{selectedRun.duplicate_count}</span>
                <span className="run-stat-label">Duplicates</span>
              </div>
            </div>

            {selectedRun.error_message && (
              <div style={{
                padding: 'var(--space-3)',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid var(--danger)',
                borderRadius: '0.375rem',
                marginBottom: 'var(--space-4)',
                color: 'var(--danger)',
                fontSize: '0.875rem',
              }}>
                Error: {selectedRun.error_message}
              </div>
            )}

            <div className="candidate-list">
              {candidates.map(candidate => (
                <div
                  key={candidate.candidate_id}
                  className={`candidate-card ${candidate.is_duplicate ? 'is-duplicate' : ''}`}
                >
                  <div className="candidate-info">
                    <div className="candidate-company">{candidate.company}</div>
                    <div className="candidate-role">{candidate.role}</div>
                    <div className="candidate-meta">
                      {candidate.location && <span>{candidate.location}</span>}
                      {candidate.salary && <span>{candidate.salary}</span>}
                      {candidate.remote && <span>{candidate.remote}</span>}
                      <span className={`candidate-badge ${candidate.source}`}>{candidate.source}</span>
                      {candidate.is_duplicate && (
                        <span className="candidate-badge duplicate">duplicate</span>
                      )}
                    </div>
                  </div>
                  <div className="candidate-actions">
                    {candidate.apply_url && (
                      <a
                        href={candidate.apply_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn-ingest"
                      >
                        Apply
                      </a>
                    )}
                    {!candidate.ingested && !candidate.is_duplicate && (
                      <button
                        className="btn-ingest"
                        onClick={() => handleIngest(candidate.candidate_id)}
                      >
                        + Ingest
                      </button>
                    )}
                    {candidate.ingested && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--success)' }}>
                        Ingested
                      </span>
                    )}
                  </div>
                </div>
              ))}
              {candidates.length === 0 && selectedRun.status === 'running' && (
                <LoadingState message="Gathering candidates..." />
              )}
              {candidates.length === 0 && selectedRun.status === 'completed' && (
                <EmptyState
                  title="No candidates found"
                  description="This search did not return any results. Try adjusting your keywords or sources."
                />
              )}
            </div>
          </>
        )}
      </div>

      {showCreate && (
        <CreatePrefDialog
          onClose={() => setShowCreate(false)}
          onCreated={pref => {
            setPreferences(prev => [...prev, pref]);
            setSelectedPrefId(pref.preference_id);
          }}
        />
      )}
    </div>
  );
}
