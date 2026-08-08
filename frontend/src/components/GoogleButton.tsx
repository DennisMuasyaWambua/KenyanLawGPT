import { useEffect, useRef } from 'react';
import { GOOGLE_CLIENT_ID } from '../config/api';

// Renders the official Google Identity Services button and hands the returned
// ID token back via onCredential. Renders nothing when no client ID is set.

declare global {
  interface Window {
    google?: any;
  }
}

let scriptPromise: Promise<void> | null = null;

function loadGsi(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load Google Sign-In.'));
    document.head.appendChild(s);
  });
  return scriptPromise;
}

export function GoogleButton({
  onCredential,
  text = 'signin_with',
}: {
  onCredential: (credential: string) => void;
  text?: 'signin_with' | 'signup_with' | 'continue_with';
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    let cancelled = false;
    loadGsi()
      .then(() => {
        if (cancelled || !ref.current) return;
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (resp: { credential: string }) => onCredential(resp.credential),
        });
        window.google.accounts.id.renderButton(ref.current, {
          theme: 'outline',
          size: 'large',
          text,
          width: 280,
        });
      })
      .catch(() => {
        /* button just won't render; email auth still works */
      });
    return () => {
      cancelled = true;
    };
  }, [onCredential, text]);

  if (!GOOGLE_CLIENT_ID) return null;
  return <div className="google-btn" ref={ref} />;
}
