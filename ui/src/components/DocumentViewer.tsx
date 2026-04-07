import { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { EnrichedJob } from '../types';
import { MarkdownEditor } from './MarkdownEditor';
import { API_BASE } from '../config';

interface DocumentViewerProps {
  jobs: EnrichedJob[];
}

export function DocumentViewer({ jobs }: DocumentViewerProps) {
  const { index: urlIndex } = useParams<{ index: string }>();
  const [searchParams] = useSearchParams();
  const docType = searchParams.get('doc') || 'resume';

  const [selectedJobIndex, setSelectedJobIndex] = useState<number>(urlIndex ? parseInt(urlIndex, 10) : jobs[0]?.index || 1);
  const [documentType, setDocumentType] = useState<'resume' | 'cover_letter'>(docType as 'resume' | 'cover_letter');
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [viewMode, setViewMode] = useState<'markdown' | 'pdf'>('markdown');
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [pdfCacheBuster, setPdfCacheBuster] = useState(Date.now());

  useEffect(() => {
    if (urlIndex) {
      setSelectedJobIndex(parseInt(urlIndex, 10));
    }
    if (docType) {
      setDocumentType(docType as 'resume' | 'cover_letter');
    }
  }, [urlIndex, docType]);

  // Clear success message after 3 seconds
  useEffect(() => {
    if (saveSuccess) {
      const timer = setTimeout(() => setSaveSuccess(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [saveSuccess]);

  const selectedJob = jobs.find(j => j.index === selectedJobIndex);

  const documentContent = selectedJob?.resumeMd && documentType === 'resume'
    ? selectedJob.resumeMd
    : selectedJob?.coverLetterMd && documentType === 'cover_letter'
    ? selectedJob.coverLetterMd
    : null;

  const pdfUrl = `${API_BASE}/api/jobs/${selectedJobIndex}/pdf/${documentType}?t=${pdfCacheBuster}`;

  const jobsWithDocuments = jobs.filter(j => j.resumeMd || j.coverLetterMd);

  const handleSave = useCallback(async (content: string) => {
    setIsSaving(true);
    try {
      const endpoint = documentType === 'resume'
        ? `${API_BASE}/api/jobs/${selectedJobIndex}/resume`
        : `${API_BASE}/api/jobs/${selectedJobIndex}/cover-letter`;

      const response = await fetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });

      const data = await response.json();
      if (!response.ok || !data.saved) {
        throw new Error(data.error || 'Save failed');
      }
      setSaveSuccess(true);
      setIsEditing(false);
      // Refresh the page data to reflect changes
      window.location.reload();
    } finally {
      setIsSaving(false);
    }
  }, [selectedJobIndex, documentType]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
  }, []);

  const handleStartEdit = useCallback(() => {
    setIsEditing(true);
    setSaveSuccess(false);
  }, []);

  const handleRegenerate = useCallback(async () => {
    if (isEditing) return; // Disable while editing
    setIsRegenerating(true);
    setRegenerateError(null);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${selectedJobIndex}/regenerate-pdf`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!data.success) {
        setRegenerateError(data.error || 'Regeneration failed');
      } else {
        setPdfCacheBuster(Date.now()); // Force iframe refresh
      }
    } catch (err) {
      setRegenerateError('Network error');
    } finally {
      setIsRegenerating(false);
    }
  }, [selectedJobIndex, isEditing]);

  const handleDownload = useCallback(() => {
    window.open(pdfUrl, '_blank');
  }, [pdfUrl]);

  const handleViewModeChange = useCallback((mode: 'markdown' | 'pdf') => {
    if (isEditing) {
      alert('Please save or cancel your edits before switching views.');
      return;
    }
    setViewMode(mode);
  }, [isEditing]);

  // Warn on navigation away with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isEditing) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isEditing]);

  return (
    <div className="document-viewer">
      <div className="doc-sidebar">
        <h3>Select Job</h3>
        <div className="doc-job-list">
          {jobsWithDocuments.map(job => (
            <button
              key={job.index}
              className={`doc-job-item ${selectedJobIndex === job.index ? 'active' : ''}`}
              onClick={() => setSelectedJobIndex(job.index)}
            >
              <span className="doc-job-index">#{job.index}</span>
              <span className="doc-job-company">{job.company}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="doc-main">
        <div className="doc-toolbar">
          <div className="doc-type-tabs">
            <button
              className={`doc-tab ${documentType === 'resume' ? 'active' : ''}`}
              onClick={() => setDocumentType('resume')}
              disabled={isEditing}
            >
              Resume
            </button>
            <button
              className={`doc-tab ${documentType === 'cover_letter' ? 'active' : ''}`}
              onClick={() => setDocumentType('cover_letter')}
              disabled={isEditing}
            >
              Cover Letter
            </button>
          </div>
          <div className="doc-job-info">
            {selectedJob && (
              <span>{selectedJob.company} — {selectedJob.role}</span>
            )}
          </div>
          <div className="doc-toolbar-actions">
            {saveSuccess && (
              <span className="save-success-indicator">Saved successfully</span>
            )}
            {!isEditing && documentContent && (
              <>
                <button
                  className={`btn-view-toggle ${viewMode === 'markdown' ? 'active' : ''}`}
                  onClick={() => handleViewModeChange('markdown')}
                  title="View Markdown"
                >
                  MD
                </button>
                <button
                  className={`btn-view-toggle ${viewMode === 'pdf' ? 'active' : ''}`}
                  onClick={() => handleViewModeChange('pdf')}
                  title="View PDF"
                >
                  PDF
                </button>
              </>
            )}
            {!isEditing && viewMode === 'pdf' && documentContent && (
              <>
                <button
                  className="btn-regenerate"
                  onClick={handleRegenerate}
                  disabled={isRegenerating}
                  title="Regenerate PDF"
                >
                  {isRegenerating ? 'Regenerating...' : 'Regenerate'}
                </button>
                <button
                  className="btn-download"
                  onClick={handleDownload}
                  title="Download PDF"
                >
                  Download
                </button>
              </>
            )}
            {!isEditing && viewMode === 'markdown' && documentContent && (
              <button
                className="btn-edit"
                onClick={handleStartEdit}
                title="Edit document"
              >
                Edit
              </button>
            )}
          </div>
        </div>

        <div className="doc-content">
          {viewMode === 'markdown' ? (
            isEditing ? (
              <MarkdownEditor
                content={documentContent || ''}
                onSave={handleSave}
                onCancel={handleCancel}
                documentType={documentType}
              />
            ) : documentContent ? (
              <ReactMarkdown>{documentContent}</ReactMarkdown>
            ) : (
              <div className="no-doc">
                {selectedJob
                  ? `No ${documentType === 'resume' ? 'resume' : 'cover letter'} available for this job.`
                  : 'Select a job to view documents.'
                }
              </div>
            )
          ) : (
            <div className="pdf-preview-container">
              {regenerateError && (
                <div className="regenerate-error">{regenerateError}</div>
              )}
              <iframe
                src={pdfUrl}
                className="pdf-preview-iframe"
                title="PDF Preview"
              />
            </div>
          )}
        </div>

        {isSaving && (
          <div className="doc-loading-overlay">
            <div className="doc-loading-spinner">Saving...</div>
          </div>
        )}
      </div>
    </div>
  );
}
