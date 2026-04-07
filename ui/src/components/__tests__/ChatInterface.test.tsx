import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionSelector } from '../SessionSelector';
import { JobContextPanel } from '../JobContextPanel';

// Mock fetch
vi.stubGlobal('fetch', vi.fn());

// ============ SESSION SELECTOR TESTS (11-02-01) ============

describe('SessionSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders with "New Session" option when no sessions exist', async () => {
    // Mock fetch to return empty sessions
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ sessions: [] })
    } as Response);

    const onSelect = vi.fn();
    render(<SessionSelector currentSessionId={null} onSelect={onSelect} />);

    const select = screen.getByRole('combobox');
    expect(select).toBeTruthy();
    expect((select as HTMLSelectElement).value).toBe('');
    expect(screen.getByText('New Session')).toBeTruthy();
  });

  it('renders saved sessions as dropdown options', async () => {
    const mockSessions = [
      { session_id: 'sess-1', display_name: 'Session sess', updated_at: 123456, job_index: 1, skill_name: null, message_count: 5 },
      { session_id: 'sess-2', display_name: 'Session sess', updated_at: 123457, job_index: null, skill_name: 'resume_swe', message_count: 10 }
    ];

    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ sessions: mockSessions })
    } as Response);

    const onSelect = vi.fn();
    render(<SessionSelector currentSessionId={null} onSelect={onSelect} />);

    // Wait for sessions to load
    await waitFor(() => {
      expect(screen.getByText('Session sess (5 msgs)')).toBeTruthy();
    });
    expect(screen.getByText('Session sess (10 msgs)')).toBeTruthy();
  });

  it('calls onSelect with session ID when session is chosen', async () => {
    const mockSessions = [
      { session_id: 'sess-1', display_name: 'Session sess', updated_at: 123456, job_index: 1, skill_name: null, message_count: 5 }
    ];

    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ sessions: mockSessions })
    } as Response);

    const onSelect = vi.fn();
    render(<SessionSelector currentSessionId={null} onSelect={onSelect} />);

    // Wait for sessions to load
    await waitFor(() => {
      expect(screen.getByText('Session sess (5 msgs)')).toBeTruthy();
    });

    const select = screen.getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'sess-1' } });

    expect(onSelect).toHaveBeenCalledWith('sess-1');
  });

  it('calls onSelect with null when "New Session" is chosen', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ sessions: [] })
    } as Response);

    const onSelect = vi.fn();
    render(<SessionSelector currentSessionId="sess-1" onSelect={onSelect} />);

    const select = screen.getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '' } });

    expect(onSelect).toHaveBeenCalledWith(null);
  });
});

// ============ JOB CONTEXT PANEL TESTS (11-02-02) ============

describe('JobContextPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns null when jobIndex is null', () => {
    const { container } = render(<JobContextPanel jobIndex={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders toggle button when jobIndex is provided', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ resume: 'Test resume', cover_letter: 'Test CL', job_name: 'Test Job' })
    } as Response);

    render(<JobContextPanel jobIndex={1} />);
    expect(screen.getByText('Show Job Context')).toBeTruthy();
  });

  it('toggles panel visibility on click', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ resume: 'Test resume', cover_letter: 'Test CL', job_name: 'Test Job' })
    } as Response);

    render(<JobContextPanel jobIndex={1} />);

    const toggle = screen.getByText('Show Job Context');
    fireEvent.click(toggle);

    // The panel shows "Resume" and "(Test Job)" separately
    await waitFor(() => {
      expect(screen.getByText('Hide Job Context')).toBeTruthy();
    });
    expect(screen.getByText(/Resume/)).toBeTruthy();
  });

  it('displays resume and cover letter when data loads', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ resume: 'My resume content', cover_letter: 'My cover letter', job_name: 'SWE Job' })
    } as Response);

    render(<JobContextPanel jobIndex={1} />);

    // Click to show panel
    fireEvent.click(screen.getByText('Show Job Context'));

    await waitFor(() => {
      expect(screen.getByText(/Resume/)).toBeTruthy();
    });
    expect(screen.getByText('My resume content')).toBeTruthy();
    expect(screen.getByText('My cover letter')).toBeTruthy();
  });

  it('shows loading state while fetching', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => new Promise(() => {})); // Never resolves

    render(<JobContextPanel jobIndex={1} />);
    fireEvent.click(screen.getByText('Show Job Context'));

    expect(screen.getByText('Loading job context...')).toBeTruthy();
  });

  it('shows error state on fetch failure', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: false,
      status: 500
    } as Response);

    render(<JobContextPanel jobIndex={1} />);
    fireEvent.click(screen.getByText('Show Job Context'));

    await waitFor(() => {
      expect(screen.getByText('Failed to load job context. Try again.')).toBeTruthy();
    });
  });
});
