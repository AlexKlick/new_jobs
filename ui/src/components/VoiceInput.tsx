import { useState, useRef, useCallback, useEffect } from 'react';

export interface VoiceInputProps {
  onTranscription: (text: string) => void;
  onError?: (error: string) => void;
  disabled?: boolean;
}

type VoiceState = 'idle' | 'recording' | 'processing';

const API_BASE = import.meta.env.VITE_VOICE_API_URL || 'http://localhost:8081';

export function VoiceInput({ onTranscription, onError, disabled = false }: VoiceInputProps) {
  const [state, setState] = useState<VoiceState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [recordingDuration, setRecordingDuration] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const MAX_DURATION = 60; // seconds

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const startRecording = useCallback(async () => {
    try {
      setErrorMessage(null);
      audioChunksRef.current = [];

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      streamRef.current = stream;

      // Try webm/opus first, fall back to wav
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/wav')
          ? 'audio/wav'
          : 'audio/webm';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        setState('processing');

        if (audioChunksRef.current.length === 0) {
          setErrorMessage('No audio recorded');
          setState('idle');
          return;
        }

        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });

        try {
          const formData = new FormData();
          formData.append('audio', audioBlob, `recording.${mimeType.split('/')[1].split(';')[0]}`);

          const response = await fetch(`${API_BASE}/api/voice`, {
            method: 'POST',
            body: formData,
          });

          if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
          }

          const data = await response.json();

          if (data.transcription) {
            onTranscription(data.transcription);
          } else if (data.error) {
            throw new Error(data.error);
          } else {
            throw new Error('No transcription in response');
          }

          setState('idle');
          setRecordingDuration(0);
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Transcription failed';
          setErrorMessage(message);
          setState('idle');
          onError?.(message);
        }
      };

      mediaRecorder.start(100); // Collect data every 100ms
      setState('recording');
      setRecordingDuration(0);

      // Start duration timer
      timerRef.current = setInterval(() => {
        setRecordingDuration((d) => {
          if (d >= MAX_DURATION - 1) {
            stopRecording();
            return MAX_DURATION;
          }
          return d + 1;
        });
      }, 1000);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to access microphone';
      setErrorMessage(message);
      setState('idle');
      onError?.(message);
    }
  }, [onTranscription, onError]);

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const handleClick = useCallback(() => {
    if (disabled) return;

    if (state === 'idle') {
      startRecording();
    } else if (state === 'recording') {
      stopRecording();
    }
    // Ignore clicks while processing
  }, [state, disabled, startRecording, stopRecording]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      if (state === 'idle' && !disabled) {
        startRecording();
      } else if (state === 'recording') {
        stopRecording();
      }
    }
  }, [state, disabled, startRecording, stopRecording]);

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getButtonClass = (): string => {
    const base = 'voice-input-btn';
    if (disabled) return `${base} disabled`;
    if (state === 'recording') return `${base} recording`;
    if (state === 'processing') return `${base} processing`;
    return base;
  };

  return (
    <div className="voice-input-container">
      <button
        type="button"
        className={getButtonClass()}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        disabled={disabled || state === 'processing'}
        aria-label={state === 'recording' ? 'Stop recording' : 'Start recording'}
        role="button"
        title={state === 'recording' ? 'Click to stop' : 'Click to record'}
      >
        {state === 'idle' && (
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          </svg>
        )}
        {state === 'recording' && (
          <div className="recording-indicator">
            <div className="pulse-ring"></div>
            <div className="pulse-dot"></div>
          </div>
        )}
        {state === 'processing' && (
          <svg className="spinner" viewBox="0 0 24 24" width="20" height="20">
            <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="31.4 31.4" />
          </svg>
        )}
      </button>

      {state === 'recording' && (
        <span className="recording-duration">{formatDuration(recordingDuration)}</span>
      )}

      {state === 'recording' && (
        <span className="voice-state-label listening">Listening...</span>
      )}

      {state === 'processing' && (
        <span className="voice-state-label processing">Transcribing...</span>
      )}

      {errorMessage && (
        <span className="voice-error">{errorMessage}</span>
      )}
    </div>
  );
}
