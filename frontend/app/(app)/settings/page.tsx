"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, currentUser } from "@/lib/api";

const ROLES = ["owner", "partner", "associate", "paralegal", "client"];

export default function SettingsPage() {
  const qc = useQueryClient();
  const me = currentUser();
  const isPartnerPlus = me && ["owner", "partner"].includes(me.role);
  const [kdpaResult, setKdpaResult] = useState("");

  const { data: meData } = useQuery({ queryKey: ["me"], queryFn: () => api("/api/v1/auth/me") });
  const { data: usersData } = useQuery({
    queryKey: ["users"],
    queryFn: () => api("/api/v1/users"),
    enabled: !!isPartnerPlus,
  });
  const { data: clientsData } = useQuery({ queryKey: ["clients"], queryFn: () => api("/api/v1/clients") });

  const createUser = useMutation({
    mutationFn: (body: any) => api("/api/v1/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const erase = useMutation({
    mutationFn: (body: any) => api("/api/v1/kdpa/erasure", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (d) => setKdpaResult(JSON.stringify(d.erased)),
    onError: (e) => setKdpaResult((e as Error).message),
  });

  async function exportSubject(subjectId: string) {
    const data = await api(`/api/v1/kdpa/export?subject_type=client&subject_id=${subjectId}`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `kdpa-export-${subjectId}.json`;
    a.click();
  }

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Firm Settings</h2>
      <div className="card mt-4 text-sm">
        <p><b>{meData?.tenant?.name}</b> · plan: {meData?.tenant?.plan}</p>
        <p className="text-xs text-ink/60">
          Tenant: {meData?.tenant?.slug} · KDPA data residency (Kenya):{" "}
          {meData?.tenant?.data_residency_ke ? "✓ enabled" : "—"}
        </p>
      </div>

      {isPartnerPlus && (
        <>
          <h3 className="mt-8 font-display text-xl font-bold text-navy">Team</h3>
          <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="card !p-0 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-navy/5 text-left text-xs uppercase text-navy/60">
                  <tr><th className="p-3">Name</th><th className="p-3">Email</th><th className="p-3">Role</th><th className="p-3">Status</th></tr>
                </thead>
                <tbody>
                  {(usersData?.users || []).map((u: any) => (
                    <tr key={u.id} className="border-t border-navy/5">
                      <td className="p-3">{u.full_name}</td>
                      <td className="p-3 text-xs">{u.email}</td>
                      <td className="p-3 capitalize">{u.role}</td>
                      <td className="p-3">{u.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <form className="card space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                createUser.mutate({
                  email: fd.get("email"), full_name: fd.get("full_name"),
                  role: fd.get("role"), password: fd.get("password"),
                  client_id: fd.get("client_id") || null,
                });
                (e.target as HTMLFormElement).reset();
              }}>
              <h4 className="font-display text-lg font-bold text-navy">Add member</h4>
              <input name="full_name" className="input" placeholder="Full name" required />
              <input name="email" type="email" className="input" placeholder="Email" required />
              <div className="grid grid-cols-2 gap-2">
                <select name="role" className="input">
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <input name="password" className="input" placeholder="Temp password" required />
              </div>
              <select name="client_id" className="input">
                <option value="">Link to client (portal accounts only)</option>
                {(clientsData?.clients || []).map((c: any) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              {createUser.isError && <p className="text-xs text-red-600">{(createUser.error as Error).message}</p>}
              <button className="btn-gold w-full" disabled={createUser.isPending}>Create</button>
            </form>
          </div>

          <h3 className="mt-8 font-display text-xl font-bold text-navy">KDPA — data subject rights</h3>
          <div className="card mt-3 space-y-3 text-sm">
            <p className="text-xs text-ink/60">
              Export produces the full subject-access JSON. Erasure cascades across the database,
              document storage, vector index and knowledge graph (Data Protection Act, 2019 s.26/40).
            </p>
            {(clientsData?.clients || []).map((c: any) => (
              <div key={c.id} className="flex items-center justify-between border-t border-navy/5 pt-2">
                <span>{c.name} <span className="text-xs text-ink/40">consent: {c.kdpa_consent ? "✓" : "✗"}</span></span>
                <span className="flex gap-2">
                  <button className="btn-primary !px-2 !py-1 !text-xs" onClick={() => exportSubject(c.id)}>Export</button>
                  <button className="btn-primary !bg-red-700 !px-2 !py-1 !text-xs"
                    onClick={() => confirm(`Erase all personal data for ${c.name}? This cannot be undone.`) &&
                      erase.mutate({ subject_type: "client", subject_id: c.id })}>
                    Erase
                  </button>
                </span>
              </div>
            ))}
            {kdpaResult && <p className="text-xs text-gold-dim">result: {kdpaResult}</p>}
          </div>
        </>
      )}
    </div>
  );
}
