"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { getTenant, setSession } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function LoginPage() {
  const router = useRouter();
  const [slug, setSlug] = useState(getTenant() || "mwangi-advocates");
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

  return (
    <main className="flex min-h-screen items-center justify-center bg-navy p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="font-display text-4xl font-bold text-white">
            Wakili<span className="text-gold">AI</span>
          </h1>
          <p className="mt-2 text-sm text-white/60">
            Practice management &amp; AI legal research for Kenyan firms
          </p>
        </div>
        <form onSubmit={submit} className="card space-y-4">
          <div>
            <label className="label">Firm (subdomain slug)</label>
            <input className="input" value={slug} onChange={(e) => setSlug(e.target.value)}
              placeholder="mwangi-advocates" required />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="owner@mwangi-advocates.demo" required />
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
          <p className="text-center text-xs text-ink/50">
            Demo firms: <code>mwangi-advocates</code> / <code>odhiambo-partners</code> — password{" "}
            <code>DemoPass123!</code>
          </p>
        </form>
      </div>
    </main>
  );
}
