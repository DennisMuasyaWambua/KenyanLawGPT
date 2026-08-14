"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type Role = {
  id: string;
  name: string;
  description: string;
  is_protected: boolean;
  permissions: string[];
  member_count: number;
};
type PermissionDef = { key: string; resource: string; action: string; label: string };
type Template = { name: string; description: string; is_protected: boolean; permissions: string[] };

export default function SettingsPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const [kdpaResult, setKdpaResult] = useState("");
  const [inviteLink, setInviteLink] = useState("");

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

  const inviteUser = useMutation({
    mutationFn: (body: any) => api("/api/v1/users/invite", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (d: any) => {
      setInviteLink(d.accept_url || "");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
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
            Tenant: {meData?.tenant?.slug} · KDPA data residency (Kenya):{" "}
            {meData?.tenant?.data_residency_ke ? "✓ enabled" : "—"}
          </p>
        </div>
      </div>

      {/* --- Team ------------------------------------------------------------ */}
      {canViewUsers && (
        <section>
          <h3 className="font-display text-xl font-bold text-navy">Team</h3>
          <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="card !p-0 overflow-hidden">
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
                <form className="card space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const fd = new FormData(e.currentTarget);
                    setInviteLink("");
                    inviteUser.mutate({ email: fd.get("email"), full_name: fd.get("full_name"), role_id: fd.get("role_id") });
                    (e.target as HTMLFormElement).reset();
                  }}>
                  <h4 className="font-display text-lg font-bold text-navy">Invite a firm member</h4>
                  <p className="text-xs text-ink/50">They&apos;ll get an email link to set a password (or sign in with Google), joining with the role you pick.</p>
                  <input name="full_name" className="input" placeholder="Full name" />
                  <input name="email" type="email" className="input" placeholder="Email" required />
                  <select name="role_id" className="input" required defaultValue="">
                    <option value="" disabled>Select a role…</option>
                    {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                  {inviteUser.isError && <p className="text-xs text-red-600">{(inviteUser.error as Error).message}</p>}
                  {inviteLink && <p className="break-all text-xs text-gold-dim">Invite sent. Dev link: <code>{inviteLink}</code></p>}
                  <button className="btn-gold w-full" disabled={inviteUser.isPending}>Send invite</button>
                </form>
              )}

              {canInvite && (
                <form className="card space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const fd = new FormData(e.currentTarget);
                    createUser.mutate({
                      email: fd.get("email"), full_name: fd.get("full_name"),
                      password: fd.get("password"), client_id: fd.get("client_id") || null,
                    });
                    (e.target as HTMLFormElement).reset();
                  }}>
                  <h4 className="font-display text-lg font-bold text-navy">Create a client portal account</h4>
                  <input name="full_name" className="input" placeholder="Full name" required />
                  <input name="email" type="email" className="input" placeholder="Email" required />
                  <div className="grid grid-cols-2 gap-2">
                    <input name="password" className="input" placeholder="Temp password" required />
                    <select name="client_id" className="input" required defaultValue="">
                      <option value="" disabled>Link to client…</option>
                      {(clientsData?.clients || []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </div>
                  {createUser.isError && <p className="text-xs text-red-600">{(createUser.error as Error).message}</p>}
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

// --- Roles manager ----------------------------------------------------------

function RolesManager({ roles }: { roles: Role[] }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Role | "new" | null>(null);

  const { data: catalogData } = useQuery({ queryKey: ["permissions"], queryFn: () => api("/api/v1/permissions") });
  const { data: templatesData } = useQuery({ queryKey: ["role-templates"], queryFn: () => api("/api/v1/role-templates") });
  const catalog: PermissionDef[] = catalogData?.permissions || [];
  const templates: Template[] = templatesData?.templates || [];

  const del = useMutation({
    mutationFn: (id: string) => api(`/api/v1/roles/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["roles"] }),
  });

  return (
    <section>
      <div className="flex items-center justify-between">
        <h3 className="font-display text-xl font-bold text-navy">Roles &amp; permissions</h3>
        <button className="btn-gold !py-1.5 !text-sm" onClick={() => setEditing("new")}>+ New role</button>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {roles.map((r) => (
          <div key={r.id} className="card !py-3">
            <div className="flex items-start justify-between">
              <div>
                <span className="font-semibold text-navy">{r.name}</span>
                {r.is_protected && <span className="ml-2 rounded bg-navy/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-navy">protected</span>}
                <p className="text-xs text-ink/50">{r.description || "—"}</p>
                <p className="mt-1 text-xs text-ink/40">{r.permissions.length} permissions · {r.member_count} member{r.member_count === 1 ? "" : "s"}</p>
              </div>
              <div className="flex gap-2 text-xs">
                <button className="text-navy hover:underline disabled:opacity-40" disabled={r.is_protected} onClick={() => setEditing(r)}>Edit</button>
                <button className="text-red-600 hover:underline disabled:opacity-40"
                  disabled={r.is_protected || r.member_count > 0}
                  title={r.member_count > 0 ? "Reassign members first" : ""}
                  onClick={() => confirm(`Delete role "${r.name}"?`) && del.mutate(r.id)}>Delete</button>
              </div>
            </div>
          </div>
        ))}
      </div>
      {del.isError && <p className="mt-2 text-xs text-red-600">{(del.error as Error).message}</p>}

      {editing && (
        <RoleEditor
          role={editing === "new" ? null : editing}
          catalog={catalog}
          templates={templates}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["roles"] }); }}
        />
      )}
    </section>
  );
}

function RoleEditor({
  role, catalog, templates, onClose, onSaved,
}: {
  role: Role | null;
  catalog: PermissionDef[];
  templates: Template[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(role?.name || "");
  const [description, setDescription] = useState(role?.description || "");
  const [selected, setSelected] = useState<Set<string>>(new Set(role?.permissions || []));

  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, permissions: [...selected] };
      return role
        ? api(`/api/v1/roles/${role.id}`, { method: "PATCH", body: JSON.stringify(body) })
        : api("/api/v1/roles", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: onSaved,
  });

  const byResource = useMemo(() => {
    const groups: Record<string, PermissionDef[]> = {};
    for (const p of catalog) (groups[p.resource] ||= []).push(p);
    return Object.entries(groups);
  }, [catalog]);

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }
  function applyTemplate(t: Template) {
    setSelected(new Set(t.permissions));
    if (!name) setName(t.name);
    if (!description) setDescription(t.description);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-xl font-bold text-navy">{role ? `Edit ${role.name}` : "New role"}</h3>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <input className="input" placeholder="Role name" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="input" placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        {!role && templates.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink/50">Start from a template:</span>
            {templates.filter((t) => !t.is_protected).map((t) => (
              <button key={t.name} className="rounded border border-navy/20 px-2 py-1 hover:border-gold" onClick={() => applyTemplate(t)}>{t.name}</button>
            ))}
          </div>
        )}

        <div className="mt-4 space-y-4">
          {byResource.map(([resource, perms]) => (
            <div key={resource}>
              <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">{resource.replace("_", " ")}</p>
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {perms.map((p) => (
                  <label key={p.key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={selected.has(p.key)} onChange={() => toggle(p.key)} />
                    {p.label}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        {save.isError && <p className="mt-3 text-xs text-red-600">{(save.error as Error).message}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn-gold" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : role ? "Save changes" : "Create role"}
          </button>
        </div>
      </div>
    </div>
  );
}
