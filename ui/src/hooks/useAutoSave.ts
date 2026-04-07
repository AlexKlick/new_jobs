import { useEffect, useRef, useCallback, useState } from 'react';

interface UseAutoSaveOptions<T> {
  data: T;
  onSave: (data: T) => Promise<void>;
  delay?: number; // debounce delay in ms, default 1500
  enabled?: boolean;
}

export function useAutoSave<T>({
  data,
  onSave,
  delay = 1500,
  enabled = true,
}: UseAutoSaveOptions<T>) {
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevDataRef = useRef<string>(JSON.stringify(data));

  // Deep compare data for dirtiness
  useEffect(() => {
    const current = JSON.stringify(data);
    if (current !== prevDataRef.current) {
      setIsDirty(true);
      prevDataRef.current = current;
    }
  }, [data]);

  const save = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await onSave(data);
      setLastSaved(new Date());
      setIsDirty(false);
      prevDataRef.current = JSON.stringify(data);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setIsSaving(false);
    }
  }, [data, onSave]);

  // Auto-save on change with debounce
  useEffect(() => {
    if (!enabled || !isDirty) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      save();
    }, delay);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isDirty, enabled, delay, save]);

  const saveNow = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    save();
  }, [save]);

  // Warn on navigate-away with unsaved changes
  useEffect(() => {
    if (!isDirty) return;

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };

    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  return {
    isDirty,
    isSaving,
    lastSaved,
    saveError,
    saveNow,
  };
}
