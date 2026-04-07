import { useState, useEffect, useCallback, useRef } from 'react';
import { VoiceInput } from './VoiceInput';
import { TtsToggle } from './TtsToggle';
import { JobSwitcher } from './JobSwitcher';
import { SessionSelector } from './SessionSelector';
import { JobContextPanel } from './JobContextPanel';
import { VoiceClonePanel } from './VoiceClonePanel';
import { VoiceSelector } from './VoiceSelector';
import { EngineLoadingIndicator } from './EngineLoadingIndicator';
import { CacheStatusBadge } from './CacheStatusBadge';
import { API_BASE } from '../config';
import '../styles/voice-clone.css';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

type ProcessingState = 'idle' | 'recording' | 'transcribing' | 'thinking' | 'speaking';

interface ChatInterfaceProps {
  initialJobIndex?: number | null;
}

const TTS_API_BASE = API_BASE;
const STORAGE_KEY = 'tts_enabled';
const SESSION_STORAGE_KEY = 'last_chat_session_id';
const SKILLS_API = '/api/skills';

export function ChatInterface({ initialJobIndex = null }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [processingState, setProcessingState] = useState<ProcessingState>('idle');
  const [selectedJobIndex, setSelectedJobIndex] = useState<number | null>(initialJobIndex);
  const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === null || stored === 'true';
    }
    return true;
  });
  const [sessionId, setSessionId] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(SESSION_STORAGE_KEY);
    }
    return null;
  });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [skillJobType, setSkillJobType] = useState<string | null>(null);
  const [skillFiles, setSkillFiles] = useState<{ name: string; modified: number; size: number }[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string>('carter');
  const [cacheStatus, setCacheStatus] = useState<'HIT' | 'MISS' | null>(null);
  const [engineLoading, setEngineLoading] = useState(false);

  const filteredSkillFiles = skillJobType
    ? skillFiles.filter(sf => {
        const name = sf.name.toLowerCase();
        if (skillJobType === 'swe') return name.includes('swe') || (!name.includes('ml') && !name.includes('consulting'));
        if (skillJobType === 'ml') return name.includes('ml');
        if (skillJobType === 'consulting') return name.includes('consulting');
        return true;
      })
    : skillFiles;

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load skill list on mount
  useEffect(() => {
    async function loadSkills() {
      try {
        const res = await fetch(`${SKILLS_API}`);
        if (res.ok) {
          const data = await res.json();
          setSkillFiles(data.skills || []);
        }
      } catch {
        // skills not available - non-fatal
      }
    }
    loadSkills();
  }, []);

  const handleTtsChange = useCallback((enabled: boolean) => {
    setTtsEnabled(enabled);
    localStorage.setItem(STORAGE_KEY, String(enabled));
  }, []);

  const handleJobSelect = useCallback((index: number | null) => {
    setSelectedJobIndex(index);
    // Clear conversation when switching jobs
    setMessages([]);
  }, []);

  const handleSessionSelect = useCallback((newSessionId: string | null) => {
    if (newSessionId === sessionId) return;

    if (newSessionId) {
      // Load existing session
      fetch(`${API_BASE}/api/sessions/${newSessionId}`)
        .then(r => r.json())
        .then(data => {
          setMessages(data.messages.map((m: any) => ({
            id: crypto.randomUUID(),
            role: m.role,
            content: m.content
          })));
          setSelectedJobIndex(data.job_index);
          setSelectedSkill(data.skill_name);
          setSkillJobType(data.skill_job_type || null);
          setSessionId(newSessionId);
          localStorage.setItem(SESSION_STORAGE_KEY, newSessionId);
        });
    } else {
      // New session
      setMessages([]);
      setSelectedJobIndex(null);
      setSelectedSkill(null);
      setSkillJobType(null);
      setSessionId(null);
      localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }, [sessionId]);

  const playAudio = useCallback(async (audioUrl: string) => {
    if (!ttsEnabled) return;

    try {
      setProcessingState('speaking');
      const audio = new Audio(audioUrl);
      audioRef.current = audio;

      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        setProcessingState('idle');
      };

      audio.onerror = () => {
        console.error('Audio playback failed');
        setProcessingState('idle');
      };

      await audio.play();
    } catch (err) {
      console.error('Failed to play audio:', err);
      setProcessingState('idle');
    }
  }, [ttsEnabled]);

  const callTtsApi = useCallback(async (text: string) => {
    if (!ttsEnabled) return null;

    try {
      const response = await fetch(`${TTS_API_BASE}/api/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: selectedVoice }),
      });

      if (!response.ok) {
        throw new Error(`TTS API error: ${response.status}`);
      }

      // Check cache status from response header
      const cacheHeader = response.headers.get('X-Cache');
      setCacheStatus(cacheHeader === 'HIT' ? 'HIT' : 'MISS');

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      return url;
    } catch (err) {
      console.error('TTS API call failed:', err);
      return null;
    }
  }, [ttsEnabled]);

  const sendTextMessage = useCallback(async (text: string) => {
    if (!text.trim()) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text.trim(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInputText('');
    setProcessingState('thinking');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text.trim(),
          job_index: selectedJobIndex,
          session_id: sessionId,
          skill_name: selectedSkill,
        }),
      });

      if (!response.ok) {
        throw new Error(`Chat API error: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.response,
      };

      setMessages(prev => [...prev, assistantMessage]);

      // Handle TTS
      if (data.audio_url) {
        await playAudio(data.audio_url);
      } else {
        // Try to generate TTS
        const audioUrl = await callTtsApi(data.response);
        if (audioUrl) {
          await playAudio(audioUrl);
        } else {
          setProcessingState('idle');
        }
      }
    } catch (err) {
      console.error('Chat API call failed:', err);

      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to get response'}`,
      };

      setMessages(prev => [...prev, errorMessage]);
      setProcessingState('idle');
    }
  }, [selectedJobIndex, sessionId, playAudio, callTtsApi, ttsEnabled]);

  const handleVoiceTranscription = useCallback(async (text: string) => {
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: `🎤 ${text}`,
    };

    setMessages(prev => [...prev, userMessage]);
    setProcessingState('thinking');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          job_index: selectedJobIndex,
          session_id: sessionId,
          skill_name: selectedSkill,
        }),
      });

      if (!response.ok) {
        throw new Error(`Chat API error: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.response,
      };

      setMessages(prev => [...prev, assistantMessage]);

      // Handle TTS
      if (data.audio_url) {
        await playAudio(data.audio_url);
      } else {
        const audioUrl = await callTtsApi(data.response);
        if (audioUrl) {
          await playAudio(audioUrl);
        } else {
          setProcessingState('idle');
        }
      }
    } catch (err) {
      console.error('Voice chat API call failed:', err);

      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to get response'}`,
      };

      setMessages(prev => [...prev, errorMessage]);
      setProcessingState('idle');
    }
  }, [selectedJobIndex, sessionId, playAudio, callTtsApi, ttsEnabled]);

  const handleVoiceError = useCallback((error: string) => {
    const errorMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: `Voice error: ${error}`,
    };
    setMessages(prev => [...prev, errorMessage]);
  }, []);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (inputText.trim() && processingState === 'idle') {
      sendTextMessage(inputText);
    }
  }, [inputText, processingState, sendTextMessage]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputText.trim() && processingState === 'idle') {
        sendTextMessage(inputText);
      }
    }
  }, [inputText, processingState, sendTextMessage]);

  const getProcessingLabel = (): string => {
    switch (processingState) {
      case 'recording':
        return 'Listening...';
      case 'transcribing':
        return 'Transcribing...';
      case 'thinking':
        return 'Thinking...';
      case 'speaking':
        return 'Speaking...';
      default:
        return '';
    }
  };

  const getStatusIndicatorClass = (): string => {
    return `status-indicator ${processingState !== 'idle' ? 'active' : ''} ${processingState}`;
  };

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <SessionSelector
          currentSessionId={sessionId}
          onSelect={handleSessionSelect}
        />
        <JobSwitcher
          jobs={[]}
          selectedIndex={selectedJobIndex}
          onSelect={handleJobSelect}
        />
        <div className="chat-skill-filter">
          <select
            value={skillJobType ?? ''}
            onChange={e => setSkillJobType(e.target.value || null)}
          >
            <option value="">All Skills</option>
            <option value="swe">SWE</option>
            <option value="ml">ML</option>
            <option value="consulting">Consulting</option>
          </select>
        </div>
        <div className="chat-skill-selector">
          <label htmlFor="skill-select">Skill:</label>
          <select
            id="skill-select"
            value={selectedSkill ?? ''}
            onChange={e => setSelectedSkill(e.target.value || null)}
          >
            <option value="">Default</option>
            {filteredSkillFiles.map(sf => (
              <option key={sf.name} value={sf.name}>{sf.name}</option>
            ))}
          </select>
        </div>
        <TtsToggle enabled={ttsEnabled} onChange={handleTtsChange} />
        <VoiceSelector
          selectedVoice={selectedVoice}
          onVoiceChange={setSelectedVoice}
          onEngineWarm={() => setEngineLoading(true)}
        />
        <CacheStatusBadge cacheStatus={cacheStatus} />
      </div>

      <EngineLoadingIndicator visible={engineLoading} />

      <VoiceClonePanel
        onCloneCreated={() => setEngineLoading(false)}
      />

      <JobContextPanel jobIndex={selectedJobIndex} />

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty-state">
            <h3>Start a conversation</h3>
            <p>Select a job from the switcher above to discuss a specific application, or ask about anything else.</p>
          </div>
        )}

        {messages.map(message => (
          <div key={message.id} className={`chat-message ${message.role}`}>
            <div className="message-avatar">
              {message.role === 'user' ? '👤' : '🤖'}
            </div>
            <div className="message-content">
              {message.content}
            </div>
          </div>
        ))}

        <div ref={messagesEndRef} />
      </div>

      {processingState !== 'idle' && (
        <div className={getStatusIndicatorClass()}>
          {processingState === 'thinking' && <span className="thinking-dots">...</span>}
          {processingState === 'transcribing' && <span className="spinner"></span>}
          {processingState === 'recording' && <span className="pulse"></span>}
          {processingState === 'speaking' && <span className="speaker-icon">🔊</span>}
          <span className="status-text">{getProcessingLabel()}</span>
        </div>
      )}

      <form className="chat-input-area" onSubmit={handleSubmit}>
        <VoiceInput
          onTranscription={handleVoiceTranscription}
          onError={handleVoiceError}
          disabled={processingState !== 'idle'}
        />

        <textarea
          className="chat-text-input"
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          disabled={processingState !== 'idle'}
          rows={1}
        />

        <button
          type="submit"
          className="chat-send-btn"
          disabled={!inputText.trim() || processingState !== 'idle'}
          aria-label="Send message"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </form>
    </div>
  );
}
