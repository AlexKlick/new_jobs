/**
 * VoiceSelector — Grouped dropdown for preset and cloned voices
 *
 * Fetches voice list from /api/voices and displays grouped options.
 * Selecting a cloned voice triggers MOSS engine pre-warm.
 */

import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../config';

export interface VoiceOption {
  id: string;
  name: string;
  type: 'preset' | 'cloned';
}

interface VoiceSelectorProps {
  selectedVoice: string;
  onVoiceChange: (voice: string) => void;
  onEngineWarm?: () => void;
}

export function VoiceSelector({
  selectedVoice,
  onVoiceChange,
  onEngineWarm,
}: VoiceSelectorProps) {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch voices on mount
  useEffect(() => {
    loadVoices();
  }, []);

  const loadVoices = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/voices`);
      if (res.ok) {
        const data = await res.json();
        setVoices(data.voices || []);
      }
    } catch {
      // Non-fatal: voices may not be available
    } finally {
      setLoading(false);
    }
  };

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const voiceId = e.target.value;
      onVoiceChange(voiceId);

      // Trigger MOSS pre-warm if cloned voice selected
      if (voiceId.startsWith('clone:') && onEngineWarm) {
        onEngineWarm();
      }
    },
    [onVoiceChange, onEngineWarm]
  );

  const presetVoices = voices.filter(v => v.type === 'preset');
  const clonedVoices = voices.filter(v => v.type === 'cloned');

  if (loading) {
    return (
      <div className="voice-selector">
        <label htmlFor="voice-select">Voice:</label>
        <select id="voice-select" disabled>
          <option>Loading voices...</option>
        </select>
      </div>
    );
  }

  return (
    <div className="voice-selector">
      <label htmlFor="voice-select">Voice:</label>
      <select
        id="voice-select"
        value={selectedVoice}
        onChange={handleChange}
      >
        {presetVoices.length > 0 && (
          <optgroup label="Preset Voices">
            {presetVoices.map(v => (
              <option key={v.id} value={v.id}>
                VibeVoice — {v.name}
              </option>
            ))}
          </optgroup>
        )}
        {clonedVoices.length > 0 && (
          <optgroup label="Cloned Voices">
            {clonedVoices.map(v => (
              <option key={v.id} value={v.id}>
                Cloned — {v.name}
              </option>
            ))}
          </optgroup>
        )}
        {voices.length === 0 && (
          <option value="carter">Default (carter)</option>
        )}
      </select>
    </div>
  );
}

export default VoiceSelector;
