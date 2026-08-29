"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmtKES } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { usePermissions } from "@/lib/usePermissions";

export default function Dashboard() {
  const { can, permissions } = usePermissions();
  const { data } = useQuery({ queryKey: ["dashboard"], queryFn: () => api("/api/v1/dashboard") });
  const { data: notif } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api("/api/v1/notifications"),
  });
  const s = data?.stats || {};
  // Cards are gated by permission so the dashboard adapts to the designation:
  // interns/associates/clerks -> matters, court dates, deadlines; secretary adds
  // clients; partners/managing partner also see billing.
  const allCards = [
    { label: "Active matters", value: s.open_files ?? "—" },
    { label: "Court dates (7 days)", value: s.court_dates_7d ?? "—" },
    { label: "Deadlines (7 days)", value: s.deadlines_7d ?? "—" },
    { label: "Outstanding fees", value: s.outstanding_kes != null ? fmtKES(s.outstanding_kes) : "—", perm: "billing.view" },
    { label: "Collected (30 days)", value: s.collected_30d_kes != null ? fmtKES(s.collected_30d_kes) : "—", perm: "billing.view" },
    { label: "Clients", value: s.clients ?? "—", perm: "clients.view" },
  ];
  const cards = allCards.filter((c) => !c.perm || permissions.length === 0 || can(c.perm));
  return (
    <div className="relative">
      {/* Faint firm watermark behind the dashboard content. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 flex select-none flex-col items-center justify-center opacity-[0.07]"
      >
        <img src={BRAND.logo} alt="" className="w-2/3 max-w-lg" />
        <p className="mt-4 font-display text-4xl font-bold text-navy">{BRAND.name}</p>
      </div>
      <div className="relative z-10">
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
    </div>
  );
}
