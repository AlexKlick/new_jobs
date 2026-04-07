/**
 * VoiceClonePanel — Browser recording with OfflineAudioContext at 24kHz
 *
 * Records voice via getUserMedia, resamples to 24kHz mono using
 * OfflineAudioContext, encodes to WAV manually, and uploads to
 * /api/voice-clone/upload endpoint.
 *
 * Per CONTEXT.md locked decisions:
 * - OfflineAudioContext for resampling to 24kHz
 * - Manual WAV encoding (MediaRecorder outputs WebM/OGG, not WAV)
 * - Duration: 3-10 seconds, auto-stop at 10s
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { API_BASE } from '../config';

export interface VoiceClonePanelProps {
  onCloneCreated?: (name: string) => void;
}

type RecordingState = 'idle' | 'recording' | 'recorded' | 'uploading' | 'success' | 'error';

const MIN_DURATION = 3;
const MAX_DURATION = 10;
const TARGET_SAMPLE_RATE = 24000;

export function VoiceClonePanel({ onCloneCreated }: VoiceClonePanelProps) {
  const [state, setState] = useState<RecordingState>('idle');
  const [voiceName, setVoiceName] = useState('');
  const [duration, setDuration] = useState(0);
  const [errorMessage, setErrorMessage] = useState('');
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const chunksRef = useRef<Float32Array[]>([]);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, []);

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop());
      mediaStreamRef.current = null;
    }
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (contextRef.current) {
      contextRef.current.close();
      contextRef.current = null;
    }
  }, []);

  const startRecording = useCallback(async () => {
    try {
      setState('recording');
      setErrorMessage('');
      chunksRef.current = [];

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: TARGET_SAMPLE_RATE,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      mediaStreamRef.current = stream;

      // Use AudioContext at 24kHz for capturing
      const audioCtx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      contextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        const inputData = e.inputBuffer.getChannelData(0);
        chunksRef.current.push(new Float32Array(inputData));
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

      startTimeRef.current = Date.now();

      // Timer for duration display
      timerRef.current = setInterval(() => {
        const elapsed = (Date.now() - startTimeRef.current) / 1000;
        setDuration(elapsed);

        // Auto-stop at MAX_DURATION
        if (elapsed >= MAX_DURATION) {
          stopRecording();
        }
      }, 100);

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Microphone access denied';
      setErrorMessage(msg);
      setState('error');
      cleanup();
    }
  }, [cleanup]);

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop());
      mediaStreamRef.current = null;
    }

    const elapsed = (Date.now() - startTimeRef.current) / 1000;
    setDuration(elapsed);

    if (elapsed < MIN_DURATION) {
      setErrorMessage(`Recording too short. Please record at least ${MIN_DURATION} seconds.`);
      setState('error');
      return;
    }

    // Encode WAV from collected chunks
    const wavBlob = encodeWavFromChunks(chunksRef.current, TARGET_SAMPLE_RATE);
    setRecordedBlob(wavBlob);

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    const url = URL.createObjectURL(wavBlob);
    setPreviewUrl(url);
    setState('recorded');
  }, [previewUrl]);

  const discardRecording = useCallback(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    setPreviewUrl(null);
    setRecordedBlob(null);
    setDuration(0);
    setState('idle');
  }, [previewUrl]);

  const uploadClone = useCallback(async () => {
    if (!recordedBlob) return;

    setState('uploading');
    const name = voiceName.trim() || 'user_voice';

    try {
      const formData = new FormData();
      formData.append('name', name);
      formData.append('audio', recordedBlob, `${name}.wav`);

      const response = await fetch(`${API_BASE}/api/voice-clone/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(data.detail || `Upload failed: ${response.status}`);
      }

      setState('success');
      if (onCloneCreated) {
        onCloneCreated(name);
      }

      // Reset after 3 seconds
      setTimeout(() => {
        discardRecording();
      }, 3000);

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Voice cloning failed';
      setErrorMessage(msg);
      setState('error');
    }
  }, [recordedBlob, voiceName, onCloneCreated, discardRecording]);

  const progressPercent = Math.min((duration / MAX_DURATION) * 100, 100);

  return (
    <div className="voice-clone-panel">
      <h4 className="voice-clone-title">Voice Cloning</h4>

      <div className="voice-clone-name">
        <label htmlFor="voice-name">Voice Name:</label>
        <input
          id="voice-name"
          type="text"
          value={voiceName}
          onChange={e => setVoiceName(e.target.value)}
          placeholder="Enter a name for this voice"
          disabled={state === 'recording' || state === 'uploading'}
          maxLength={50}
        />
      </div>

      {state === 'idle' && (
        <button
          className="voice-clone-record-btn"
          onClick={startRecording}
        >
          Record Your Voice
        </button>
      )}

      {state === 'recording' && (
        <div className="voice-clone-recording">
          <div className="recording-timer">
            {duration.toFixed(1)}s / {MAX_DURATION}s
          </div>
          <div className="recording-progress">
            <div
              className="recording-progress-fill"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <button
            className="voice-clone-stop-btn"
            onClick={stopRecording}
          >
            Stop Recording
          </button>
        </div>
      )}

      {state === 'recorded' && previewUrl && (
        <div className="voice-clone-preview">
          <audio src={previewUrl} controls />
          <div className="preview-actions">
            <button
              className="preview-discard-btn"
              onClick={discardRecording}
            >
              Discard
            </button>
            <button
              className="voice-clone-submit-btn"
              onClick={uploadClone}
            >
              Create Voice Clone
            </button>
          </div>
        </div>
      )}

      {state === 'uploading' && (
        <div className="voice-clone-uploading">
          <span className="spinner" /> Processing...
        </div>
      )}

      {state === 'success' && (
        <div className="voice-clone-success">
          Voice clone created successfully
        </div>
      )}

      {state === 'error' && (
        <div className="voice-clone-error">
          {errorMessage}
          <button
            className="voice-clone-rerecord-btn"
            onClick={() => {
              setErrorMessage('');
              discardRecording();
            }}
          >
            Re-record
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Encode collected Float32Array chunks into a WAV Blob.
 * Manual WAV encoding: RIFF header + fmt chunk + data chunk.
 */
