import { useState, useEffect, useCallback } from 'react';
import type {
  SourceRecord,
  SourceFieldValue,
  SourceRevision,
  SourceSuggestion,
  ArchetypeDefinition,
} from '../types';

import { API_BASE } from '../config';

/** Group fields by category for organized display. */
function groupByCategory(fields: SourceFieldValue[]): Record<string, SourceFieldValue[]> {
  const groups: Record<string, SourceFieldValue[]> = {};
  for (const f of fields) {
    if (!groups[f.category]) groups[f.category] = [];
    groups[f.category].push(f);
  }
  // Sort each group by order
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => a.order - b.order);
  }
  return groups;
}

/** Format ISO timestamp for display. */
function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Badge class for archetype display. */
function badgeClass(archetype: string): string {
  switch (archetype) {
    case 'new_grad':
      return 'source-archetype-badge new-grad';
    case 'experienced':
      return 'source-archetype-badge experienced';
    default:
      return 'source-archetype-badge';
  }
}

export function SourcesWorkspace() {
  const [records, setRecords] = useState<SourceRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editedFields, setEditedFields] = useState<Record<string, string>>({});
  const [editedLabel, setEditedLabel] = useState('');
  const [revisions, setRevisions] = useState<SourceRevision[]>([]);
  const [archetypes, setArchetypes] = useState<ArchetypeDefinition[]>([]);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createArchetype, setCreateArchetype] = useState<'new_grad' | 'experienced'>('new_grad');
  const [createLabel, setCreateLabel] = useState('');
  const [noteText, setNoteText] = useState('');
  const [suggestions, setSuggestions] = useState<SourceSuggestion[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);

  const selectedRecord = records.find(r => r.record_id === selectedId) || null;

  // Load records and archetypes on mount
  useEffect(() => {
    loadRecords();
    loadArchetypes();
  }, []);

  const loadRecords = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/sources/records`);
      if (resp.ok) {
        const data = await resp.json();
        setRecords(data);
      }
    } catch {
      // API not available yet or network error
    }
  }, []);

  const loadArchetypes = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/sources/archetypes`);
      if (resp.ok) {
        const data = await resp.json();
        setArchetypes(data);
      }
    } catch {
      // API not available yet
    }
  }, []);

  const loadRevisions = useCallback(async (recordId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/sources/records/${recordId}/revisions`);
      if (resp.ok) {
        const data = await resp.json();
        setRevisions(data);
      }
    } catch {
      setRevisions([]);
    }
  }, []);

  // When selecting a record, load its data
  const handleSelectRecord = useCallback((recordId: string) => {
    setSelectedId(recordId);
    setSuggestions([]);
    setNoteText('');
    const rec = records.find(r => r.record_id === recordId);
    if (rec) {
      const fieldMap: Record<string, string> = {};
      for (const f of rec.fields) {
        fieldMap[f.field_id] = f.value;
      }
      setEditedFields(fieldMap);
      setEditedLabel(rec.label);
      setIsDirty(false);
      loadRevisions(recordId);
    }
  }, [records, loadRevisions]);

  const handleFieldChange = useCallback((fieldId: string, value: string) => {
    setEditedFields(prev => ({ ...prev, [fieldId]: value }));
    setIsDirty(true);
  }, []);

  const handleLabelChange = useCallback((value: string) => {
    setEditedLabel(value);
    setIsDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedId) return;
    setIsSaving(true);
    try {
      const fieldUpdates = Object.entries(editedFields).map(([field_id, value]) => ({
        field_id,
        value,
      }));
      const resp = await fetch(`${API_BASE}/api/sources/records/${selectedId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: editedLabel, fields: fieldUpdates }),
      });
      if (resp.ok) {
        setIsDirty(false);
        await loadRecords();
        await loadRevisions(selectedId);
      }
    } finally {
      setIsSaving(false);
    }
  }, [selectedId, editedLabel, editedFields, loadRecords, loadRevisions]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    if (!confirm('Delete this source record? This cannot be undone.')) return;
    try {
      const resp = await fetch(`${API_BASE}/api/sources/records/${selectedId}`, {
        method: 'DELETE',
      });
      if (resp.ok) {
        setSelectedId(null);
        setEditedFields({});
        setRevisions([]);
        await loadRecords();
      }
    } catch {
      // silently fail
    }
  }, [selectedId, loadRecords]);

  const handleCreate = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/sources/records`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ archetype: createArchetype, label: createLabel }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setShowCreate(false);
        setCreateLabel('');
        await loadRecords();
        handleSelectRecord(data.record_id);
      }
    } catch {
      // silently fail
    }
  }, [createArchetype, createLabel, loadRecords, handleSelectRecord]);

  const handleExtractNote = useCallback(async () => {
    if (!selectedId || !noteText.trim()) return;
    setIsExtracting(true);
    try {
      const resp = await fetch(`${API_BASE}/api/sources/records/${selectedId}/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note_text: noteText }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSuggestions(data.suggestions || []);
      }
    } catch {
      // silently fail
    } finally {
      setIsExtracting(false);
    }
  }, [selectedId, noteText]);

  const handleApplySuggestion = useCallback(async (suggestion: SourceSuggestion) => {
    try {
      const resp = await fetch(`${API_BASE}/api/sources/suggestions/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(suggestion),
      });
      if (resp.ok) {
        setSuggestions(prev => prev.filter(s => s.suggestion_id !== suggestion.suggestion_id));
        await loadRecords();
        if (selectedId) {
          await loadRevisions(selectedId);
          // Refresh edited fields from updated record
          const recResp = await fetch(`${API_BASE}/api/sources/records/${selectedId}`);
          if (recResp.ok) {
            const rec = await recResp.json();
            const fieldMap: Record<string, string> = {};
            for (const f of rec.fields) {
              fieldMap[f.field_id] = f.value;
            }
            setEditedFields(fieldMap);
            setEditedLabel(rec.label);
            setIsDirty(false);
          }
        }
      }
    } catch {
      // silently fail
    }
  }, [selectedId, loadRecords, loadRevisions]);

  const handleDismissSuggestion = useCallback((suggestionId: string) => {
    setSuggestions(prev => prev.filter(s => s.suggestion_id !== suggestionId));
  }, []);

  // Build field groups for the form
  const fieldGroups = selectedRecord ? groupByCategory(selectedRecord.fields) : {};
  // Find matching archetype definition for required-field info
  const archetypeDef = archetypes.find(a => a.archetype === selectedRecord?.archetype);

  return (
    <div className="sources-workspace">
      {/* Left Rail: record list */}
      <div className="sources-left-rail">
        <h3>Source Records</h3>
        {records.map(rec => (
          <button
            key={rec.record_id}
            className={`source-record-item ${selectedId === rec.record_id ? 'active' : ''}`}
            onClick={() => handleSelectRecord(rec.record_id)}
          >
            <span className="source-record-label">{rec.label}</span>
            <span className={badgeClass(rec.archetype)}>
              {rec.archetype === 'new_grad' ? 'New Grad' : 'Experienced'}
            </span>
          </button>
        ))}
        <button className="btn-create-source" onClick={() => setShowCreate(true)}>
          + Create Source Record
        </button>
      </div>

      {/* Main Form */}
      <div className="sources-main">
        {selectedRecord ? (
          <>
            <div className="source-form-header">
              <h2>{selectedRecord.label}</h2>
              <div className="source-form-actions">
                <button
                  className="btn-delete-source"
                  onClick={handleDelete}
                >
                  Delete
                </button>
                <button
                  className="btn-save-source"
                  onClick={handleSave}
                  disabled={!isDirty || isSaving}
                >
                  {isSaving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>

            <div className="source-field">
              <label>Record Label</label>
              <input
                type="text"
                value={editedLabel}
                onChange={e => handleLabelChange(e.target.value)}
                placeholder="Profile name"
              />
            </div>

            {Object.entries(fieldGroups).map(([category, fields]) => (
              <div key={category} className="source-category">
                <h4>{category.charAt(0).toUpperCase() + category.slice(1)}</h4>
                {fields.map(field => {
                  const fieldDef = archetypeDef?.fields.find(f => f.field_id === field.field_id);
                  const isRequired = fieldDef?.required ?? false;
                  return (
                    <div key={field.field_id} className="source-field">
                      <label>
                        {field.label}
                        {isRequired && <span className="required-marker">*</span>}
                      </label>
                      {(field.field_id.includes('project') || field.field_id.includes('role') ||
                        field.field_id.includes('achievement') || field.field_id.includes('internship'))
                        ? (
                          <textarea
                            value={editedFields[field.field_id] ?? field.value}
                            onChange={e => handleFieldChange(field.field_id, e.target.value)}
                            placeholder={fieldDef?.placeholder || ''}
                            rows={3}
                          />
                        )
                        : (
                          <input
                            type="text"
                            value={editedFields[field.field_id] ?? field.value}
                            onChange={e => handleFieldChange(field.field_id, e.target.value)}
                            placeholder={fieldDef?.placeholder || ''}
                          />
                        )
                      }
                    </div>
                  );
                })}
              </div>
            ))}
          </>
        ) : (
          <div className="source-form-empty">
            Select a source record or create a new one.
          </div>
        )}
      </div>

      {/* Right Rail: revisions + notes */}
      <div className="sources-right-rail">
        <div className="rail-section">
          <h4>Revisions</h4>
          {revisions.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
              No revisions yet.
            </div>
          ) : (
            revisions.map(rev => (
              <div key={rev.revision_id} className="revision-item">
                <div className="revision-time">{formatTime(rev.created_at)}</div>
                <div className="revision-summary">{rev.summary}</div>
                <div className="revision-provenance">{rev.provenance}</div>
              </div>
            ))
          )}
        </div>

        <div className="rail-section">
          <h4>Note to Source</h4>
          <div className="note-input">
            <textarea
              value={noteText}
              onChange={e => setNoteText(e.target.value)}
              placeholder="Paste freeform notes here to extract structured data..."
              rows={4}
            />
            <button
              className="btn-extract-note"
              onClick={handleExtractNote}
              disabled={!noteText.trim() || isExtracting || !selectedId}
            >
              {isExtracting ? 'Extracting...' : 'Extract Suggestions'}
            </button>
          </div>
          {suggestions.length > 0 && (
            <div style={{ marginTop: '0.5rem' }}>
              {suggestions.map(sug => (
                <div key={sug.suggestion_id} className="suggestion-card">
                  <div className="suggestion-field-label">{sug.field_label}</div>
                  {sug.current_value && (
                    <div className="suggestion-current">{sug.current_value}</div>
                  )}
                  <div className="suggestion-proposed">{sug.suggested_value}</div>
                  <div className="suggestion-actions">
                    <button
                      className="btn-apply-suggestion"
                      onClick={() => handleApplySuggestion(sug)}
                    >
                      Apply
                    </button>
                    <button
                      className="btn-dismiss-suggestion"
                      onClick={() => handleDismissSuggestion(sug.suggestion_id)}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Create Record Dialog */}
      {showCreate && (
        <div className="create-source-overlay" onClick={() => setShowCreate(false)}>
          <div className="create-source-dialog" onClick={e => e.stopPropagation()}>
            <h3>Create Source Record</h3>

            <div className="source-field">
              <label>Record Label</label>
              <input
                type="text"
                value={createLabel}
                onChange={e => setCreateLabel(e.target.value)}
                placeholder="e.g. My Career Profile"
              />
            </div>

            <div className="archetype-selector">
              <button
                className={`archetype-option ${createArchetype === 'new_grad' ? 'selected' : ''}`}
                onClick={() => setCreateArchetype('new_grad')}
              >
                <h4>New Graduate</h4>
                <p>Education, projects, internships</p>
              </button>
              <button
                className={`archetype-option ${createArchetype === 'experienced' ? 'selected' : ''}`}
                onClick={() => setCreateArchetype('experienced')}
              >
                <h4>Experienced Professional</h4>
                <p>Work history, achievements, leadership</p>
              </button>
            </div>

            <div className="dialog-actions">
              <button
                className="btn-dialog-cancel"
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
              <button
                className="btn-dialog-create"
                onClick={handleCreate}
                disabled={!createLabel.trim()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
