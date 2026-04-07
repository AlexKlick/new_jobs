import { useState, useEffect, useCallback, useRef } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { linter } from '@codemirror/lint';
import { githubLight } from '@uiw/codemirror-theme-github';
import { EditorView } from '@codemirror/view';
import * as yamlLib from 'js-yaml';
import { getSkill, saveSkill } from '../skills/api';

interface SkillsEditorProps {
  filename: string;
  onBack?: () => void;
}

export function SkillsEditor({ filename, onBack }: SkillsEditorProps) {
  const [draft, setDraft] = useState('');
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationMessage, setValidationMessage] = useState<string>('Valid YAML');
  const [validationStatus, setValidationStatus] = useState<'valid' | 'error'>('valid');
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [showSaved, setShowSaved] = useState(false);
  const lastSavedRef = useRef('');

  // Load skill content when filename changes
  useEffect(() => {
    setIsDirty(false);
    setSaveError(null);
    setShowSaved(false);
    getSkill(filename)
      .then((data) => {
        setDraft(data.content);
        lastSavedRef.current = data.content;
      })
      .catch((err) => {
        setSaveError(err instanceof Error ? err.message : 'Failed to load skill');
      });
  }, [filename]);

  // Track dirty state
  useEffect(() => {
    setIsDirty(draft !== lastSavedRef.current);
  }, [draft]);

  // YAML Linter with 300ms debounce
  const yamlLinter = linter((view) => {
    const content = view.state.doc.toString();
    if (!content.trim()) {
      setValidationStatus('valid');
      setValidationMessage('Valid YAML');
      return [];
    }
    try {
      yamlLib.load(content);
      setValidationStatus('valid');
      setValidationMessage('Valid YAML');
      return [];
    } catch (e: any) {
      setValidationStatus('error');
      const msg = e.message || 'Unknown YAML error';
      setValidationMessage(`Invalid YAML: ${msg}`);
      return [
        {
          from: 0,
          to: content.length,
          severity: 'error',
          message: msg,
        },
      ];
    }
  }, { delay: 300 });

  const extensions = [yaml(), yamlLinter, EditorView.lineWrapping];

  const handleSave = useCallback(async () => {
    if (!draft.trim()) {
      setSaveError('Content cannot be empty');
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      await saveSkill(filename, draft);
      lastSavedRef.current = draft;
      setIsDirty(false);
      setLastSavedAt(new Date());
      setShowSaved(true);
      setTimeout(() => setShowSaved(false), 2000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setIsSaving(false);
    }
  }, [draft, filename]);

  // Keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (isDirty && !isSaving) {
          handleSave();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDirty, isSaving, handleSave]);

  return (
    <div className="skills-editor">
      <div className="editor-toolbar">
        <div className="toolbar-left">
          {onBack && (
            <button className="btn-back" onClick={onBack} title="Back to list">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15,18 9,12 15,6" />
              </svg>
            </button>
          )}
          <span className="toolbar-filename">{filename}</span>
        </div>

        <div className="toolbar-center">
          <span className={`toolbar-validation ${validationStatus === 'error' ? 'validation-error' : 'validation-valid'}`}>
            {validationStatus === 'error' ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
              </svg>
            )}
            <span>{validationMessage}</span>
          </span>
        </div>

        <div className="toolbar-right">
          {isDirty && <span className="dirty-indicator">Unsaved changes</span>}
          {showSaved && <span className="saved-indicator">Saved</span>}
          <button
            className="btn-save-skill"
            onClick={handleSave}
            disabled={isSaving || !isDirty}
          >
            {isSaving ? 'Saving...' : 'Save skill'}
          </button>
        </div>
      </div>

      <div className="skills-editor-content">
        <CodeMirror
          value={draft}
          height="100%"
          theme={githubLight}
          extensions={extensions}
          onChange={(value: string) => setDraft(value)}
          className="skills-codemirror"
        />
      </div>

      <div className="skills-validation-bar">
        {saveError ? (
          <span className="error-indicator">{saveError}</span>
        ) : (
          <>
            <span className={`validation-status ${validationStatus === 'error' ? 'validation-error' : 'validation-valid'}`}>
              {validationStatus === 'error' ? 'Invalid YAML' : 'Valid YAML'}
            </span>
            {lastSavedAt && (
              <span className="last-saved">
                Last saved: {lastSavedAt.toLocaleTimeString()}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
