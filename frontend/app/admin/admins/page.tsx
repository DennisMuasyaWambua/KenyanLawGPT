"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi, currentAdmin } from "@/lib/admin";

type Admin = { id: string; email: string; full_name: string; status: string; last_login_at: string | null };

export default function AdminAdmins() {
  const qc = useQueryClient();
  const me = currentAdmin();
  const [f, setF] = useState({ full_name: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));

  const { data } = useQuery({ queryKey: ["admin-admins"], queryFn: () => adminApi("/admins") });
  const admins: Admin[] = data?.admins || [];

  const create = useMutation({
    mutationFn: () => adminApi("/admins", { method: "POST", body: JSON.stringify(f) }),
    onSuccess: () => { setF({ full_name: "", email: "", password: "" }); qc.invalidateQueries({ queryKey: ["admin-admins"] }); },
    onError: (e: any) => setErr(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => adminApi(`/admins/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-admins"] }),
    onError: (e: any) => setErr(e.message),
  });

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Platform admins</h2>
      <p className="mt-1 text-sm text-ink/50">Accounts with full cross-tenant control. Handle with care.</p>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}

      <form
        onSubmit={(e) => { e.preventDefault(); setErr(""); create.mutate(); }}
        className="card mt-6 grid grid-cols-1 gap-4 md:grid-cols-4"
      >
        <div>
          <label className="label">Full name</label>
          <input className="input" value={f.full_name} onChange={(e) => set("full_name", e.target.value)} />
        </div>
        <div>
          <label className="label">Email</label>
          <input className="input" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} required />
        </div>
        <div>
          <label className="label">Password</label>
          <input className="input" type="password" value={f.password} onChange={(e) => set("password", e.target.value)} placeholder="min 8 chars" required />
        </div>
        <div className="flex items-end">
          <button className="btn-gold w-full" disabled={create.isPending}>{create.isPending ? "Adding…" : "Add admin"}</button>
        </div>
      </form>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-navy/10 text-left text-xs uppercase tracking-wide text-ink/50">
              <th className="py-2 pr-3">Name</th>
              <th className="py-2 pr-3">Email</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3"></th>
            </tr>
          </thead>
          <tbody>
            {admins.map((a) => (
              <tr key={a.id} className="border-b border-navy/5">
                <td className="py-2 pr-3 font-medium text-navy">{a.full_name || "—"}</td>
                <td className="py-2 pr-3">{a.email}{me?.id === a.id && <span className="ml-2 badge-public">you</span>}</td>
                <td className="py-2 pr-3">{a.status}</td>
                <td className="py-2 pr-3 text-right">
                  {me?.id !== a.id && (
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => { if (confirm(`Remove admin ${a.email}?`)) remove.mutate(a.id); }}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
