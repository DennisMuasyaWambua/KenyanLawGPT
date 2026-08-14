"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { setSession } from "@/lib/api";
import GoogleButton from "@/components/GoogleButton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

// Turn a firm name into a candidate slug (backend validates/normalises again).
const slugify = (s: string) =>
  s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);

export default function SignupPage() {
  const router = useRouter();
  const [firmName, setFirmName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [ownerName, setOwnerName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [residency, setResidency] = useState(true);
  const [solo, setSolo] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const effectiveSlug = slugTouched ? slug : slugify(firmName);

  function routeFor(user: any) {
    router.push(user.role === "client" ? "/portal" : "/dashboard");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/v1/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          firm_name: firmName,
          slug: effectiveSlug,
          owner_name: ownerName,
          owner_email: email,
          owner_password: password,
          data_residency_ke: residency,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "sign up failed");
      // Provisioned — now log in to obtain tokens.
      const created = data.tenant.slug as string;
      const login = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-Slug": created },
        body: JSON.stringify({ email, password }),
      });
      const ld = await login.json();
      if (!login.ok) throw new Error(ld.error || "login after signup failed");
      setSession(created, ld.access_token, ld.refresh_token, ld.user);
      routeFor(ld.user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function googleSignup(credential: string) {
    setBusy(true);
    setError("");
    try {
      // Solo => omit firm fields; backend auto-provisions a personal workspace.
      const res = await fetch(`${API}/api/v1/signup/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          solo
            ? { credential, data_residency_ke: residency }
            : { credential, firm_name: firmName, slug: effectiveSlug, data_residency_ke: residency }
        ),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Google sign up failed");
      const created = data.tenant.slug as string;
      // Exchange the same Google credential for a session in the new firm.
      const login = await fetch(`${API}/api/v1/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-Slug": created },
        body: JSON.stringify({ credential }),
      });
      const ld = await login.json();
      if (!login.ok) throw new Error(ld.error || "login after Google signup failed");
      setSession(created, ld.access_token, ld.refresh_token, ld.user);
      routeFor(ld.user);
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
          <h1 className="font-display text-4xl font-bold text-white">
            Advocat<span className="text-gold">us</span>
          </h1>
          <p className="mt-2 text-sm text-white/60">Create your law firm workspace</p>
        </div>
        <form onSubmit={submit} className="card space-y-4">
          <label className="flex items-center gap-2 text-sm text-ink/70">
            <input type="checkbox" checked={solo} onChange={(e) => setSolo(e.target.checked)} />
            I&apos;m signing up as an individual (personal workspace)
          </label>

          {!solo && (
            <>
              <div>
                <label className="label">Firm name</label>
                <input className="input" value={firmName} onChange={(e) => setFirmName(e.target.value)}
                  placeholder="Mwangi &amp; Advocates" required={!solo} />
              </div>
              <div>
                <label className="label">Firm subdomain slug</label>
                <input className="input" value={effectiveSlug}
                  onChange={(e) => { setSlugTouched(true); setSlug(slugify(e.target.value)); }}
                  placeholder="mwangi-advocates" required={!solo} />
              </div>
            </>
          )}

          <div>
            <label className="label">Your name</label>
            <input className="input" value={ownerName} onChange={(e) => setOwnerName(e.target.value)}
              placeholder="Jane Mwangi" required />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@firm.co.ke" required />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters"
              minLength={8} required />
          </div>
          <label className="flex items-center gap-2 text-sm text-ink/70">
            <input type="checkbox" checked={residency} onChange={(e) => setResidency(e.target.checked)} />
            Keep data in Kenya (KDPA data residency)
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <button className="btn-gold w-full" disabled={busy}>
            {busy ? "Creating…" : "Create workspace"}
          </button>

          <div className="flex items-center gap-3 text-xs text-ink/40">
            <span className="h-px flex-1 bg-ink/10" /> or <span className="h-px flex-1 bg-ink/10" />
          </div>
          <GoogleButton text="signup_with" onCredential={googleSignup} />

          <p className="text-center text-xs text-ink/50">
            Already have an account? <Link href="/login" className="text-gold underline">Sign in</Link>
          </p>
        </form>
      </div>
    </main>
  );
}
