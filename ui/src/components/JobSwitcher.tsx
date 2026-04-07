import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../config';

export interface JobSwitcherProps {
  jobs: Array<{ index: number; name: string }>;
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
}

interface JobsResponse {
  jobs: Array<{ index: number; name: string }>;
}

export function JobSwitcher({ jobs: initialJobs, selectedIndex, onSelect }: JobSwitcherProps) {
  const [jobs, setJobs] = useState<Array<{ index: number; name: string }>>(initialJobs ?? []);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load jobs from API on mount
  useEffect(() => {
    const loadJobs = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/api/jobs`);
        if (!response.ok) {
          throw new Error(`Failed to load jobs: ${response.status}`);
        }
        const data: unknown = await response.json();
        // Handle both flat array [JobInfo, ...] and wrapped {jobs: [...]} formats
        if (Array.isArray(data)) {
          setJobs(data as JobsResponse['jobs']);
        } else if (data && typeof data === 'object' && 'jobs' in data) {
          setJobs((data as { jobs: JobsResponse['jobs'] }).jobs);
        } else {
          throw new Error('Unexpected response format');
        }
      } catch (err) {
        // If API fails, use initial jobs from props
        console.warn('Failed to load jobs from API, using initial jobs:', err);
        setError('Using cached job list');
        setJobs(initialJobs ?? []);
      } finally {
        setIsLoading(false);
      }
    };

    if ((initialJobs ?? []).length === 0) {
      loadJobs();
    }
  }, [initialJobs]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    if (value === 'none' || value === '') {
      onSelect(null);
    } else {
      const index = parseInt(value, 10);
      onSelect(index);
    }
  }, [onSelect]);

  const selectedJobName = selectedIndex !== null
    ? (jobs.find(j => j.index === selectedIndex)?.name ?? null)
    : null;

  return (
    <div className="job-switcher-container">
      <label className="job-switcher-label" htmlFor="job-select">
        Job Context:
      </label>
      <select
        id="job-select"
        className="job-switcher-select"
        value={selectedIndex === null ? 'none' : String(selectedIndex)}
        onChange={handleChange}
        disabled={isLoading}
      >
        <option value="none">No job selected</option>
        {jobs.map(job => {
          const name = job.name ?? '(unnamed)';
          return (
            <option key={job.index} value={job.index}>
              {job.index}: {name.length > 40 ? name.substring(0, 40) + '...' : name}
            </option>
          );
        })}
      </select>
      {isLoading && <span className="job-switcher-loading">Loading...</span>}
      {error && <span className="job-switcher-error">{error}</span>}
      {selectedJobName && (
        <span className="job-switcher-selected" title={selectedJobName}>
          {selectedJobName.length > 30 ? selectedJobName.substring(0, 30) + '...' : selectedJobName}
        </span>
      )}
    </div>
  );
}
