"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type Role = {
  id: string;
  name: string;
  description: string;
  is_protected: boolean;
  permissions: string[];
  member_count: number;
};
type PermissionDef = { key: string; resource: string; action: string; label: string };
type Template = { name: string; description: string; is_protected: boolean; permissions: string[] };

// Firm RBAC policy editor: each role's granular permissions, from the gateway's
// fixed catalog. Shared by Settings and the post-signup onboarding wizard.
export default function RolesManager({ roles, embedded = false }: { roles: Role[]; embedded?: boolean }) {
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
      <div className="flex items-center justify-between gap-3">
        {embedded ? <span /> : <h3 className="font-display text-xl font-bold text-navy">Roles &amp; permissions</h3>}
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
