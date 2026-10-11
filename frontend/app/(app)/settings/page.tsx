"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";
import RolesManager, { type Role } from "@/components/RolesManager";
import AddMemberForm from "@/components/AddMemberForm";


export default function SettingsPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const [kdpaResult, setKdpaResult] = useState("");
  const [resent, setResent] = useState<Record<string, string>>({});

  const canViewUsers = can("users.view");
  const canInvite = can("users.invite");
  const canManageRoles = can("roles.manage");
  const canChangeRoles = can("users.manage_roles");
  const canRemove = can("users.remove");
  const canKDPA = can("kdpa.export") || can("kdpa.erase");

  const { data: meData } = useQuery({ queryKey: ["me"], queryFn: () => api("/api/v1/auth/me") });
  const { data: usersData } = useQuery({ queryKey: ["users"], queryFn: () => api("/api/v1/users"), enabled: canViewUsers });
  const { data: rolesData } = useQuery({ queryKey: ["roles"], queryFn: () => api("/api/v1/roles"), enabled: canInvite || canManageRoles });
  const { data: clientsData } = useQuery({ queryKey: ["clients"], queryFn: () => api("/api/v1/clients"), enabled: can("clients.view") });

  const roles: Role[] = rolesData?.roles || [];

  const resendLogin = useMutation({
    mutationFn: (id: string) => api(`/api/v1/users/${id}/resend-login`, { method: "POST" }),
    onSuccess: (d: any, id) => {
      setResent((prev) => ({
        ...prev,
        [id]: d.credentials_emailed ? "New login emailed ✓" : `Email not sent — temporary password: ${d.temp_password}`,
      }));
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e, id) => setResent((prev) => ({ ...prev, [id]: (e as Error).message })),
  });
  const createUser = useMutation({
    mutationFn: (body: any) => api("/api/v1/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const changeRole = useMutation({
    mutationFn: ({ id, role_id }: { id: string; role_id: string }) =>
      api(`/api/v1/users/${id}/role`, { method: "PATCH", body: JSON.stringify({ role_id }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api(`/api/v1/users/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
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
    <div className="space-y-8">
      <div>
        <h2 className="font-display text-3xl font-bold text-navy">Firm Settings</h2>
        <div className="card mt-4 text-sm">
          <p><b>{meData?.tenant?.name}</b> · plan: {meData?.tenant?.plan}</p>
          <p className="text-xs text-ink/60">
            Firm ID: {meData?.tenant?.slug} · KDPA data residency (Kenya):{" "}
            {meData?.tenant?.data_residency_ke ? "✓ enabled" : "—"}
          </p>
          {can("firm_settings.edit") && meData?.tenant && <FirmProfile tenant={meData.tenant} />}
          <a href="/change-password" className="mt-3 inline-block text-xs font-semibold text-navy hover:underline">Change my password</a>
        </div>
      </div>

      {/* --- Team ------------------------------------------------------------ */}
      {canViewUsers && (
        <section>
          <h3 className="font-display text-xl font-bold text-navy">Team</h3>
          <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="card !p-0 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-navy/5 text-left text-xs uppercase text-navy/60">
                  <tr><th className="p-3">Name</th><th className="p-3">Role</th><th className="p-3">Status</th></tr>
                </thead>
                <tbody>
                  {(usersData?.users || []).map((u: any) => (
                    <tr key={u.id} className="border-t border-navy/5 align-top">
                      <td className="p-3">
                        <div className="font-medium">{u.full_name}</div>
                        <div className="text-xs text-ink/50">{u.email}</div>
                        {u.must_change_password && (
                          <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                            awaiting first sign-in
                          </span>
                        )}
                        {canInvite && u.status === "active" && u.id !== meData?.user?.id && u.id !== meData?.tenant?.owner_user_id && (
                          <button className="ml-2 text-[11px] text-navy hover:underline disabled:opacity-50"
                            disabled={resendLogin.isPending}
                            onClick={() => confirm(`Email ${u.full_name} a new temporary password? Their current password stops working.`) && resendLogin.mutate(u.id)}>
                            resend login
                          </button>
                        )}
                        {resent[u.id] && <div className="mt-1 break-all text-[11px] text-gold-dim">{resent[u.id]}</div>}
                      </td>
                      <td className="p-3">
                        {u.role_id && canChangeRoles ? (
                          <select
                            className="input !py-1 !text-xs"
                            defaultValue={u.role_id}
                            onChange={(e) => changeRole.mutate({ id: u.id, role_id: e.target.value })}
                          >
                            {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                          </select>
                        ) : (
                          <span className="capitalize">{u.role}</span>
                        )}
                      </td>
                      <td className="p-3">
                        <span className={u.status === "active" ? "text-green-700" : "text-red-600"}>{u.status}</span>
                        {canRemove && u.role !== "client" && (
                          <button
                            className="ml-2 text-xs text-ink/50 hover:underline"
                            onClick={() => setStatus.mutate({ id: u.id, status: u.status === "active" ? "disabled" : "active" })}
                          >
                            {u.status === "active" ? "suspend" : "reactivate"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="space-y-6">
              {canInvite && (
                <div className="card space-y-3">
                  <h4 className="font-display text-lg font-bold text-navy">Add a firm member</h4>
                  <p className="text-xs text-ink/50">
                    They&apos;re emailed a temporary password and choose their own at first sign-in (or sign in with
                    Google using the same email). What they can do is set by the role.
                  </p>
                  <AddMemberForm roles={roles} />
                </div>
              )}

              {canInvite && (
                <form className="card space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const fd = new FormData(e.currentTarget);
                    createUser.mutate({
                      email: fd.get("email"), full_name: fd.get("full_name"),
                      password: fd.get("password") || "", client_id: fd.get("client_id") || null,
                    });
                    (e.target as HTMLFormElement).reset();
                  }}>
                  <h4 className="font-display text-lg font-bold text-navy">Create a client portal account</h4>
                  <input name="full_name" className="input" placeholder="Full name" required />
                  <input name="email" type="email" className="input" placeholder="Email" required />
                  <div className="grid grid-cols-2 gap-2">
                    <input name="password" className="input" placeholder="Password (blank = email one)" minLength={8} />
                    <select name="client_id" className="input" required defaultValue="">
                      <option value="" disabled>Link to client…</option>
                      {(clientsData?.clients || []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </div>
                  {createUser.isError && <p className="text-xs text-red-600">{(createUser.error as Error).message}</p>}
                  {createUser.data && (
                    <p className="break-all text-xs text-gold-dim">
                      {(createUser.data as any).credentials_emailed !== false
                        ? "Portal account created."
                        : `Portal account created; email not sent — temporary password: ${(createUser.data as any).temp_password}`}
                    </p>
                  )}
                  <button className="btn-primary w-full" disabled={createUser.isPending}>Create portal account</button>
                </form>
              )}
            </div>
          </div>
        </section>
      )}

      {/* --- Roles & permissions ------------------------------------------- */}
      {canManageRoles && <RolesManager roles={roles} />}

      {/* --- KDPA ----------------------------------------------------------- */}
      {canKDPA && (
        <section>
          <h3 className="font-display text-xl font-bold text-navy">KDPA — data subject rights</h3>
          <div className="card mt-3 space-y-3 text-sm">
            <p className="text-xs text-ink/60">
              Export produces the full subject-access JSON. Erasure cascades across the database,
              document storage, vector index and knowledge graph (Data Protection Act, 2019 s.26/40).
            </p>
            {(clientsData?.clients || []).map((c: any) => (
              <div key={c.id} className="flex items-center justify-between border-t border-navy/5 pt-2">
                <span>{c.name} <span className="text-xs text-ink/40">consent: {c.kdpa_consent ? "✓" : "✗"}</span></span>
                <span className="flex gap-2">
                  {can("kdpa.export") && <button className="btn-primary !px-2 !py-1 !text-xs" onClick={() => exportSubject(c.id)}>Export</button>}
                  {can("kdpa.erase") && (
                    <button className="btn-primary !bg-red-700 !px-2 !py-1 !text-xs"
                      onClick={() => confirm(`Erase all personal data for ${c.name}? This cannot be undone.`) && erase.mutate({ subject_type: "client", subject_id: c.id })}>
                      Erase
                    </button>
                  )}
                </span>
              </div>
            ))}
            {kdpaResult && <p className="text-xs text-gold-dim">result: {kdpaResult}</p>}
          </div>
        </section>
      )}
    </div>
  );
}

function FirmProfile({ tenant }: { tenant: { name: string; reg_number?: string; phone?: string } }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: (body: Record<string, string>) => api("/api/v1/firm", { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ["me"] }); },
  });
  if (!editing) {
    return (
      <p className="mt-2 text-xs text-ink/60">
        LSK / registration no.: {tenant.reg_number || "—"} · Phone: {tenant.phone || "—"}
        <button className="ml-2 font-semibold text-navy hover:underline" onClick={() => setEditing(true)}>Edit firm details</button>
      </p>
    );
  }
  return (
    <form className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        save.mutate({ name: String(fd.get("name")), reg_number: String(fd.get("reg_number")), phone: String(fd.get("phone")) });
      }}>
      <input name="name" className="input" defaultValue={tenant.name} required aria-label="Firm name" />
      <input name="reg_number" className="input" defaultValue={tenant.reg_number} placeholder="LSK / registration no." aria-label="Registration number" />
      <input name="phone" className="input" defaultValue={tenant.phone} placeholder="Phone" aria-label="Phone" />
      {save.isError && <p className="text-xs text-red-600 sm:col-span-3">{(save.error as Error).message}</p>}
      <div className="flex gap-2 sm:col-span-3">
        <button className="btn-gold !py-1.5" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</button>
        <button type="button" className="btn-outline" onClick={() => setEditing(false)}>Cancel</button>
      </div>
    </form>
  );
}