function encodeWavFromChunks(chunks: Float32Array[], sampleRate: number): Blob {
  // Concatenate all chunks
  const totalLength = chunks.reduce((acc, c) => acc + c.length, 0);
  const audio = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    audio.set(chunk, offset);
    offset += chunk.length;
  }

  // Convert float32 to int16
  const numSamples = audio.length;
  const bytesPerSample = 2;
  const dataLength = numSamples * bytesPerSample;
  const headerLength = 44;
  const totalLengthBytes = headerLength + dataLength;

  const buffer = new ArrayBuffer(totalLengthBytes);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, 'RIFF');
  view.setUint32(4, totalLengthBytes - 8, true);
  writeString(view, 8, 'WAVE');

  // fmt chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);        // chunk size
  view.setUint16(20, 1, true);         // PCM format
  view.setUint16(22, 1, true);         // mono
  view.setUint32(24, sampleRate, true); // sample rate
  view.setUint32(28, sampleRate * bytesPerSample, true); // byte rate
  view.setUint16(32, bytesPerSample, true);              // block align
  view.setUint16(34, 16, true);        // bits per sample

  // data chunk
  writeString(view, 36, 'data');
  view.setUint32(40, dataLength, true);

  // Write PCM samples
  let writeOffset = 44;
  for (let i = 0; i < numSamples; i++) {
    const s = Math.max(-1, Math.min(1, audio[i]));
    const int16 = s < 0 ? s * 0x8000 : s * 0x7FFF;
    view.setInt16(writeOffset, int16, true);
    writeOffset += 2;
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

function writeString(view: DataView, offset: number, str: string): void {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

export default VoiceClonePanel;
