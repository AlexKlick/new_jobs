import { useState, useEffect } from 'react';
import { SkillsList } from './SkillsList';
import { SkillsEditor } from './SkillsEditor';
import { SkillsDiff } from './SkillsDiff';
import { getSkillVersions } from '../skills/api';
import type { SkillVersion } from '../skills/types';

interface SkillsPageProps {}

export function SkillsPage({}: SkillsPageProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [showVersions, setShowVersions] = useState(false);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [showDiff, setShowDiff] = useState(false);

  // Load versions when a file is selected
  useEffect(() => {
    if (selectedFile) {
      getSkillVersions(selectedFile)
        .then(setVersions)
        .catch((err) => console.error('Failed to load versions:', err));
    }
  }, [selectedFile]);

  const handleToggleVersions = () => {
    setShowVersions(!showVersions);
    if (!showVersions) {
      setShowDiff(false);
    }
  };

  const handleCompareVersions = () => {
    setShowDiff(true);
  };

  const handleCloseDiff = () => {
    setShowDiff(false);
  };

  return (
    <div className="skills-page">
      <div className="skills-list-panel">
        <SkillsList
          selectedFile={selectedFile}
          onSelectFile={setSelectedFile}
          versionsOpen={showVersions}
          onToggleVersions={handleToggleVersions}
        />
        {showVersions && versions.length >= 1 && (
          <div className="version-history-panel">
            <div className="version-history-header">
              <h3>Version History</h3>
              <button
                className="btn-compare-versions"
                onClick={handleCompareVersions}
                disabled={versions.length < 2}
              >
                Compare
              </button>
            </div>
            <div className="version-list">
              {versions.map((v) => (
                <div
                  key={v.name}
                  className={`version-item${v.current ? ' current' : ''}`}
                >
                  <span className="version-name">{v.name}</span>
                  <span className="version-modified">
                    {new Date(v.modified * 1000).toLocaleString()}
                  </span>
                  {v.current && <span className="version-badge">current</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="skills-editor-panel">
        {showDiff ? (
          <SkillsDiff
            filename={selectedFile!}
            versions={versions}
            onClose={handleCloseDiff}
          />
        ) : selectedFile ? (
          <SkillsEditor
            filename={selectedFile}
            onBack={() => setSelectedFile(null)}
          />
        ) : (
          <div className="skills-empty-state">
            <h2>Select a skill to edit</h2>
            <p>Choose a skill file from the list on the left.</p>
            <a href="/chat" className="btn-link-to-chat">Go to Chat</a>
          </div>
        )}
      </div>
    </div>
  );
}
