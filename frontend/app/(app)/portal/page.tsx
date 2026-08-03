"use client";

import { useQuery } from "@tanstack/react-query";
import { api, currentUser, fmtDate, fmtKES } from "@/lib/api";

// Client portal: strictly scoped server-side to the signed-in client's own
// matters, invoices and messages.
export default function PortalPage() {
  const me = currentUser();
  const { data: matters } = useQuery({ queryKey: ["portal-matters"], queryFn: () => api("/api/v1/portal/matters") });
  const { data: invoices } = useQuery({ queryKey: ["portal-invoices"], queryFn: () => api("/api/v1/portal/invoices") });
  const { data: messages } = useQuery({ queryKey: ["portal-messages"], queryFn: () => api("/api/v1/portal/messages") });

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Welcome, {me?.full_name}</h2>
      <p className="mt-1 text-sm text-ink/60">Your matters with the firm, invoices and updates.</p>

      <h3 className="mt-8 font-display text-xl font-bold text-navy">My matters</h3>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {(matters?.matters || []).map((m: any) => (
          <div key={m.id} className="card">
            <p className="text-xs text-ink/40">{m.reference}</p>
            <p className="font-semibold text-navy">{m.title}</p>
            <p className="mt-1 text-xs capitalize text-gold-dim">status: {m.status.replace("_", " ")}</p>
            {m.court && <p className="text-xs text-ink/50">{m.court} {m.court_case_number}</p>}
          </div>
        ))}
        {(matters?.matters || []).length === 0 && <p className="text-sm text-ink/50">No matters yet.</p>}
      </div>

      <h3 className="mt-8 font-display text-xl font-bold text-navy">Invoices</h3>
      <div className="card mt-3 !p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy/5 text-left text-xs uppercase text-navy/60">
            <tr><th className="p-3">Number</th><th className="p-3">Total</th><th className="p-3">Status</th><th className="p-3">Due</th></tr>
          </thead>
          <tbody>
            {(invoices?.invoices || []).map((inv: any) => (
              <tr key={inv.id} className="border-t border-navy/5">
                <td className="p-3">{inv.number}</td>
                <td className="p-3">{fmtKES(inv.total_kes)}</td>
                <td className="p-3">{inv.status}</td>
                <td className="p-3">{inv.due_at ? fmtDate(inv.due_at) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-8 font-display text-xl font-bold text-navy">Messages</h3>
      <div className="mt-3 space-y-2">
        {(messages?.messages || []).map((m: any) => (
          <div key={m.id} className="card !p-3 text-sm">
            <p className="text-xs text-ink/40">{m.channel} · {fmtDate(m.created_at)}</p>
            {m.body}
          </div>
        ))}
      </div>
    </div>
  );
}
