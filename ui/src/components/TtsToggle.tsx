import { useState, useEffect, useCallback } from 'react';

export interface TtsToggleProps {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
}

const STORAGE_KEY = 'tts_enabled';

export function TtsToggle({ enabled: initialEnabled, onChange }: TtsToggleProps) {
  const [isEnabled, setIsEnabled] = useState<boolean>(() => {
    // Read from localStorage on mount
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        return stored === 'true';
      }
    }
    // Default to true if no stored value
    return true;
  });

  // Sync with prop when it changes externally
  useEffect(() => {
    setIsEnabled(initialEnabled);
  }, [initialEnabled]);

  const handleToggle = useCallback(() => {
    const newValue = !isEnabled;
    setIsEnabled(newValue);
    localStorage.setItem(STORAGE_KEY, String(newValue));
    onChange(newValue);
  }, [isEnabled, onChange]);

  return (
    <button
      type="button"
      className={`tts-toggle ${isEnabled ? 'enabled' : 'disabled'}`}
      onClick={handleToggle}
      aria-label={isEnabled ? 'Disable text-to-speech' : 'Enable text-to-speech'}
      title={isEnabled ? 'TTS On - Click to disable' : 'TTS Off - Click to enable'}
    >
      {isEnabled ? (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <path d="M3 9v6h4l5 5V4L7 9H3z" />
          <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
          <path d="M14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63z" />
          <path d="M19 12h2c0-4.97-4.03-9-9-9v2c3.87 0 7 3.13 7 7zm-3 9H3v-6h4l5-5v11l-5-5z" />
          <line x1="1" y1="1" x2="23" y2="23" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )}
      <span className="tts-label">{isEnabled ? 'TTS On' : 'TTS Off'}</span>
    </button>
  );
}
