import { useState, useEffect } from 'react';
import * as Diff from 'diff';
import type { Change } from 'diff';
import { getSkillVersionContent } from '../skills/api';
import type { SkillVersion } from '../skills/types';

interface SkillsDiffProps {
  filename: string;
  versions: SkillVersion[];
  onClose: () => void;
}

export function SkillsDiff({ filename, versions, onClose }: SkillsDiffProps) {
  const [versionA, setVersionA] = useState('');
  const [versionB, setVersionB] = useState('');
  const [diffResult, setDiffResult] = useState<Change[]>([]);
  const [loading, setLoading] = useState(false);

  // Set defaults: A = current, B = first non-current (usually .bak)
  useEffect(() => {
    if (versions.length > 0) {
      const current = versions.find((v) => v.current);
      const others = versions.filter((v) => !v.current);
      setVersionA(current?.name || versions[0].name);
      setVersionB(others[0]?.name || versions[0].name);
    }
  }, [versions]);

  const handleCompare = async () => {
    if (versionA === versionB) return;
    setLoading(true);
    try {
      const [dataA, dataB] = await Promise.all([
        getSkillVersionContent(filename, versionA),
        getSkillVersionContent(filename, versionB),
      ]);
      const changes = Diff.diffLines(dataA.content, dataB.content);
      setDiffResult(changes);
    } catch (err) {
      console.error('Failed to compare versions:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="skills-diff">
      <div className="diff-controls">
        <div className="diff-version-select">
          <label htmlFor="version-a">Version A:</label>
          <select
            id="version-a"
            className="diff-dropdown"
            value={versionA}
            onChange={(e) => setVersionA(e.target.value)}
          >
            {versions.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name} {v.current ? '(current)' : ''}
              </option>
            ))}
          </select>
        </div>

        <div className="diff-version-select">
          <label htmlFor="version-b">Version B:</label>
          <select
            id="version-b"
            className="diff-dropdown"
            value={versionB}
            onChange={(e) => setVersionB(e.target.value)}
          >
            {versions.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name} {v.current ? '(current)' : ''}
              </option>
            ))}
          </select>
        </div>

        <button
          className="btn-compare"
          onClick={handleCompare}
          disabled={loading || versionA === versionB}
        >
          {loading ? 'Comparing...' : 'Compare'}
        </button>

        <button className="btn-close-diff" onClick={onClose}>
          Back to editor
        </button>
      </div>

      <div className="diff-view">
        {versions.length < 2 ? (
          <div className="diff-empty">
            <p>No previous version to compare</p>
          </div>
        ) : diffResult.length === 0 ? (
          <div className="diff-empty">
            <p>Select two versions and click Compare to see differences.</p>
          </div>
        ) : (
          <div className="diff-content">
            {diffResult.map((part, index) => (
              <div
                key={index}
                className={`diff-line${part.added ? ' added' : ''}${part.removed ? ' removed' : ''}`}
              >
                <span className="diff-marker">
                  {part.added ? '+' : part.removed ? '-' : ' '}
                </span>
                <span className="diff-text">{part.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
