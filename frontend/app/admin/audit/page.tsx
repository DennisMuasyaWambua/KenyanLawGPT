"use client";

import { useQuery } from "@tanstack/react-query";
import { adminApi } from "@/lib/admin";

type Entry = {
  created_at: string; firm_name: string; tenant_id: string;
  user_id: string | null; action: string; resource: string; status: number; ip: string;
};

const fmt = (s: string) => new Date(s).toLocaleString("en-KE", { dateStyle: "medium", timeStyle: "short" });

export default function AdminAudit() {
  const { data } = useQuery({ queryKey: ["admin-audit"], queryFn: () => adminApi("/audit?limit=200") });
  const entries: Entry[] = data?.entries || [];

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Audit log</h2>
      <p className="mt-1 text-sm text-ink/50">Cross-tenant activity across every firm (most recent 200).</p>
      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-navy/10 text-left text-xs uppercase tracking-wide text-ink/50">
              <th className="py-2 pr-3">Time</th>
              <th className="py-2 pr-3">Firm</th>
              <th className="py-2 pr-3">Action</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">IP</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} className="border-b border-navy/5">
                <td className="whitespace-nowrap py-2 pr-3 text-ink/70">{fmt(e.created_at)}</td>
                <td className="py-2 pr-3">{e.firm_name || <span className="text-ink/40">—</span>}</td>
                <td className="py-2 pr-3 font-mono text-xs">{e.action}</td>
                <td className="py-2 pr-3">
                  <span className={e.status >= 400 ? "text-red-600" : "text-green-700"}>{e.status || "—"}</span>
                </td>
                <td className="py-2 pr-3 text-xs text-ink/50">{e.ip}</td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-ink/50">No audit activity yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
