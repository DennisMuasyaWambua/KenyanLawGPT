import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { createCase, listCases, type Case } from '../lib/gateway';
import { ApiError } from '../lib/api';

export function CasesPage() {
  const [cases, setCases] = useState<Case[]>([]);
  const [title, setTitle] = useState('');
  const [reference, setReference] = useState('');
  const [error, setError] = useState('');

  const refresh = () => {
    listCases().then(setCases).catch(() => {});
  };
  useEffect(refresh, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await createCase({ title, reference });
      setTitle('');
      setReference('');
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create case.');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Cases</h1>
          <p className="page-sub">Matters and the documents that ground the assistant’s reasoning.</p>
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">New case</h2>
        <form className="inline-form" onSubmit={add}>
          <input placeholder="Case title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          <input placeholder="Reference (optional)" value={reference} onChange={(e) => setReference(e.target.value)} />
          <button className="btn btn-primary">Create</button>
        </form>
        {error && <div className="auth-error">{error}</div>}
      </section>

      <section className="card">
        <h2 className="card-title">Open matters</h2>
        {cases.length === 0 ? (
          <p className="muted">No cases yet.</p>
        ) : (
          <ul className="case-list">
            {cases.map((c) => (
              <li key={c.id} className="case-row">
                <Link to={`/app/cases/${c.id}`} className="case-link">
                  <span className="case-title">{c.title}</span>
                  {c.reference && <span className="case-ref">{c.reference}</span>}
                </Link>
                <span className="muted">{c.document_count} document{c.document_count === 1 ? '' : 's'}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
