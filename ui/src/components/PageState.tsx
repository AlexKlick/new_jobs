/**
 * Shared page-state components for consistent UX across v1.2 surfaces.
 *
 * Every data-driven page should use these patterns so empty, loading,
 * error, and stale states look and behave the same everywhere.
 */

// ── Page Shell ─────────────────────────────────────────────────────────────────

interface PageShellProps {
  title: string;
  children: React.ReactNode;
}

export function PageShell({ title, children }: PageShellProps) {
  return (
    <div className="page-shell">
      <h2 className="page-shell-title">{title}</h2>
      {children}
    </div>
  );
}

// ── Empty State ────────────────────────────────────────────────────────────────

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="page-state page-state-empty" role="status">
      {icon && <span className="page-state-icon" aria-hidden="true">{icon}</span>}
      <span className="page-state-title">{title}</span>
      {description && <span className="page-state-desc">{description}</span>}
      {action && <div className="page-state-action">{action}</div>}
    </div>
  );
}

// ── Loading State ──────────────────────────────────────────────────────────────

interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message = 'Loading...' }: LoadingStateProps) {
  return (
    <div className="page-state page-state-loading" role="status" aria-live="polite">
      <span className="page-state-spinner" aria-hidden="true" />
      <span className="page-state-title">{message}</span>
    </div>
  );
}

// ── Error State ────────────────────────────────────────────────────────────────

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="page-state page-state-error" role="alert">
      <span className="page-state-icon" aria-hidden="true">!</span>
      <span className="page-state-title">{message}</span>
      {onRetry && (
        <button className="page-state-retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

// ── Stale Indicator ────────────────────────────────────────────────────────────

interface StaleIndicatorProps {
  lastRefreshed: string | null;
  isStale: boolean;
}

export function StaleIndicator({ lastRefreshed, isStale }: StaleIndicatorProps) {
  if (!lastRefreshed) return null;
  const label = isStale ? `Data may be stale (last refreshed ${lastRefreshed})` : `Last refreshed ${lastRefreshed}`;
  return (
    <span
      className={`page-state-stale ${isStale ? 'stale' : ''}`}
      title={label}
      role="status"
    >
      {label}
    </span>
  );
}
