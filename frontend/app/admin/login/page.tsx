"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setAdminSession } from "@/lib/admin";
import { BRAND } from "@/lib/brand";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/v1/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "login failed");
      setAdminSession(d.access_token, d.refresh_token, d.admin);
      router.push("/admin");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-navy p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <img src={BRAND.logo} alt={BRAND.name} className="mx-auto mb-4 w-full max-w-xs rounded-lg bg-white p-3 shadow-lg" />
          <h1 className="font-display text-2xl font-bold text-white">Control Center</h1>
          <p className="mt-1 text-xs uppercase tracking-widest text-gold">Platform administration</p>
        </div>
        <form onSubmit={submit} className="card space-y-4">
          <div>
            <label className="label">Admin email</label>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button className="btn-gold w-full" disabled={busy}>
            {busy ? "Signing in…" : "Enter control center"}
          </button>
        </form>
      </div>
    </main>
  );
}
