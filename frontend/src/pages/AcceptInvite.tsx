import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { acceptInvite, previewInvite } from '../lib/gateway';
import { ApiError } from '../lib/api';

export function AcceptInvite() {
  const { token = '' } = useParams();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<{ firm_name: string; email: string; role: string } | null>(null);
  const [firstName, setFirstName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    previewInvite(token)
      .then(setPreview)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Invalid invite.'));
  }, [token]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const res = await acceptInvite({ token, password, first_name: firstName });
      applyAuth(res);
      navigate('/app');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not accept invite.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand center">
          <span className="brand-name">WakiliAI</span>
          <span className="brand-tag">Join your firm</span>
        </div>
        {preview ? (
          <>
            <p className="invite-intro">
              You’ve been invited to join <strong>{preview.firm_name}</strong> as{' '}
              <strong>{preview.role}</strong> ({preview.email}).
            </p>
            <form onSubmit={submit} className="auth-form">
              <label>
                Your name
                <input value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="Jane" />
              </label>
              <label>
                Choose a password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} placeholder="At least 8 characters" />
              </label>
              {error && <div className="auth-error">{error}</div>}
              <button className="btn btn-primary" disabled={busy}>
                {busy ? 'Joining…' : 'Accept & join'}
              </button>
            </form>
          </>
        ) : (
          <div className="auth-error">{error || 'Loading invite…'}</div>
        )}
      </div>
    </div>
  );
}
