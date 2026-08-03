"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmtKES } from "@/lib/api";

export default function Dashboard() {
  const { data } = useQuery({ queryKey: ["dashboard"], queryFn: () => api("/api/v1/dashboard") });
  const { data: notif } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api("/api/v1/notifications"),
  });
  const s = data?.stats || {};
  const cards = [
    { label: "Open matters", value: s.open_matters ?? "—" },
    { label: "Court dates (7 days)", value: s.court_dates_7d ?? "—" },
    { label: "Deadlines (7 days)", value: s.deadlines_7d ?? "—" },
    { label: "Outstanding fees", value: s.outstanding_kes != null ? fmtKES(s.outstanding_kes) : "—" },
    { label: "Collected (30 days)", value: s.collected_30d_kes != null ? fmtKES(s.collected_30d_kes) : "—" },
    { label: "Clients", value: s.clients ?? "—" },
  ];
  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Dashboard</h2>
      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="card">
            <p className="text-xs uppercase tracking-wide text-ink/50">{c.label}</p>
            <p className="mt-2 font-display text-3xl font-bold text-navy">{c.value}</p>
          </div>
        ))}
      </div>
      <h3 className="mt-10 font-display text-xl font-bold text-navy">Notifications</h3>
      <div className="mt-3 space-y-2">
        {(notif?.notifications || []).length === 0 && (
          <p className="text-sm text-ink/50">No notifications yet.</p>
        )}
        {(notif?.notifications || []).map((n: any) => (
          <div key={n.id} className="card !p-3 text-sm">
            <span className="badge-public mr-2">{n.kind}</span>
            {n.body}
          </div>
        ))}
      </div>
    </div>
  );
}
