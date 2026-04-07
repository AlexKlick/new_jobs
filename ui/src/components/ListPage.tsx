import { useState, useEffect, useCallback } from 'react';
import type { JobList, JobListDetail, JobListItemDisplay } from '../types';
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

function priorityClass(p: string | null): string {
  if (p === 'high') return 'priority-high';
  if (p === 'medium') return 'priority-medium';
  if (p === 'low') return 'priority-low';
  return '';
}

function statusClass(s: string | null): string {
  if (s === 'applied') return 'status-applied';
  if (s === 'rejected') return 'status-rejected';
  if (s === 'wishlist') return 'status-wishlist';
  return '';
}

// ── Priority Select ─────────────────────────────────────────────────────────────

interface PrioritySelectProps {
  value: string | null;
  itemId: string;
  onUpdate: (itemId: string, priority: string) => void;
}

function PrioritySelect({ value, itemId, onUpdate }: PrioritySelectProps) {
  return (
    <select
      className={`list-priority-select ${priorityClass(value)}`}
      value={value || ''}
      onChange={e => onUpdate(itemId, e.target.value)}
    >
      <option value="">—</option>
      <option value="low">Low</option>
      <option value="medium">Med</option>
      <option value="high">High</option>
    </select>
  );
}

// ── Status Select ───────────────────────────────────────────────────────────────

interface StatusSelectProps {
  value: string | null;
  itemId: string;
  onUpdate: (itemId: string, status: string) => void;
}

function StatusSelect({ value, itemId, onUpdate }: StatusSelectProps) {
  return (
    <select
      className={`list-status-select ${statusClass(value)}`}
      value={value || ''}
      onChange={e => onUpdate(itemId, e.target.value)}
    >
      <option value="">—</option>
      <option value="wishlist">Wishlist</option>
      <option value="applied">Applied</option>
      <option value="rejected">Rejected</option>
    </select>
  );
}

// ── Notes Editor ───────────────────────────────────────────────────────────────

interface NotesEditorProps {
  itemId: string;
  notes: string | null;
  onSave: (itemId: string, notes: string) => void;
}

function NotesEditor({ itemId, notes, onSave }: NotesEditorProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(notes || '');

  const handleBlur = useCallback(() => {
    setEditing(false);
    if (value !== (notes || '')) {
      onSave(itemId, value);
    }
  }, [value, notes, itemId, onSave]);

  if (!editing) {
    return (
      <div
        className={`list-item-notes ${notes ? 'has-notes' : 'empty-notes'}`}
        onClick={() => { setEditing(true); setValue(notes || ''); }}
        title="Click to add notes"
      >
        {notes || <span className="notes-placeholder">Add notes…</span>}
      </div>
    );
  }

  return (
    <textarea
      className="list-item-notes-editor"
      value={value}
      onChange={e => setValue(e.target.value)}
      onBlur={handleBlur}
      onKeyDown={e => { if (e.key === 'Escape') { setEditing(false); setValue(notes || ''); } }}
      rows={2}
      autoFocus
    />
  );
}

// ── Promote Dialog ──────────────────────────────────────────────────────────────

interface PromoteDialogProps {
  item: JobListItemDisplay;
  onClose: () => void;
  onPromote: (itemId: string) => void;
}

