"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi, fmtBytes } from "@/lib/admin";
import { setSession } from "@/lib/api";

type Metrics = { users: number; files: number; archives: number; storage_bytes: number };
type Firm = {
  id: string; name: string; slug: string; plan: string; status: string;
  created_at: string; metrics: Metrics | null;
};
type Plan = { code: string; name: string };

export default function AdminOverview() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [err, setErr] = useState("");

  const { data: statsData } = useQuery({ queryKey: ["admin-stats"], queryFn: () => adminApi("/stats") });
  const { data: firmsData } = useQuery({ queryKey: ["admin-firms"], queryFn: () => adminApi("/tenants") });
  const { data: plansData } = useQuery({ queryKey: ["admin-plans"], queryFn: () => adminApi("/plans") });
  const s = statsData?.stats || {};
  const firms: Firm[] = firmsData?.tenants || [];
  const plans: Plan[] = plansData?.plans || [];

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin-firms"] });
    qc.invalidateQueries({ queryKey: ["admin-stats"] });
  };

  const setStatus = useMutation({
    mutationFn: (v: { id: string; status: string }) =>
      adminApi(`/tenants/${v.id}/status`, { method: "PATCH", body: JSON.stringify({ status: v.status }) }),
    onSuccess: refresh,
    onError: (e: any) => setErr(e.message),
  });
  const setPlan = useMutation({
    mutationFn: (v: { id: string; plan: string }) =>
      adminApi(`/tenants/${v.id}/plan`, { method: "PATCH", body: JSON.stringify({ plan: v.plan }) }),
    onSuccess: refresh,
    onError: (e: any) => setErr(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => adminApi(`/tenants/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e: any) => setErr(e.message),
  });

  async function impersonate(f: Firm) {
    setErr("");
    try {
      const d = await adminApi<any>(`/tenants/${f.id}/impersonate`, { method: "POST" });
      // Store as a normal firm session and open the workspace in a new tab.
      setSession(d.tenant.slug, d.access_token, d.refresh_token, d.user);
      window.open("/dashboard", "_blank");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  const cards = [
    { label: "Firms", value: s.firms ?? "—" },
    { label: "Active", value: s.active ?? "—" },
    { label: "Suspended", value: s.suspended ?? "—" },
    { label: "Users", value: s.users ?? "—" },
    { label: "Files", value: s.files ?? "—" },
    { label: "Storage", value: s.storage_bytes != null ? fmtBytes(s.storage_bytes) : "—" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Platform overview</h2>
        <button className="btn-gold" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Close" : "+ New firm"}
        </button>
      </div>

      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}

      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-6">
        {cards.map((c) => (
          <div key={c.label} className="card">
            <p className="text-xs uppercase tracking-wide text-ink/50">{c.label}</p>
            <p className="mt-2 font-display text-2xl font-bold text-navy">{c.value}</p>
          </div>
        ))}
      </div>

      {showCreate && <CreateFirm plans={plans} onDone={() => { setShowCreate(false); refresh(); }} onError={setErr} />}

      <h3 className="mt-10 font-display text-xl font-bold text-navy">Firms</h3>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-navy/10 text-left text-xs uppercase tracking-wide text-ink/50">
              <th className="py-2 pr-3">Firm</th>
              <th className="py-2 pr-3">Plan</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Users</th>
              <th className="py-2 pr-3">Files</th>
              <th className="py-2 pr-3">Storage</th>
              <th className="py-2 pr-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {firms.map((f) => (
              <tr key={f.id} className="border-b border-navy/5">
                <td className="py-2 pr-3">
                  <div className="font-medium text-navy">{f.name}</div>
                  <div className="text-xs text-ink/50">{f.slug}</div>
                </td>
                <td className="py-2 pr-3">
                  <select
                    className="input !py-1"
                    value={f.plan}
                    onChange={(e) => setPlan.mutate({ id: f.id, plan: e.target.value })}
                  >
                    {plans.map((p) => (
                      <option key={p.code} value={p.code}>{p.name}</option>
                    ))}
                  </select>
                </td>
                <td className="py-2 pr-3">
                  <span className={f.status === "active" ? "badge-private" : "badge-public"}>{f.status}</span>
                </td>
                <td className="py-2 pr-3">{f.metrics?.users ?? "—"}</td>
                <td className="py-2 pr-3">{f.metrics?.files ?? "—"}</td>
                <td className="py-2 pr-3">{f.metrics ? fmtBytes(f.metrics.storage_bytes) : "—"}</td>
                <td className="py-2 pr-3">
                  <div className="flex flex-wrap gap-2">
                    {f.status === "active" ? (
                      <button className="text-xs text-amber-700 hover:underline" onClick={() => setStatus.mutate({ id: f.id, status: "suspended" })}>Suspend</button>
                    ) : (
                      <button className="text-xs text-green-700 hover:underline" onClick={() => setStatus.mutate({ id: f.id, status: "active" })}>Activate</button>
                    )}
                    <button className="text-xs text-navy hover:underline" onClick={() => impersonate(f)}>Log in as owner</button>
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => {
                        if (confirm(`Delete ${f.name}? This drops the firm's entire database schema and cannot be undone.`)) remove.mutate(f.id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {firms.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-ink/50">No firms yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CreateFirm({ plans, onDone, onError }: { plans: Plan[]; onDone: () => void; onError: (m: string) => void }) {
  const [f, setF] = useState({ firm_name: "", slug: "", owner_name: "", owner_email: "", owner_password: "", plan: "starter" });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    onError("");
    try {
      await adminApi("/tenants", { method: "POST", body: JSON.stringify(f) });
      onDone();
    } catch (e: any) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
      <div>
        <label className="label">Firm name</label>
        <input className="input" value={f.firm_name} onChange={(e) => set("firm_name", e.target.value)} placeholder="Mwangi & Associates" required />
      </div>
      <div>
        <label className="label">Slug (subdomain)</label>
        <input className="input" value={f.slug} onChange={(e) => set("slug", e.target.value)} placeholder="mwangi-associates" />
      </div>
      <div>
        <label className="label">Owner name</label>
        <input className="input" value={f.owner_name} onChange={(e) => set("owner_name", e.target.value)} required />
      </div>
      <div>
        <label className="label">Owner email</label>
        <input className="input" type="email" value={f.owner_email} onChange={(e) => set("owner_email", e.target.value)} required />
      </div>
      <div>
        <label className="label">Owner password</label>
        <input className="input" type="password" value={f.owner_password} onChange={(e) => set("owner_password", e.target.value)} placeholder="min 8 chars" required />
      </div>
      <div>
        <label className="label">Plan</label>
        <select className="input" value={f.plan} onChange={(e) => set("plan", e.target.value)}>
          {plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
        </select>
      </div>
      <div className="md:col-span-2">
        <button className="btn-gold" disabled={busy}>{busy ? "Provisioning…" : "Provision firm"}</button>
      </div>
    </form>
  );
}
