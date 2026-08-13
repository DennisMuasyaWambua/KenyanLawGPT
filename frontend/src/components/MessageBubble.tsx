import ReactMarkdown from 'react-markdown';
import type { Source } from '../lib/api';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  sources?: Source[];
  isError?: boolean;
  /** Chain-of-thought from a reasoning model, shown as a "thinking…" panel. */
  reasoning?: string;
  /** True while tokens are still arriving for this message. */
  streaming?: boolean;
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg-row msg-row-user">
        <div className="msg-bubble msg-user">{message.text}</div>
      </div>
    );
  }
  // While reasoning is arriving but the answer hasn't started, keep the panel
  // open so the user sees live "thinking…"; collapse it once the answer flows.
  const hasReasoning = !!message.reasoning?.trim();
  const answerStarted = message.text.trim().length > 0;
  return (
    <div className="msg-row msg-row-assistant">
      <div className={`msg-bubble msg-assistant${message.isError ? ' msg-error' : ''}`}>
        {hasReasoning && (
          <details className="msg-thinking" open={message.streaming && !answerStarted}>
            <summary>
              {message.streaming && !answerStarted ? 'Thinking…' : 'Thought process'}
            </summary>
            <div className="msg-thinking-body">{message.reasoning}</div>
          </details>
        )}
        {answerStarted ? (
          <div className="markdown">
            <ReactMarkdown>{message.text}</ReactMarkdown>
            {message.streaming && <span className="stream-caret" aria-hidden="true" />}
          </div>
        ) : (
          // No answer text yet: show live dots (unless the thinking panel is
          // already conveying activity above).
          message.streaming && !hasReasoning && (
            <div className="typing" aria-label="Assistant is responding">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          )
        )}
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
