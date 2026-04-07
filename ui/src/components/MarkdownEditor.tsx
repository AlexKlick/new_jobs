import { useState, useEffect, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import CodeMirror from '@uiw/react-codemirror';
import { markdown } from '@codemirror/lang-markdown';
import { githubLight } from '@uiw/codemirror-theme-github';
import { history } from '@codemirror/commands';
import { EditorView } from '@codemirror/view';

export interface MarkdownEditorProps {
  content: string;
  onSave: (content: string) => Promise<void>;
  onCancel: () => void;
  documentType: 'resume' | 'cover_letter';
}

type EditMode = 'edit' | 'preview';
type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

function useAutoSave(
  content: string,
  lastSavedRef: React.MutableRefObject<string>,
  onSave: (content: string) => Promise<void>,
  setSaveState: React.Dispatch<React.SetStateAction<SaveState>>,
  delay: number = 3000
) {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveStateRef = useRef<SaveState>('idle');

  useEffect(() => {
    // Not dirty - no need to save
    if (content === lastSavedRef.current) {
      if (saveStateRef.current === 'pending') {
        saveStateRef.current = 'idle';
        setSaveState('idle');
      }
      return;
    }

    // Clear existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Set pending state
    saveStateRef.current = 'pending';
    setSaveState('pending');

    // Set new timeout
    timeoutRef.current = setTimeout(async () => {
      saveStateRef.current = 'saving';
      setSaveState('saving');
      try {
        await onSave(content);
        lastSavedRef.current = content;
        saveStateRef.current = 'saved';
        setSaveState('saved');
      } catch {
        saveStateRef.current = 'error';
        setSaveState('error');
      }
    }, delay);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [content, delay, onSave, lastSavedRef, setSaveState]);

  // Return function to cancel pending auto-save (call from manual save)
  const cancelPending = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
      saveStateRef.current = 'idle';
      setSaveState('idle');
    }
  }, [setSaveState]);

  return { cancelPending };
}

