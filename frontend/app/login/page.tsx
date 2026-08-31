"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { getTenant, setSession } from "@/lib/api";
import GoogleButton from "@/components/GoogleButton";
import { BRAND } from "@/lib/brand";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function LoginPage() {
  const router = useRouter();
  const [slug, setSlug] = useState(getTenant() || process.env.NEXT_PUBLIC_DEFAULT_TENANT || "ckarwitha");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-Slug": slug },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "login failed");
      setSession(slug, data.access_token, data.refresh_token, data.user);
      router.push(data.user.role === "client" ? "/portal" : "/dashboard");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function googleLogin(credential: string) {
    setBusy(true);
    setError("");
    try {
      if (!slug) throw new Error("Enter your firm slug first, then continue with Google");
      const res = await fetch(`${API}/api/v1/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-Slug": slug },
        body: JSON.stringify({ credential }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Google sign-in failed");
      setSession(slug, data.access_token, data.refresh_token, data.user);
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
          <img
            src={BRAND.logo}
            alt={BRAND.name}
            className="mx-auto mb-4 w-full max-w-xs rounded-lg bg-white p-3 shadow-lg"
          />
          <h1 className="font-display text-3xl font-bold text-white">
            {BRAND.short}
          </h1>
          <p className="mt-1 text-xs uppercase tracking-widest text-gold">{BRAND.sub}</p>
        </div>
        <form onSubmit={submit} className="card space-y-4">
          <div>
            <label className="label">Firm (subdomain slug)</label>
            <input className="input" value={slug} onChange={(e) => setSlug(e.target.value)}
              placeholder="ckarwitha" required />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@firm.co.ke" required />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button className="btn-gold w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>

          <div className="flex items-center gap-3 text-xs text-ink/40">
            <span className="h-px flex-1 bg-ink/10" /> or <span className="h-px flex-1 bg-ink/10" />
          </div>
          <GoogleButton text="signin_with" onCredential={googleLogin} />

          <p className="text-center text-xs text-ink/50">
            Need access? Ask a partner at your firm to onboard you.
          </p>
        </form>
      </div>
    </main>
  );
}
