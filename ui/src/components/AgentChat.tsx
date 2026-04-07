import { useState, useCallback, useRef, useEffect } from 'react';
import { RollbackButton } from './RollbackButton';
import { CircuitBreakerBanner } from './CircuitBreakerBanner';
import { API_BASE } from '../config';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  checkpoint_id?: string;
}

type AgentState = 'idle' | 'executing' | 'success' | 'error' | 'circuit-open';

interface AgentResponse {
  success: boolean;
  response: string;
  checkpoint_id?: string;
  error?: string;
  circuit_breaker_open: boolean;
  iterations_used: number;
  timeout_occurred: boolean;
  resets_in_s?: number;
}

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [agentState, setAgentState] = useState<AgentState>('idle');
  const [circuitStatus, setCircuitStatus] = useState<{ open: boolean; resets_in_s?: number }>({ open: false });
  const [lastCheckpointId, setLastCheckpointId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendAgentRequest = useCallback(async (instruction: string) => {
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: instruction,
    };

    setMessages(prev => [...prev, userMessage]);
    setInputText('');
    setAgentState('executing');

    try {
      const response = await fetch(`${API_BASE}/api/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instruction,
          job_index: null,
        }),
      });

      const data: AgentResponse = await response.json();

      if (data.circuit_breaker_open) {
        setAgentState('circuit-open');
        setCircuitStatus({ open: true, resets_in_s: data.resets_in_s ?? 300 });
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Circuit breaker open: ${data.error || 'Too many escalation attempts'}`,
        };
        setMessages(prev => [...prev, errorMessage]);
        return;
      }

      if (!data.success) {
        setAgentState('error');
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Error: ${data.error || 'Unknown error'}`,
        };
        setMessages(prev => [...prev, errorMessage]);
        return;
      }

      // Success
      setAgentState('success');
      setLastCheckpointId(data.checkpoint_id || null);

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.response || 'Changes have been applied.',
        checkpoint_id: data.checkpoint_id,
      };
      setMessages(prev => [...prev, assistantMessage]);

      // Reset to idle after a delay
      setTimeout(() => setAgentState('idle'), 2000);

    } catch (err) {
      setAgentState('error');
      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Request failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
      };
      setMessages(prev => [...prev, errorMessage]);
    }
  }, []);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (inputText.trim() && agentState === 'idle') {
      sendAgentRequest(inputText.trim());
    }
  }, [inputText, agentState, sendAgentRequest]);

  const handleRollback = useCallback(async (checkpointId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/agent/rollback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkpoint_id: checkpointId }),
      });

      const data = await response.json();

      if (data.success) {
        const rollbackMessage: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Rolled back changes. File has been restored.`,
        };
        setMessages(prev => [...prev, rollbackMessage]);
        setLastCheckpointId(null);
      } else {
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Rollback failed: ${data.error}`,
        };
        setMessages(prev => [...prev, errorMessage]);
      }
    } catch (err) {
      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Rollback request failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
      };
      setMessages(prev => [...prev, errorMessage]);
    }
  }, []);

  const getAgentStateLabel = (): string => {
    switch (agentState) {
      case 'executing':
        return 'Working on it...';
      case 'success':
        return 'Done!';
      case 'error':
        return 'Error';
      case 'circuit-open':
        return 'Circuit breaker open';
      default:
        return '';
    }
  };

  return (
    <div className="chat-interface agent-chat">
      <div className="chat-header">
        <h2>Agent Assistant</h2>
      </div>

      {agentState === 'circuit-open' && (
        <CircuitBreakerBanner resetsIn={circuitStatus.resets_in_s ?? 300} />
      )}

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty-state">
            <h3>Ready to assist</h3>
            <p>Describe what you want changed - I'll update your resume, cover letter, or skills.</p>
          </div>
        )}

        {messages.map(message => (
          <div key={message.id} className={`chat-message ${message.role}`}>
            <div className="message-avatar">
              {message.role === 'user' ? 'You' : 'Agent'}
            </div>
            <div className="message-content">
              {message.content}
              {message.role === 'assistant' && message.checkpoint_id && lastCheckpointId === message.checkpoint_id && (
                <RollbackButton
                  checkpointId={message.checkpoint_id}
                  onRollback={handleRollback}
                  disabled={agentState !== 'idle'}
                />
              )}
            </div>
          </div>
        ))}

        <div ref={messagesEndRef} />
      </div>

      {agentState !== 'idle' && (
        <div className={`status-indicator ${agentState}`}>
          <span className="spinner"></span>
          <span className="status-text">{getAgentStateLabel()}</span>
        </div>
      )}

      <form className="chat-input-area" onSubmit={handleSubmit}>
        <textarea
          className="chat-text-input"
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          placeholder="Describe what you want changed..."
          disabled={agentState !== 'idle' && agentState !== 'circuit-open'}
          rows={2}
        />

        <button
          type="submit"
          className="chat-send-btn agent-submit-btn"
          disabled={!inputText.trim() || (agentState !== 'idle' && agentState !== 'circuit-open')}
        >
          Make it happen
        </button>
      </form>
    </div>
  );
}
