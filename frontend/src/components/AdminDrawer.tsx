import { useState } from 'react';
import { startCrawl, ApiError } from '../lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
  notify: (kind: 'success' | 'error', text: string) => void;
}

export function AdminDrawer({ open, onClose, notify }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const fire = async () => {
    setBusy(true);
    try {
      const res = await startCrawl();
      // The endpoint returns immediately; crawling continues server-side.
      notify('success', res.message || 'Crawl triggered. Indexing runs in the background.');
      setConfirming(false);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Failed to trigger crawl.';
      notify('error', msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Administration">
        <div className="drawer-header">
          <h2>Administration</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <section className="drawer-section">
          <h3>Source data</h3>
          <p className="drawer-hint">
            Re-crawl the Kenya Law websites to refresh the assistant's knowledge base.
            This is a long-running, resource-intensive operation on the server — only
            trigger it when source content is known to be stale.
          </p>

          {!confirming ? (
            <button className="btn btn-secondary" onClick={() => setConfirming(true)}>
              Re-crawl source data…
            </button>
          ) : (
            <div className="confirm-box">
              <p>
                Start a full re-crawl now? The backend will index up to 100 pages and
                may respond slowly while it runs.
              </p>
              <div className="confirm-actions">
                <button className="btn btn-danger" onClick={fire} disabled={busy}>
                  {busy ? 'Starting…' : 'Yes, start crawl'}
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => setConfirming(false)}
                  disabled={busy}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      </aside>
    </>
  );
}