function PromoteDialog({ item, onClose, onPromote }: PromoteDialogProps) {
  const [promoting, setPromoting] = useState(false);

  const handlePromote = async () => {
    setPromoting(true);
    await onPromote(item.item_id);
    setPromoting(false);
  };

  return (
    <div className="promote-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="promote-title">
      <div className="promote-dialog" onClick={e => e.stopPropagation()}>
        <h3 id="promote-title">Promote to Application?</h3>
        <p>
          This will promote <strong>{item.company}</strong> — <strong>{item.role}</strong> into
          your canonical application workflow.
        </p>
        <p className="promote-note">
          The job will enter the standard application pipeline (Tracker, Documents, Generation).
          This action cannot be undone. The raw search candidate will remain in the search history.
        </p>
        <div className="dialog-actions">
          <button className="btn-dialog-cancel" onClick={onClose}>Cancel</button>
          <button
            className="btn-promote-confirm"
            onClick={handlePromote}
            disabled={promoting}
          >
            {promoting ? 'Promoting…' : 'Promote'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── List Page ───────────────────────────────────────────────────────────────────

export function ListPage() {
  const [lists, setLists] = useState<JobList[]>([]);
  const [selectedListId, setSelectedListId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobListDetail | null>(null);
  const [promoteItem, setPromoteItem] = useState<JobListItemDisplay | null>(null);
  const [loading, setLoading] = useState(false);

  // Load all lists on mount
  useEffect(() => {
    loadLists();
  }, []);

  const loadLists = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/lists`);
      if (resp.ok) {
        const data: JobList[] = await resp.json();
        setLists(data);
      }
    } catch {
      // API not available
    }
  }, []);

  const loadListDetail = useCallback(async (listId: string) => {
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/search/lists/${listId}`);
      if (resp.ok) {
        const data: JobListDetail = await resp.json();
        setDetail(data);
        setSelectedListId(listId);
      }
    } catch {
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Update priority
  const handlePriorityUpdate = useCallback(async (itemId: string, priority: string) => {
    try {
      await fetch(`${API_BASE}/api/search/lists/items/${itemId}/priority`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority }),
      });
      // Refresh detail
      if (selectedListId) loadListDetail(selectedListId);
    } catch {
      // silent fail
    }
  }, [selectedListId, loadListDetail]);

  // Update status
  const handleStatusUpdate = useCallback(async (itemId: string, status: string) => {
    try {
      await fetch(`${API_BASE}/api/search/lists/items/${itemId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (selectedListId) loadListDetail(selectedListId);
    } catch {
      // silent fail
    }
  }, [selectedListId, loadListDetail]);

  // Save notes
  const handleNotesSave = useCallback(async (itemId: string, notes: string) => {
    try {
      await fetch(`${API_BASE}/api/search/lists/items/${itemId}/notes`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes }),
      });
      if (selectedListId) loadListDetail(selectedListId);
    } catch {
      // silent fail
    }
  }, [selectedListId, loadListDetail]);

  // Remove item
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);

  const handleRemove = useCallback(async (itemId: string) => {
    try {
      await fetch(`${API_BASE}/api/search/lists/items/${itemId}`, {
        method: 'DELETE',
      });
      setRemoveTarget(null);
      if (selectedListId) loadListDetail(selectedListId);
    } catch {
      setRemoveTarget(null);
    }
  }, [selectedListId, loadListDetail]);

  // Reorder — keyboard move up/down
  const handleMoveUp = useCallback(async (index: number) => {
    if (!detail || index === 0) return;
    const newOrder = [...detail.items];
    [newOrder[index - 1], newOrder[index]] = [newOrder[index], newOrder[index - 1]];
    await reorderItems(newOrder.map(it => it.item_id));
  }, [detail]);

  const handleMoveDown = useCallback(async (index: number) => {
    if (!detail || index === detail.items.length - 1) return;
    const newOrder = [...detail.items];
    [newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]];
    await reorderItems(newOrder.map(it => it.item_id));
  }, [detail]);

  const reorderItems = async (itemIds: string[]) => {
    try {
      await fetch(`${API_BASE}/api/search/lists/items/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_ids: itemIds }),
      });
      if (selectedListId) loadListDetail(selectedListId);
    } catch {
      // silent fail
    }
  };

  // Promote
  const handlePromote = useCallback(async (itemId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/search/lists/items/${itemId}/promote`, {
        method: 'POST',
      });
      if (resp.ok) {
        setPromoteItem(null);
        if (selectedListId) loadListDetail(selectedListId);
      }
    } catch {
      setPromoteItem(null);
    }
  }, [selectedListId, loadListDetail]);

  return (
    <div className="list-page">
      {/* Left panel: list selector */}
      <div className="list-left-panel">
        <h3>Saved Lists</h3>
        {lists.length === 0 ? (
          <div className="list-empty-hint">
            No lists yet. Run a search to create one automatically.
          </div>
        ) : (
          <div className="list-selector">
            {lists.map(lst => (
              <button
                key={lst.list_id}
                className={`list-selector-item ${selectedListId === lst.list_id ? 'active' : ''}`}
                onClick={() => loadListDetail(lst.list_id)}
              >
                <span className="list-selector-label">{lst.label}</span>
                <span className="list-selector-time">{formatTime(lst.updated_at)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main panel: list items */}
      <div className="list-main">
        {!selectedListId ? (
          <EmptyState
            icon="?"
            title="No list selected"
            description="Select a list from the left panel to review and prioritize jobs."
          />
        ) : loading ? (
          <LoadingState message="Loading list..." />
        ) : detail ? (
          <>
            <div className="list-header">
              <h2>{detail.label}</h2>
              <span className="list-count">{detail.items.length} jobs</span>
            </div>

            {detail.items.length === 0 ? (
              <EmptyState
                title="No items in this list"
                description="Run a search to populate it with job candidates."
              />
            ) : (
              <div className="list-item-table">
                <div className="list-item-table-head">
                  <span className="col-rank">#</span>
                  <span className="col-info">Job</span>
                  <span className="col-priority">Priority</span>
                  <span className="col-status">Status</span>
                  <span className="col-notes">Notes</span>
                  <span className="col-actions">Actions</span>
                </div>
                {detail.items.map((item, idx) => (
                  <div key={item.item_id} className="list-item-row">
                    <span className="col-rank">
                      <span className="rank-number">{idx + 1}</span>
                      <span className="rank-controls">
                        <button
                          className="btn-rank"
                          onClick={() => handleMoveUp(idx)}
                          onKeyDown={e => { if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); handleMoveUp(idx); } }}
                          disabled={idx === 0}
                          title="Move up"
                          aria-label={`Move rank ${idx + 1} up`}
                        >↑</button>
                        <button
                          className="btn-rank"
                          onClick={() => handleMoveDown(idx)}
                          onKeyDown={e => { if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); handleMoveDown(idx); } }}
                          disabled={idx === detail.items.length - 1}
                          title="Move down"
                          aria-label={`Move rank ${idx + 1} down`}
                        >↓</button>
                      </span>
                    </span>
                    <span className="col-info">
                      <div className="item-company">{item.company}</div>
                      <div className="item-role">{item.role}</div>
                      <div className="item-meta">
                        {item.location && <span>{item.location}</span>}
                        <span className={`item-badge source-${item.source}`}>{item.source}</span>
                        {item.promoted && <span className="item-badge promoted">Promoted</span>}
                        {item.ingested && <span className="item-badge ingested">Ingested</span>}
                      </div>
                    </span>
                    <span className="col-priority">
                      <PrioritySelect
                        value={item.priority}
                        itemId={item.item_id}
                        onUpdate={handlePriorityUpdate}
                      />
                    </span>
                    <span className="col-status">
                      <StatusSelect
                        value={item.status}
                        itemId={item.item_id}
                        onUpdate={handleStatusUpdate}
                      />
                    </span>
                    <span className="col-notes">
                      <NotesEditor
                        itemId={item.item_id}
                        notes={item.notes}
                        onSave={handleNotesSave}
                      />
                    </span>
                    <span className="col-actions">
                      {item.apply_url && (
                        <a
                          href={item.apply_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn-list-action btn-apply"
                        >
                          Apply
                        </a>
                      )}
                      {!item.promoted && !item.ingested && (
                        <button
                          className="btn-list-action btn-promote"
                          onClick={() => setPromoteItem(item)}
                          aria-label={`Promote ${item.company} - ${item.role} to application`}
                          title="Promote to application pipeline"
                        >
                          Promote
                        </button>
                      )}
                      <button
                        className="btn-list-action btn-remove"
                        onClick={() => setRemoveTarget(item.item_id)}
                        title="Remove from list"
                        aria-label={`Remove ${item.company} - ${item.role} from list`}
                      >
                        Remove
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <EmptyState
            title="List not found"
            description="This list may have been deleted."
          />
        )}
      </div>

      {promoteItem && (
        <PromoteDialog
          item={promoteItem}
          onClose={() => setPromoteItem(null)}
          onPromote={handlePromote}
        />
      )}

      {removeTarget && (
        <div className="promote-overlay" onClick={() => setRemoveTarget(null)} role="dialog" aria-modal="true" aria-labelledby="remove-title">
          <div className="promote-dialog" onClick={e => e.stopPropagation()}>
            <h3 id="remove-title">Remove from List?</h3>
            <p>
              This will remove this job from the current list. The search candidate
              will still exist in the search history.
            </p>
            <div className="dialog-actions">
              <button className="btn-dialog-cancel" onClick={() => setRemoveTarget(null)}>Cancel</button>
              <button
                className="btn-remove-confirm"
                onClick={() => handleRemove(removeTarget)}
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
