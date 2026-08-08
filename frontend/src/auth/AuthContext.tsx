import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  activeMembership,
  getSession,
  setSession,
  type Membership,
  type Session,
} from '../lib/session';
import type { AuthResponse } from '../lib/gateway';

interface AuthContextValue {
  session: Session | null;
  membership: Membership | null;
  signedIn: boolean;
  applyAuth: (res: AuthResponse) => void;
  signOut: () => void;
  setActiveFirm: (firmId: string) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setState] = useState<Session | null>(getSession());

  const applyAuth = useCallback((res: AuthResponse) => {
    const next: Session = {
      token: res.token,
      user: res.user,
      memberships: res.memberships,
      activeFirmId: res.memberships[0]?.firm.id ?? null,
    };
    setSession(next);
    setState(next);
  }, []);

  const signOut = useCallback(() => {
    setSession(null);
    setState(null);
  }, []);

  const setActiveFirm = useCallback((firmId: string) => {
    setState((prev) => {
      if (!prev) return prev;
      const next = { ...prev, activeFirmId: firmId };
      setSession(next);
      return next;
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      membership: activeMembership(),
      signedIn: !!session,
      applyAuth,
      signOut,
      setActiveFirm,
    }),
    [session, applyAuth, signOut, setActiveFirm],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
