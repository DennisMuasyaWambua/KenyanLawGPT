"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearSession, currentUser, getTenant, landingPathFor, setSession } from "@/lib/api";
import FirmMark from "@/components/FirmMark";

// Reached after signing in with an emailed temporary password (the gateway
// refuses everything else until this succeeds) or by choice from Settings.
export default function ChangePasswordPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [forced, setForced] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [firm, setFirm] = useState<{ name: string; slug: string } | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("wakili_access")) {
      router.replace("/login");
      return;
    }
    setForced(!!currentUser()?.must_change_password);
    setReady(true);
    api("/api/v1/firm/info").then((d) => setFirm(d.firm)).catch(() => {});
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("The new passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      const data = await api("/api/v1/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setSession(getTenant(), data.access_token, data.refresh_token, data.user);
      router.replace(landingPathFor(data.user));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await api("/api/v1/auth/logout", { method: "POST" }).catch(() => {});
    clearSession();
    router.replace("/login");
  }

  if (!ready) return null;
  return (
    <main className="flex min-h-screen items-center justify-center bg-navy p-4">
      <div className="w-full max-w-md">
        {firm && (
          <div className="mb-6 flex items-center justify-center gap-3">
            <FirmMark name={firm.name} slug={firm.slug} />
            <span className="font-display text-xl font-bold text-white">{firm.name}</span>
          </div>
        )}
        <form onSubmit={submit} className="card space-y-4">
          <div>
            <h1 className="font-display text-2xl font-bold text-navy">
              {forced ? "Choose your password" : "Change password"}
            </h1>
            {forced && (
              <p className="mt-1 text-sm text-ink/60">
                You signed in with a temporary password. Pick your own to continue — the temporary one stops working.
              </p>
            )}
          </div>
          <div>
            <label className="label" htmlFor="cur">{forced ? "Temporary password" : "Current password"}</label>
            <input id="cur" className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
              required autoComplete="current-password" />
          </div>
          <div>
            <label className="label" htmlFor="new">New password</label>
            <input id="new" className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)}
              minLength={8} required autoComplete="new-password" placeholder="At least 8 characters" />
          </div>
          <div>
            <label className="label" htmlFor="new2">Confirm new password</label>
            <input id="new2" className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
              minLength={8} required autoComplete="new-password" />
          </div>
          {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
          <button className="btn-gold w-full" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
          <button type="button" className="w-full text-center text-xs text-ink/50 hover:underline" onClick={signOut}>
            Sign out
          </button>
        </form>
      </div>
    </main>
  );
}
