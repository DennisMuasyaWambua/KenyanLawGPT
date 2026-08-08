// Tiny persisted session store shared between the auth React context and the
// low-level fetch wrapper. Kept outside React so lib/gateway.ts can read the
// token/active-firm without prop-drilling.

export interface FirmRef {
  id: string;
  name: string;
  slug: string;
}

export interface Membership {
  firm: FirmRef;
  role: 'owner' | 'admin' | 'staff';
}

export interface AuthUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
}

export interface Session {
  token: string;
  user: AuthUser;
  memberships: Membership[];
  activeFirmId: string | null;
}

const KEY = 'wakili.session';

let current: Session | null = load();

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function getSession(): Session | null {
  return current;
}

export function setSession(next: Session | null): void {
  current = next;
  if (next) localStorage.setItem(KEY, JSON.stringify(next));
  else localStorage.removeItem(KEY);
}

export function getToken(): string | null {
  return current?.token ?? null;
}

export function getActiveFirmId(): string | null {
  return current?.activeFirmId ?? null;
}

export function activeMembership(): Membership | null {
  if (!current) return null;
  return (
    current.memberships.find((m) => m.firm.id === current!.activeFirmId) ??
    current.memberships[0] ??
    null
  );
}
