import { useEffect, useState } from 'react';
import { getSampleQuestions } from '../lib/api';

export function EmptyState({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  const [questions, setQuestions] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    getSampleQuestions()
      .then((res) => {
        if (!cancelled) setQuestions(res.questions.slice(0, 6));
      })
      .catch(() => {
        /* chips are a nice-to-have; stay silent if unavailable */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="empty-state">
      <h1 className="empty-title">WakiliAI</h1>
      <p className="empty-subtitle">
        Ask questions about Kenyan law — statutes, case law, court procedure and more.
        Answers are generated from indexed Kenya Law sources and are informational,
        not legal advice.
      </p>
      {questions.length > 0 && (
        <div className="chips" role="list">
          {questions.map((q) => (
            <button
              key={q}
              role="listitem"
              className="chip"
              disabled={disabled}
              onClick={() => onPick(q)}
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
