import ReactMarkdown from 'react-markdown';
import type { Source } from '../lib/api';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  sources?: Source[];
  isError?: boolean;
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg-row msg-row-user">
        <div className="msg-bubble msg-user">{message.text}</div>
      </div>
    );
  }
  return (
    <div className="msg-row msg-row-assistant">
      <div className={`msg-bubble msg-assistant${message.isError ? ' msg-error' : ''}`}>
        <div className="markdown">
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
        {message.sources && message.sources.length > 0 && (
          <div className="msg-sources">
            <span className="msg-sources-label">Sources</span>
            <ul>
              {message.sources.map((s, i) => (
                <li key={i}>
                  <a href={s.url} target="_blank" rel="noreferrer">
                    {s.title?.trim() || s.url}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="msg-row msg-row-assistant">
      <div className="msg-bubble msg-assistant typing" aria-label="Assistant is responding">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
    </div>
  );
}
