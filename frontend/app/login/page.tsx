"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getTenant, landingPathFor, setSession } from "@/lib/api";
import GoogleButton from "@/components/GoogleButton";
import FirmMark from "@/components/FirmMark";
import ProductMark from "@/components/ProductMark";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function LoginPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [firmName, setFirmName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Firm ID: a ?firm= link (welcome / sign-in emails), else the firm last used
  // on this device, else an optional deployment default.
  useEffect(() => {
    const firm = new URLSearchParams(window.location.search).get("firm");
    setSlug(firm || getTenant() || localStorage.getItem("wakili_last_firm") || process.env.NEXT_PUBLIC_DEFAULT_TENANT || "");
  }, []);
  // Greet people with their own firm's name once the ID resolves.
  useEffect(() => {
    const id = slug.trim().toLowerCase();
    setFirmName("");
    if (id.length < 3) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetch(`${API}/api/v1/firm/info`, { headers: { "X-Tenant-Slug": id }, signal: ctrl.signal })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => d?.firm?.name && setFirmName(d.firm.name))
        .catch(() => {});
    }, 300);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [slug]);

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
      router.push(landingPathFor(data.user, new URLSearchParams(window.location.search).get("next")));
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
      router.push(landingPathFor(data.user, new URLSearchParams(window.location.search).get("next")));
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
          {firmName ? (
            <>
              <div className="mb-4 flex justify-center">
                <FirmMark name={firmName} slug={slug.trim().toLowerCase()} className="h-20 w-20 text-3xl" />
              </div>
              <h1 className="font-display text-3xl font-bold text-white">{firmName}</h1>
              <p className="mt-1 text-xs uppercase tracking-widest text-gold">Sign in to your workspace</p>
            </>
          ) : (
            <>
              <ProductMark light />
              <p className="mt-3 text-sm text-white/60">Sign in to your firm&apos;s workspace</p>
            </>
          )}
        </div>
        <form onSubmit={submit} className="card space-y-4">
          <div>
            <label className="label">Firm ID</label>
            <input className="input" value={slug} onChange={(e) => setSlug(e.target.value)}
              placeholder="your-firm-id" required autoCapitalize="none" spellCheck={false} />
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
            Need access? Ask your firm&apos;s administrator to add you.
            <br />
            Setting up a new firm?{" "}
            <Link href="/signup" className="font-semibold text-navy hover:underline">Create a firm account</Link>
          </p>
        </form>
      </div>
    </main>
  );
}
