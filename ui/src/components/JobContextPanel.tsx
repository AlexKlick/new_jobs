import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

interface JobContextData {
  resume: string;
  cover_letter: string;
  job_name: string;
}

interface JobContextPanelProps {
  jobIndex: number | null;
}

export function JobContextPanel({ jobIndex }: JobContextPanelProps) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState<JobContextData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (jobIndex === null) {
      setData(null);
      setShow(false);
      return;
    }

    setLoading(true);
    setError(false);

    fetch(`${API_BASE}/api/jobs/${jobIndex}/context`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load');
        return r.json();
      })
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, [jobIndex]);

  if (jobIndex === null) return null;

  return (
    <>
      <button
        className={`job-context-toggle ${show ? 'active' : ''}`}
        onClick={() => setShow(!show)}
      >
        {show ? 'Hide Job Context' : 'Show Job Context'}
      </button>
      {show && (
        <div className="job-context-panel">
          {loading && (
            <div className="job-context-loading">Loading job context...</div>
          )}
          {error && (
            <div className="job-context-error">Failed to load job context. Try again.</div>
          )}
          {!loading && !error && data && (
            <>
              <h4>Resume ({data.job_name})</h4>
              <pre>{data.resume || '(No resume)'}</pre>
              <h4>Cover Letter</h4>
              <pre>{data.cover_letter || '(No cover letter)'}</pre>
            </>
          )}
        </div>
      )}
    </>
  );
}
