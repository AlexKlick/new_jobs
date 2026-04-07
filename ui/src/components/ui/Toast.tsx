import { CheckCircle, XCircle, Info, X } from 'lucide-react';
import { useToastQueue, type Toast } from '../../hooks/useToast';

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const icons = {
    success: <CheckCircle size={18} className="text-success flex-shrink-0" />,
    error: <XCircle size={18} className="text-danger flex-shrink-0" />,
    info: <Info size={18} className="text-accent flex-shrink-0" />,
  };

  const bgColors = {
    success: 'bg-success/10 border-success/30',
    error: 'bg-danger/10 border-danger/30',
    info: 'bg-accent/10 border-accent/30',
  };

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-lg border ${bgColors[toast.type]} backdrop-blur-sm shadow-lg animate-slide-in`}
      role="alert"
    >
      {icons[toast.type]}
      <span className="text-sm text-text-primary flex-1">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-text-muted hover:text-text-primary transition-colors"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useToastQueue();

  const dismiss = (_id: string) => {
    // Auto-dismiss is handled by the hook; this is a no-op to satisfy the callback
  };

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </div>
  );
}
