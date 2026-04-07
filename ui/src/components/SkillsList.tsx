import { useState, useEffect } from 'react';
import { listSkills } from '../skills/api';
import type { SkillFile } from '../skills/types';

interface SkillsListProps {
  selectedFile: string | null;
  onSelectFile: (filename: string) => void;
  versionsOpen: boolean;
  onToggleVersions: () => void;
}

export function SkillsList({ selectedFile, onSelectFile, versionsOpen, onToggleVersions }: SkillsListProps) {
  const [skills, setSkills] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listSkills()
      .then(setSkills)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load skills'))
      .finally(() => setLoading(false));
  }, []);

  const formatDate = (timestamp: number): string => {
    return new Date(timestamp * 1000).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div className="skills-list">
        <div className="skills-list-header">
          <span>Skills</span>
          <button
            className="btn-toggle-versions"
            onClick={onToggleVersions}
            title="Toggle version history"
          >
            {versionsOpen ? 'Hide' : 'History'}
          </button>
        </div>
        <div className="skills-list-items">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skills-list-item skeleton">
              <div className="skeleton-line" style={{ width: '70%' }} />
              <div className="skeleton-line" style={{ width: '40%', marginTop: 4 }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="skills-list">
        <div className="skills-list-header">
          <span>Skills</span>
        </div>
        <div className="skills-list-error">{error}</div>
      </div>
    );
  }

  return (
    <div className="skills-list">
      <div className="skills-list-header">
        <span>Skills</span>
        <button
          className="btn-toggle-versions"
          onClick={onToggleVersions}
          title="Toggle version history"
        >
          {versionsOpen ? 'Hide' : 'History'}
        </button>
      </div>
      <div className="skills-list-items">
        {skills.length === 0 ? (
          <div className="skills-list-empty">
            <p>No skills yet</p>
            <p className="skills-list-empty-hint">
              Create your first skill to customize how AI generates your documents.
            </p>
          </div>
        ) : (
          skills.map((skill) => (
            <div
              key={skill.name}
              className={`skills-list-item${selectedFile === skill.name ? ' selected' : ''}`}
              onClick={() => onSelectFile(skill.name)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && onSelectFile(skill.name)}
            >
              <div className="skill-item-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14,2 14,8 20,8" />
                </svg>
              </div>
              <div className="skill-item-info">
                <div className="skill-item-name">{skill.name}</div>
                <div className="skill-item-modified">Modified: {formatDate(skill.modified)}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
