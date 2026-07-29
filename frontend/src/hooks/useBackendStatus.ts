import { useEffect, useRef, useState } from 'react';
import { getStatus, type BackendState } from '../lib/api';
import { STATUS_POLL_INTERVAL_MS } from '../config/api';

export interface BackendStatus {
  state: BackendState;
  message: string;
}

export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>({
    state: 'initializing',
    message: 'Checking backend…',
  });
  const timerRef = useRef<number>();

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await getStatus();
        if (cancelled) return;
        const known: BackendState[] = ['ready', 'initializing', 'crawling'];
        const state = known.includes(res.status as BackendState)
          ? (res.status as BackendState)
          : 'error';
        setStatus({ state, message: res.message });
      } catch {
        if (!cancelled) {
          setStatus({ state: 'offline', message: 'Backend is unreachable.' });
        }
      }
      if (!cancelled) {
        timerRef.current = window.setTimeout(poll, STATUS_POLL_INTERVAL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timerRef.current);
    };
  }, []);

  return status;
}
