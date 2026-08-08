import { useEffect, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import {
  createInvite,
  listInvites,
  listMembers,
  revokeInvite,
  type Invite,
  type Member,
} from '../lib/gateway';
import { ApiError } from '../lib/api';

export function StaffPage() {
  const { membership } = useAuth();
  const canManage = membership?.role === 'owner' || membership?.role === 'admin';
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('staff');
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [lastLink, setLastLink] = useState('');

  const refresh = () => {
    listMembers().then(setMembers).catch(() => {});
    if (canManage) listInvites().then(setInvites).catch(() => {});
  };

  useEffect(refresh, [canManage]);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLastLink('');
    try {
      const inv = await createInvite({ email, role, title });
      if (inv.accept_token) {
        setLastLink(`${window.location.origin}/invite/${inv.accept_token}`);
      }
      setEmail('');
      setTitle('');
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send invite.');
    }
  };

  const onRevoke = async (id: string) => {
    await revokeInvite(id).catch(() => {});
    refresh();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Staff</h1>
          <p className="page-sub">Members of your firm and pending invitations.</p>
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">Members</h2>
        <table className="data-table">
          <thead>
            <tr><th>Name</th><th>Email</th><th>Role</th><th>Title</th></tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>{[m.first_name, m.last_name].filter(Boolean).join(' ') || '—'}</td>
                <td>{m.email}</td>
                <td><span className="role-pill">{m.role}</span></td>
                <td>{m.title || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {canManage && (
        <section className="card">
          <h2 className="card-title">Invite a colleague</h2>
          <form className="inline-form" onSubmit={invite}>
            <input type="email" placeholder="colleague@firm.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="staff">Staff</option>
              <option value="admin">Admin</option>
            </select>
            <button className="btn btn-primary">Send invite</button>
          </form>
          {error && <div className="auth-error">{error}</div>}
          {lastLink && (
            <div className="invite-link">
              Share this link with your colleague:
              <code>{lastLink}</code>
            </div>
          )}

          {invites.length > 0 && (
            <table className="data-table">
              <thead>
                <tr><th>Email</th><th>Role</th><th>Status</th><th></th></tr>
              </thead>
              <tbody>
                {invites.map((inv) => (
                  <tr key={inv.id}>
                    <td>{inv.email}</td>
                    <td>{inv.role}</td>
                    <td>{inv.status}</td>
                    <td>
                      {inv.is_open && (
                        <button className="btn btn-ghost btn-sm" onClick={() => onRevoke(inv.id)}>Revoke</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
