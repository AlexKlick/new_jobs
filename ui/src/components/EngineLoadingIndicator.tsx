/**
 * EngineLoadingIndicator — Shows MOSS-TTS engine loading state
 *
 * Polls /api/tts/engine/status to display loading progress.
 * States: hidden (preset_only), loading (amber progress), ready (green flash).
 */

import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

type EngineState = 'preset_only' | 'loading_moss' | 'both_loaded' | 'unloading_moss';

interface EngineLoadingIndicatorProps {
  visible: boolean;
}

const POLL_INTERVAL_MS = 2000;

export function EngineLoadingIndicator({ visible }: EngineLoadingIndicatorProps) {
  const [engineState, setEngineState] = useState<EngineState>('preset_only');
  const [progress, setProgress] = useState(0);
  const [showReady, setShowReady] = useState(false);

  useEffect(() => {
    if (!visible) {
      setEngineState('preset_only');
      return;
    }

    // Poll engine status
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tts/engine/status`);
        if (res.ok) {
          const data = await res.json();
          const state = data.state as EngineState;
          setEngineState(state);

          if (state === 'loading_moss') {
            setProgress(prev => Math.min(prev + 15, 90));
          } else if (state === 'both_loaded') {
            setProgress(100);
            setShowReady(true);
            setTimeout(() => setShowReady(false), 3000);
          } else {
            setProgress(0);
          }
        }
      } catch {
        // Non-fatal polling error
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [visible]);

  if (!visible || engineState === 'preset_only') {
    return null;
  }

  if (engineState === 'unloading_moss') {
    return null;
  }

  if (showReady) {
    return (
      <div className="engine-loading-indicator engine-ready">
        Voice cloning engine ready
      </div>
    );
  }

  if (engineState === 'loading_moss') {
    return (
      <div className="engine-loading-indicator engine-loading">
        <span className="engine-loading-text">
          Loading voice cloning engine... {progress}%
        </span>
        <div className="engine-progress-bar">
          <div
            className="engine-progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    );
  }

  return null;
}

export default EngineLoadingIndicator;
