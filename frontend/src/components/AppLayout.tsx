import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

const NAV = [
  { to: '/app/assistant', label: 'Assistant' },
  { to: '/app/calendar', label: 'Calendar' },
  { to: '/app/cases', label: 'Cases' },
  { to: '/app/transcribe', label: 'Transcribe' },
  { to: '/app/staff', label: 'Staff' },
];

export function AppLayout() {
  const { session, membership, signOut, setActiveFirm } = useAuth();
  const navigate = useNavigate();

  const onSignOut = () => {
    signOut();
    navigate('/signin');
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-name">WakiliAI</span>
          <span className="brand-tag">Legal workspace</span>
        </div>
        <nav className="side-nav">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => `side-link${isActive ? ' active' : ''}`}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {membership && <div className="role-pill">{membership.role}</div>}
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          {session && session.memberships.length > 0 && (
            <label className="firm-switcher">
              <span className="visually-hidden">Active firm</span>
              <select
                value={session.activeFirmId ?? ''}
                onChange={(e) => setActiveFirm(e.target.value)}
              >
                {session.memberships.map((m) => (
                  <option key={m.firm.id} value={m.firm.id}>
                    {m.firm.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="topbar-right">
            <span className="user-email">{session?.user.email}</span>
            <button className="btn btn-ghost" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </header>
        <main className="shell-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
