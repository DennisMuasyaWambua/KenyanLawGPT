"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { setSession } from "@/lib/api";
import GoogleButton from "@/components/GoogleButton";
import { BRAND } from "@/lib/brand";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function InviteAcceptPage() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const search = useSearchParams();
  const token = params.token;
  const firm = search.get("firm") || "";

  const [invite, setInvite] = useState<any>(null);
  const [firmName, setFirmName] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/v1/auth/invite/${token}`, {
          headers: { "X-Tenant-Slug": firm },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "invite invalid or expired");
        setInvite(data.invite);
        setFullName(data.invite.full_name || "");
        setFirmName(data.firm?.name || "");
      } catch (err: any) {
        setError(err.message);
      }
    })();
  }, [token, firm]);

  async function accept(body: Record<string, unknown>) {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/v1/auth/invite/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-Slug": firm },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "could not accept invite");
      setSession(firm, data.access_token, data.refresh_token, data.user);
      router.push(data.user.role === "client" ? "/portal" : "/dashboard");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-navy p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <img src={BRAND.logo} alt={BRAND.name} className="mx-auto mb-3 h-16 w-16 rounded-md bg-white object-contain p-1" />
          <h1 className="font-display text-2xl font-bold text-white">{BRAND.short}</h1>
          <p className="mt-2 text-sm text-white/60">
            {invite ? `Join ${firmName || firm} as ${invite.role}` : "Accept your invite"}
          </p>
        </div>

        <div className="card space-y-4">
          {!invite && !error && <p className="text-sm text-ink/60">Loading invite…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}

          {invite && (
            <>
              <div>
                <label className="label">Email</label>
                <input className="input" value={invite.email} disabled />
              </div>
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  accept({ full_name: fullName, phone, password });
                }}
              >
                <div>
                  <label className="label">Full name</label>
                  <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)}
                    placeholder="Your name" required />
                </div>
                <div>
                  <label className="label">Phone (for WhatsApp/SMS reminders)</label>
                  <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)}
                    placeholder="2547XXXXXXXX" />
                </div>
                <div>
                  <label className="label">Set a password</label>
                  <input className="input" type="password" value={password}
                    onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters"
                    minLength={8} required />
                </div>
                <button className="btn-gold w-full" disabled={busy}>
                  {busy ? "Setting up…" : "Accept & set password"}
                </button>
              </form>

              <div className="flex items-center gap-3 text-xs text-ink/40">
                <span className="h-px flex-1 bg-ink/10" /> or <span className="h-px flex-1 bg-ink/10" />
              </div>
              <GoogleButton
                text="continue_with"
                onCredential={(credential) => accept({ full_name: fullName, phone, credential })}
              />
            </>
          )}
        </div>
      </div>
    </main>
  );
}
