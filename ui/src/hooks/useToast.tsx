import { createContext, useContext, useCallback, useState, useEffect, type ReactNode } from 'react';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastContextValue {
  addToast: (type: ToastType, message: string) => void;
}

const ToastContext = createContext<ToastContextValue>({ addToast: () => {} });

export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}

// Singleton store for toast state — shared across the app
const toastListeners = new Set<(toasts: Toast[]) => void>();
let toastQueue: Toast[] = [];

function notify(listeners: typeof toastListeners, queue: Toast[]) {
  listeners.forEach(fn => fn(queue));
}

export function addToastToQueue(type: ToastType, message: string) {
  const id = crypto.randomUUID();
  toastQueue = [...toastQueue, { id, type, message }];
  notify(toastListeners, toastQueue);

  // Auto-dismiss after 4 seconds
  setTimeout(() => {
    toastQueue = toastQueue.filter(t => t.id !== id);
    notify(toastListeners, toastQueue);
  }, 4000);
}

export function useToastQueue(): Toast[] {
  const [toasts, setToasts] = useState<Toast[]>(toastQueue);
  useEffect(() => {
    const listener = (queue: Toast[]) => setToasts([...queue]);
    toastListeners.add(listener);
    return () => { toastListeners.delete(listener); };
  }, []);
  return toasts;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const addToast = useCallback((type: ToastType, message: string) => {
    addToastToQueue(type, message);
  }, []);

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
    </ToastContext.Provider>
  );
}
