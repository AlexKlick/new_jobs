import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

export interface SessionInfo {
  session_id: string;
  display_name: string;
  updated_at: number;
  job_index: number | null;
  skill_name: string | null;
  message_count: number;
}

interface SessionSelectorProps {
  currentSessionId: string | null;
  onSelect: (sessionId: string | null) => void;
}

export function SessionSelector({ currentSessionId, onSelect }: SessionSelectorProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  useEffect(() => {
    async function loadSessions() {
      try {
        const res = await fetch(`${API_BASE}/api/sessions`);
        if (res.ok) {
          const data = await res.json();
          setSessions(data.sessions || []);
        }
      } catch {
        // non-fatal
      }
    }
    loadSessions();
  }, []);

  return (
    <div className="session-selector">
      <select
        value={currentSessionId ?? ''}
        onChange={e => onSelect(e.target.value || null)}
      >
        <option value="">New Session</option>
        {sessions.map(s => (
          <option key={s.session_id} value={s.session_id}>
            {s.display_name} ({s.message_count} msgs)
          </option>
        ))}
      </select>
    </div>
  );
}
