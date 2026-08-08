import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { GoogleButton } from '../components/GoogleButton';
import { googleAuth, login } from '../lib/gateway';
import { ApiError } from '../lib/api';

export function SignIn() {
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const done = (res: Parameters<typeof applyAuth>[0]) => {
    applyAuth(res);
    navigate('/app');
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      done(await login(email, password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign in failed.');
    } finally {
      setBusy(false);
    }
  };

  const onGoogle = async (credential: string) => {
    setError('');
    try {
      done(await googleAuth(credential));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Google sign in failed.');
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand center">
          <span className="brand-name">WakiliAI</span>
          <span className="brand-tag">Sign in to your workspace</span>
        </div>
        <form onSubmit={submit} className="auth-form">
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button className="btn btn-primary" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <div className="auth-divider"><span>or</span></div>
        <div className="auth-google">
          <GoogleButton onCredential={onGoogle} text="signin_with" />
        </div>
        <p className="auth-alt">
          New firm? <Link to="/signup">Create a workspace</Link>
        </p>
      </div>
    </div>
  );
}
