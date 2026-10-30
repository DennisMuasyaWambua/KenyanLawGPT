"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";
import NewFileDialog from "@/components/NewFileDialog";

const STATUSES = ["intake", "active", "awaiting_court", "appeal", "closed"];
const STATUS_LABEL: Record<string, string> = {
  intake: "Intake", active: "Active", awaiting_court: "Awaiting Court",
  appeal: "Appeal", closed: "Closed",
};

export default function FilesPage() {
  const { can } = usePermissions();
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);

  const { data } = useQuery({
    queryKey: ["files", search],
    queryFn: () => api(`/api/v1/files?q=${encodeURIComponent(search)}`),
  });
  const files = data?.files || [];

  return (
    <div>
      {/* Wraps on phones: the New-file button used to sit off-screen to the right. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-3xl font-bold text-navy">Files</h2>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          {can("matters.create") && (
            <button className="btn-gold order-first sm:order-last" onClick={() => setShowNew(true)}>+ New file</button>
          )}
          <input className="input min-w-0 flex-1 sm:!w-56 sm:flex-none" placeholder="Search files…" value={search}
            onChange={(e) => setSearch(e.target.value)} />
          <button className="btn-primary" onClick={() => setView(view === "kanban" ? "list" : "kanban")}>
            {view === "kanban" ? "List view" : "Kanban view"}
          </button>
        </div>
      </div>

      {view === "kanban" ? (
        <div className="mt-6 grid grid-flow-col auto-cols-[minmax(14rem,1fr)] gap-3 overflow-x-auto pb-2 lg:grid-flow-row lg:grid-cols-5">
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

      {showNew && <NewFileDialog onClose={() => setShowNew(false)} />}
    </div>
  );
}