export function MarkdownEditor({ content, onSave, onCancel, documentType }: MarkdownEditorProps) {
  const [editMode, setEditMode] = useState<EditMode>('edit');
  const [draft, setDraft] = useState(content);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const editorRef = useRef<any>(null);
  const lastSavedRef = useRef(content);

  const { cancelPending } = useAutoSave(draft, lastSavedRef, onSave, setSaveState, 3000);

  // Track dirty state
  useEffect(() => {
    setIsDirty(draft !== lastSavedRef.current);
  }, [draft]);

  // Reset draft when content changes (e.g., switching jobs)
  useEffect(() => {
    setDraft(content);
    lastSavedRef.current = content;
    setIsDirty(false);
    setSaveError(null);
    setSaveState('idle');
  }, [content]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (isDirty && !isSaving) {
          handleSave();
        }
      }
      if (e.key === 'Escape') {
        if (isDirty) {
          const confirmed = window.confirm('You have unsaved changes. Are you sure you want to cancel?');
          if (!confirmed) return;
        }
        onCancel();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && e.shiftKey) {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDirty, isSaving, draft, onCancel]);

  const handleUndo = () => {
    if (editorRef.current?.view) {
      editorRef.current.view.dispatch({ undo: true });
    }
  };

  const handleRedo = () => {
    if (editorRef.current?.view) {
      editorRef.current.view.dispatch({ redo: true });
    }
  };

  const handleSave = useCallback(async () => {
    if (!draft.trim()) {
      setSaveError('Content cannot be empty');
      return;
    }
    if (draft.length > 500_000) {
      setSaveError('Content exceeds maximum size (500KB)');
      return;
    }

    // Cancel any pending auto-save first
    cancelPending();
    setIsSaving(true);
    setSaveError(null);
    setSaveState('saving');
    try {
      await onSave(draft);
      lastSavedRef.current = draft;
      setIsDirty(false);
      setSaveState('saved');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
      setSaveState('error');
    } finally {
      setIsSaving(false);
    }
  }, [draft, onSave, cancelPending]);

  const insertMarkdown = useCallback((prefix: string, suffix: string = '') => {
    const view = editorRef.current?.view;
    if (!view) return;
    const { from, to } = view.state.selection.main;
    const selected = view.state.sliceDoc(from, to);
    view.dispatch({
      changes: { from, to, insert: prefix + selected + suffix },
      selection: { anchor: from + prefix.length, head: from + prefix.length + selected.length }
    });
    view.focus();
  }, []);

  const handleUndoRedo = useCallback((action: 'undo' | 'redo') => {
    if (editorRef.current?.view) {
      editorRef.current.view.dispatch({ [action]: true });
    }
  }, []);

  const toolbarActions = [
    { label: 'Undo', title: 'Undo (Ctrl+Z)', action: () => handleUndoRedo('undo') },
    { label: 'Redo', title: 'Redo (Ctrl+Shift+Z)', action: () => handleUndoRedo('redo') },
    { label: 'B', title: 'Bold', action: () => insertMarkdown('**', '**') },
    { label: 'I', title: 'Italic', action: () => insertMarkdown('_', '_') },
    { label: 'Link', title: 'Link', action: () => insertMarkdown('[', '](url)') },
    { label: 'List', title: 'Bullet List', action: () => insertMarkdown('\n- ', '') },
    { label: 'H2', title: 'Heading', action: () => insertMarkdown('\n## ', '') },
    { label: 'Code', title: 'Inline Code', action: () => insertMarkdown('`', '`') },
    { label: 'Quote', title: 'Blockquote', action: () => insertMarkdown('\n> ', '') },
  ];

  // Save on blur (tab switch)
  useEffect(() => {
    const handleBlur = () => {
      if (isDirty && !isSaving) {
        // Trigger immediate save on blur
        cancelPending();
        onSave(draft).then(() => {
          lastSavedRef.current = draft;
          setIsDirty(false);
          setSaveState('saved');
        }).catch(() => {
          setSaveState('error');
        });
      }
    };

    const editorElement = document.querySelector('.editor-codemirror');
    editorElement?.addEventListener('blur', handleBlur);

    return () => {
      editorElement?.removeEventListener('blur', handleBlur);
    };
  }, [isDirty, draft, onSave, isSaving, cancelPending]);

  // Before unload warning
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  return (
    <div className="markdown-editor">
      <div className="editor-toolbar">
        <div className="toolbar-actions">
          {toolbarActions.map(({ label, title, action }) => (
            <button
              key={label}
              type="button"
              title={title}
              className="toolbar-btn"
              onClick={action}
              disabled={editMode === 'preview'}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="toolbar-tabs">
          <button
            type="button"
            className={`tab-btn ${editMode === 'edit' ? 'active' : ''}`}
            onClick={() => setEditMode('edit')}
          >
            Edit
          </button>
          <button
            type="button"
            className={`tab-btn ${editMode === 'preview' ? 'active' : ''}`}
            onClick={() => setEditMode('preview')}
          >
            Preview
          </button>
        </div>
      </div>

      <div className="editor-content">
        {editMode === 'edit' ? (
          <CodeMirror
            ref={editorRef}
            value={draft}
            height="100%"
            theme={githubLight}
            extensions={[
              markdown(),
              history({ minDepth: 100 }),
              EditorView.lineWrapping,
            ]}
            onChange={(value: string) => {
              setDraft(value);
              setSaveState('pending');
            }}
            className="editor-codemirror"
          />
        ) : (
          <div className="editor-preview">
            <ReactMarkdown>{draft}</ReactMarkdown>
          </div>
        )}
      </div>

      {saveError && (
        <div className="editor-error">
          {saveError}
        </div>
      )}

      <div className="editor-footer">
        <div className="editor-status">
          {saveState === 'idle' && !isDirty && <span className="saved-indicator">Saved</span>}
          {saveState === 'idle' && isDirty && <span className="dirty-indicator">Unsaved changes</span>}
          {saveState === 'pending' && <span className="pending-indicator">Pending save...</span>}
          {saveState === 'saving' && <span className="saving-indicator">Saving...</span>}
          {saveState === 'saved' && <span className="auto-saved-indicator">Auto-saved</span>}
          {saveState === 'error' && <span className="error-indicator">Save failed</span>}
          <span className="doc-type-label">
            {documentType === 'resume' ? 'Resume' : 'Cover Letter'}
          </span>
        </div>
        <div className="editor-actions">
          <button
            type="button"
            className="btn-cancel"
            onClick={() => {
              if (isDirty) {
                const confirmed = window.confirm('You have unsaved changes. Are you sure you want to cancel?');
                if (!confirmed) return;
              }
              onCancel();
            }}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn-save"
            onClick={handleSave}
            disabled={isSaving || !isDirty}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
