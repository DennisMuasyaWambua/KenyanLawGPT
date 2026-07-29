import { useEffect, useRef, useState } from 'react';
import { sendChat, ApiError } from './lib/api';
import { useBackendStatus } from './hooks/useBackendStatus';
import { StatusBadge } from './components/StatusBadge';
import { MessageBubble, TypingIndicator, type ChatMessage } from './components/MessageBubble';
import { EmptyState } from './components/EmptyState';
import { AdminDrawer } from './components/AdminDrawer';
import { Toast, type ToastData } from './components/Toast';

const MODELS = ['llama3', 'llama3.2:1b'];

let nextId = 0;
const uid = () => `m${++nextId}`;

export default function App() {
  const status = useBackendStatus();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState(MODELS[0]);
  const [pending, setPending] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const backendReady = status.state === 'ready';
  const canSend = backendReady && !pending && input.trim().length > 0;

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, pending]);

  const notify = (kind: 'success' | 'error', text: string) => {
    setToast({ kind, text });
    window.setTimeout(() => setToast(null), 6000);
  };

  const submit = async (text: string) => {
    const query = text.trim();
    if (!query || pending || !backendReady) return;
    setMessages((m) => [...m, { id: uid(), role: 'user', text: query }]);
    setInput('');
    setPending(true);
    try {
      const res = await sendChat(query, model);
      setMessages((m) => [
        ...m,
        { id: uid(), role: 'assistant', text: res.response, sources: res.sources },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.kind === 'timeout'
            ? 'The assistant took too long to respond. Please try again — shorter questions or the smaller model may help.'
            : err.message
          : 'Something went wrong.';
      setMessages((m) => [...m, { id: uid(), role: 'assistant', text: msg, isError: true }]);
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-name">WakiliAI</span>
          <span className="brand-tag">Kenya Law Assistant</span>
        </div>
        <div className="header-actions">
          <StatusBadge status={status} />
          <label className="model-select">
            <span className="visually-hidden">Model</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {MODELS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-ghost" onClick={() => setDrawerOpen(true)}>
            Admin
          </button>
        </div>
      </header>

      <main className="thread" ref={threadRef}>
        <div className="thread-inner">
          {messages.length === 0 && !pending ? (
            <EmptyState onPick={submit} disabled={!backendReady} />
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}
          {pending && <TypingIndicator />}
        </div>
      </main>

      <footer className="composer">
        <div className="composer-inner">
          {!backendReady && (
            <div className={`composer-notice notice-${status.state}`}>{status.message}</div>
          )}
          <div className="composer-box">
            <textarea
              ref={inputRef}
              rows={1}
              placeholder={
                backendReady ? 'Ask about Kenyan law…' : 'Waiting for the backend…'
              }
              value={input}
              disabled={!backendReady || pending}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button
              className="btn btn-primary send-btn"
              disabled={!canSend}
              onClick={() => submit(input)}
            >
              Send
            </button>
          </div>
          <p className="composer-disclaimer">
            WakiliAI provides legal information, not legal advice. Verify against primary
            sources.
          </p>
        </div>
      </footer>

      <AdminDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} notify={notify} />
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
