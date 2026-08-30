"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";

type CaseStatus = {
  file_id: string; reference: string; title: string; client_name: string;
  status: string; open_tasks: number; overdue_tasks: number; last_activity: string;
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-800", intake: "bg-blue-100 text-blue-800",
  awaiting_court: "bg-amber-100 text-amber-800", appeal: "bg-purple-100 text-purple-800",
  on_hold: "bg-gray-200 text-gray-700", closed: "bg-navy/10 text-navy/60",
};

export default function CasesPage() {
  const { data, isLoading } = useQuery({ queryKey: ["cases"], queryFn: () => api("/api/v1/dashboard/cases") });
  const cases: CaseStatus[] = data?.cases || [];

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Case status</h2>
      <p className="mt-1 text-sm text-ink/60">Firm-wide view across all files — open work, overdue items and activity.</p>

      <div className="card mt-4 !p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-navy/5 text-left text-xs uppercase text-navy/60">
            <tr>
              <th className="p-3">File</th><th className="p-3">Client</th><th className="p-3">Status</th>
              <th className="p-3 text-center">Open tasks</th><th className="p-3 text-center">Overdue</th><th className="p-3">Last activity</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={6} className="p-4 text-center text-ink/50">Loading…</td></tr>}
            {!isLoading && cases.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-ink/50">No files yet.</td></tr>}
            {cases.map((c) => (
              <tr key={c.file_id} className="border-t border-navy/5">
                <td className="p-3">
                  <div className="font-medium text-navy">{c.reference}</div>
                  <div className="truncate text-xs text-ink/50">{c.title}</div>
                </td>
                <td className="p-3 text-xs">{c.client_name || "—"}</td>
                <td className="p-3">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_COLORS[c.status] || "bg-navy/10 text-navy"}`}>
                    {c.status.replace("_", " ")}
                  </span>
                </td>
                <td className="p-3 text-center">{c.open_tasks}</td>
                <td className={`p-3 text-center ${c.overdue_tasks > 0 ? "font-bold text-red-600" : "text-ink/40"}`}>{c.overdue_tasks}</td>
                <td className="p-3 text-xs text-ink/60">{fmtDate(c.last_activity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
