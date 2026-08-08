import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  listCaseDocuments,
  searchCase,
  uploadCaseDocument,
  type CaseDocument,
} from '../lib/gateway';
import { ApiError } from '../lib/api';

const STATUS_LABEL: Record<string, string> = {
  pending: 'Awaiting upload',
  uploaded: 'Uploaded — queued',
  ingested: 'Ingested',
  failed: 'Failed',
};

export function CaseDetailPage() {
  const { caseId = '' } = useParams();
  const [docs, setDocs] = useState<CaseDocument[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [chunks, setChunks] = useState<{ text: string; filename: string }[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    listCaseDocuments(caseId).then(setDocs).catch(() => {});
  };
  useEffect(refresh, [caseId]);

  const onUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError('');
    try {
      for (const file of Array.from(files)) {
        await uploadCaseDocument(caseId, file);
      }
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed.');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const runSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const res = await searchCase(caseId, query);
      setChunks(res.chunks);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Search failed.');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/app/cases" className="back-link">← Cases</Link>
          <h1 className="page-title">Case documents</h1>
          <p className="page-sub">Upload documents to ingest them into this case’s knowledge base.</p>
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">Documents</h2>
        <div className="uploader">
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md"
            disabled={busy}
            onChange={(e) => onUpload(e.target.files)}
          />
          {busy && <span className="muted">Uploading & ingesting…</span>}
        </div>
        {error && <div className="auth-error">{error}</div>}
        {docs.length === 0 ? (
          <p className="muted">No documents uploaded yet.</p>
        ) : (
          <table className="data-table">
            <thead><tr><th>File</th><th>Status</th><th>Chunks</th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.filename}</td>
                  <td>
                    <span className={`status-dot status-${d.status}`} />
                    {STATUS_LABEL[d.status] ?? d.status}
                    {d.error && <div className="doc-error">{d.error}</div>}
                  </td>
                  <td>{d.chunk_count || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">Test retrieval</h2>
        <p className="page-sub">See which document passages the assistant would pull for a question.</p>
        <form className="inline-form" onSubmit={runSearch}>
          <input placeholder="e.g. What did the affidavit state about the property?" value={query} onChange={(e) => setQuery(e.target.value)} required />
          <button className="btn btn-primary">Search</button>
        </form>
        {chunks.length > 0 && (
          <ul className="chunk-list">
            {chunks.map((c, i) => (
              <li key={i} className="chunk">
                <div className="chunk-file">{c.filename}</div>
                <p>{c.text}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
