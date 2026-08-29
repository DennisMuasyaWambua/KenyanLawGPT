"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";

const STATUSES = ["intake", "active", "awaiting_court", "appeal", "closed"];
const STATUS_LABEL: Record<string, string> = {
  intake: "Intake", active: "Active", awaiting_court: "Awaiting Court",
  appeal: "Appeal", closed: "Closed",
};

export default function FilesPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { data } = useQuery({
    queryKey: ["files", search],
    queryFn: () => api(`/api/v1/files?q=${encodeURIComponent(search)}`),
  });
  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => api("/api/v1/clients"),
  });
  const files = data?.files || [];

  const create = useMutation({
    mutationFn: (body: any) => api("/api/v1/files", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["files"] });
      setShowNew(false);
    },
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Files</h2>
        <div className="flex gap-2">
          <input className="input !w-56" placeholder="Search files…" value={search}
            onChange={(e) => setSearch(e.target.value)} />
          <button className="btn-primary" onClick={() => setView(view === "kanban" ? "list" : "kanban")}>
            {view === "kanban" ? "List view" : "Kanban view"}
          </button>
          <button className="btn-gold" onClick={() => setShowNew(true)}>+ New file</button>
        </div>
      </div>

      {view === "kanban" ? (
        <div className="mt-6 grid grid-cols-5 gap-3">
          {STATUSES.map((st) => (
            <div key={st} className="rounded-lg bg-navy/5 p-2">
              <p className="mb-2 px-1 text-xs font-bold uppercase tracking-wide text-navy/60">
                {STATUS_LABEL[st]} ({files.filter((m: any) => m.status === st).length})
              </p>
              <div className="space-y-2">
                {files.filter((m: any) => m.status === st).map((m: any) => (
                  <Link key={m.id} href={`/files/${m.id}`}
                    className="block rounded-md border border-navy/10 bg-white p-3 text-sm shadow-sm hover:border-gold">
                    <p className="font-semibold text-navy">{m.title}</p>
                    <p className="mt-1 text-xs text-ink/50">{m.reference}</p>
                    {m.client_name && <p className="mt-1 text-xs text-gold-dim">{m.client_name}</p>}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card mt-6 overflow-x-auto !p-0">
          <table className="w-full text-sm">
            <thead className="bg-navy/5 text-left text-xs uppercase tracking-wide text-navy/60">
              <tr>
                <th className="p-3">Reference</th><th className="p-3">Title</th>
                <th className="p-3">Client</th><th className="p-3">Practice area</th>
                <th className="p-3">Status</th><th className="p-3">Updated</th>
              </tr>
            </thead>
            <tbody>
              {files.map((m: any) => (
                <tr key={m.id} className="border-t border-navy/5 hover:bg-paper">
                  <td className="p-3"><Link className="text-gold-dim hover:underline" href={`/files/${m.id}`}>{m.reference}</Link></td>
                  <td className="p-3">{m.title}</td>
                  <td className="p-3">{m.client_name}</td>
                  <td className="p-3">{m.practice_area}</td>
                  <td className="p-3 capitalize">{STATUS_LABEL[m.status] || m.status}</td>
                  <td className="p-3">{fmtDate(m.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4">
          <form
            className="card w-full max-w-lg space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              create.mutate({
                reference: fd.get("reference"), title: fd.get("title"),
                description: fd.get("description"), practice_area: fd.get("practice_area"),
                court: fd.get("court"), court_case_number: fd.get("court_case_number"),
                client_id: fd.get("client_id") || null,
              });
            }}
          >
            <h3 className="font-display text-xl font-bold text-navy">New file</h3>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label">Reference</label><input name="reference" className="input" required /></div>
              <div><label className="label">Practice area</label><input name="practice_area" className="input" /></div>
            </div>
            <div><label className="label">Title</label><input name="title" className="input" required /></div>
            <div><label className="label">Description</label><textarea name="description" className="input" rows={2} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label">Court</label><input name="court" className="input" /></div>
              <div><label className="label">Case number</label><input name="court_case_number" className="input" /></div>
            </div>
            <div>
              <label className="label">Client</label>
              <select name="client_id" className="input">
                <option value="">— none —</option>
                {(clientsData?.clients || []).map((c: any) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            {create.isError && <p className="text-sm text-red-600">{(create.error as Error).message}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-primary !bg-ink/20 !text-ink" onClick={() => setShowNew(false)}>Cancel</button>
              <button className="btn-gold" disabled={create.isPending}>Create</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
