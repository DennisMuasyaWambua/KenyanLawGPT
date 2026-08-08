import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { GoogleButton } from '../components/GoogleButton';
import { googleAuth, signup } from '../lib/gateway';
import { ApiError } from '../lib/api';

export function SignUp() {
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [firmName, setFirmName] = useState('');
  const [firstName, setFirstName] = useState('');
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
      done(await signup({ firm_name: firmName, email, password, first_name: firstName }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign up failed.');
    } finally {
      setBusy(false);
    }
  };

  const onGoogle = async (credential: string) => {
    setError('');
    try {
      if (!firmName.trim()) {
        setError('Enter your firm name first, then continue with Google.');
        return;
      }
      done(await googleAuth(credential, firmName));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Google sign up failed.');
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand center">
          <span className="brand-name">WakiliAI</span>
          <span className="brand-tag">Create your firm workspace</span>
        </div>
        <form onSubmit={submit} className="auth-form">
          <label>
            Law firm name
            <input value={firmName} onChange={(e) => setFirmName(e.target.value)} required placeholder="Wanjiku & Co Advocates" />
          </label>
          <label>
            Your name
            <input value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="Jane" />
          </label>
          <label>
            Work email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} placeholder="At least 8 characters" />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button className="btn btn-primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create firm'}
          </button>
        </form>
        <div className="auth-divider"><span>or</span></div>
        <div className="auth-google">
          <GoogleButton onCredential={onGoogle} text="signup_with" />
        </div>
        <p className="auth-alt">
          Already have an account? <Link to="/signin">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
