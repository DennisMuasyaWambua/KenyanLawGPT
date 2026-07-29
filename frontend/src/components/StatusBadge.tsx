import type { BackendStatus } from '../hooks/useBackendStatus';

const LABELS: Record<string, string> = {
  ready: 'Ready',
  initializing: 'Initializing',
  crawling: 'Indexing sources',
  offline: 'Offline',
  error: 'Error',
};

export function StatusBadge({ status }: { status: BackendStatus }) {
  const { state, message } = status;
  const busy = state === 'initializing' || state === 'crawling';
  return (
    <span className={`status-badge status-${state}`} title={message}>
      {busy ? <span className="status-spinner" aria-hidden /> : <span className="status-dot" aria-hidden />}
      {LABELS[state] ?? state}
    </span>
  );
}
