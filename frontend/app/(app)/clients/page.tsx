"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type Client = {
  id: string; name: string; email: string; phone: string; id_number: string;
  status: string; client_type: string; company_reg_number: string;
  conflict_check_at?: string | null; retainer_ref: string; kyc_completed_at?: string | null; kyc_ref: string;
};
type StageEvent = { from_status: string; to_status: string; note: string; created_at: string };

const STAGES = ["lead", "intake", "conflict_check", "engaged", "active", "closed"];
const LABELS: Record<string, string> = {
  lead: "Lead", intake: "Intake", conflict_check: "Conflict check",
  engaged: "Engaged", active: "Active", closed: "Closed",
};
const nextStage = (s: string) => STAGES[STAGES.indexOf(s) + 1];

export default function ClientsPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const [selected, setSelected] = useState<string | null>(null);

  const { data } = useQuery({ queryKey: ["clients"], queryFn: () => api("/api/v1/clients") });
  const clients: Client[] = data?.clients || [];

  const create = useMutation({
    mutationFn: (body: any) => api("/api/v1/clients", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Clients &amp; intake</h2>
      </div>

      {can("clients.create") && (
        <form className="card mt-4 grid grid-cols-1 gap-2 sm:grid-cols-6"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            create.mutate({
              name: fd.get("name"), email: fd.get("email"), phone: fd.get("phone"),
              client_type: fd.get("client_type"),
              id_number: fd.get("id_number"), company_reg_number: fd.get("company_reg_number"),
              kdpa_consent: fd.get("kdpa_consent") === "on",
            });
            (e.target as HTMLFormElement).reset();
          }}>
          <input name="name" className="input sm:col-span-2" placeholder="Client / company name" required />
          <select name="client_type" className="input"><option value="individual">Individual</option><option value="company">Company</option></select>
          <input name="email" type="email" className="input" placeholder="Email" />
          <input name="phone" className="input" placeholder="Phone" />
          <input name="id_number" className="input" placeholder="National ID" />
          <input name="company_reg_number" className="input" placeholder="Company reg. no." />
          <label className="flex items-center gap-2 text-xs text-ink/70"><input type="checkbox" name="kdpa_consent" /> KDPA consent</label>
          <button className="btn-gold sm:col-span-1" disabled={create.isPending}>Add lead</button>
          {create.isError && <p className="text-xs text-red-600 sm:col-span-6">{(create.error as Error).message}</p>}
        </form>
      )}

      {/* Pipeline board */}
      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {STAGES.map((stage) => {
          const inStage = clients.filter((c) => c.status === stage);
          return (
            <div key={stage} className="rounded-lg bg-navy/5 p-2">
              <p className="mb-2 px-1 text-xs font-bold uppercase tracking-wide text-navy/60">
                {LABELS[stage]} <span className="text-navy/30">{inStage.length}</span>
              </p>
              <div className="space-y-2">
                {inStage.map((c) => (
                  <button key={c.id} onClick={() => setSelected(c.id)}
                    className="w-full rounded-md bg-white p-2 text-left shadow-sm hover:ring-1 hover:ring-gold">
                    <div className="truncate text-sm font-medium text-navy">{c.name}</div>
                    <div className="truncate text-[11px] text-ink/50">{c.email || c.phone || c.client_type}</div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <ClientDrawer id={selected} canAdvance={can("clients.advance_stage")} canCreateMatter={can("matters.create")}
          onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function ClientDrawer({ id, canAdvance, canCreateMatter, onClose }: {
  id: string; canAdvance: boolean; canCreateMatter: boolean; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const [retainerRef, setRetainerRef] = useState("");
  const [kycRef, setKycRef] = useState("");

  const { data } = useQuery({ queryKey: ["client", id], queryFn: () => api(`/api/v1/clients/${id}`) });
  const client: Client | undefined = data?.client;
  const history: StageEvent[] = data?.stage_history || [];

  const refresh = () => { qc.invalidateQueries({ queryKey: ["client", id] }); qc.invalidateQueries({ queryKey: ["clients"] }); };

  const conflict = useMutation({
    mutationFn: () => api(`/api/v1/clients/${id}/conflict-check`, { method: "POST" }),
    onSuccess: refresh, onError: (e) => setErr((e as Error).message),
  });
  const advance = useMutation({
    mutationFn: (body: any) => api(`/api/v1/clients/${id}/advance`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => { setErr(""); refresh(); }, onError: (e) => setErr((e as Error).message),
  });
  const openMatter = useMutation({
    mutationFn: (body: any) => api("/api/v1/matters", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => { setErr(""); refresh(); }, onError: (e) => setErr((e as Error).message),
  });

  if (!client) return null;
  const next = nextStage(client.status);

  function doAdvance() {
    setErr("");
    advance.mutate({
      to_status: next, retainer_ref: retainerRef || undefined,
      kyc_ref: kycRef || undefined, kyc_done: !!kycRef,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-display text-xl font-bold text-navy">{client.name}</h3>
            <p className="text-xs text-ink/50">{client.client_type} · {client.email} {client.phone}</p>
          </div>
          <span className="rounded-full bg-gold/20 px-2 py-0.5 text-xs font-semibold text-gold-dim">{LABELS[client.status]}</span>
        </div>

        <div className="mt-4 space-y-1 text-sm">
          <p>National ID: <span className="text-ink/60">{client.id_number || "—"}</span></p>
          {client.company_reg_number && <p>Company reg: <span className="text-ink/60">{client.company_reg_number}</span></p>}
          <p>Conflict check: <span className="text-ink/60">{client.conflict_check_at ? "✓ " + fmtDate(client.conflict_check_at) : "pending"}</span></p>
          <p>Retainer ref: <span className="text-ink/60">{client.retainer_ref || "—"}</span></p>
          <p>KYC/AML: <span className="text-ink/60">{client.kyc_completed_at ? "✓ " + fmtDate(client.kyc_completed_at) : "pending"}</span></p>
        </div>

        {canAdvance && client.status !== "closed" && (
          <div className="card mt-4 space-y-2 !bg-navy/5">
            <p className="text-xs font-bold uppercase tracking-wide text-navy/60">Advance pipeline</p>
            {client.status === "conflict_check" && !client.conflict_check_at && (
              <button className="btn-outline w-full text-sm" onClick={() => conflict.mutate()} disabled={conflict.isPending}>
                Confirm conflict check (manual gate)
              </button>
            )}
            {next === "engaged" && (
              <input className="input" placeholder="Signed retainer reference" value={retainerRef} onChange={(e) => setRetainerRef(e.target.value)} />
            )}
            {next === "active" && (
              <input className="input" placeholder="KYC/AML reference" value={kycRef} onChange={(e) => setKycRef(e.target.value)} />
            )}
            {next && (
              <button className="btn-gold w-full text-sm" onClick={doAdvance} disabled={advance.isPending}>
                Advance to {LABELS[next]}
              </button>
            )}
          </div>
        )}

        {canCreateMatter && (client.status === "engaged" || client.status === "active") && (
          <form className="card mt-4 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              openMatter.mutate({ client_id: id, reference: fd.get("reference"), title: fd.get("title"), practice_area: fd.get("practice_area") });
              (e.target as HTMLFormElement).reset();
            }}>
            <p className="text-xs font-bold uppercase tracking-wide text-navy/60">Open a matter for this client</p>
            <div className="grid grid-cols-2 gap-2">
              <input name="reference" className="input" placeholder="Ref e.g. EMP/2026/004" required />
              <input name="practice_area" className="input" placeholder="Practice area" />
            </div>
            <input name="title" className="input" placeholder="Matter title" required />
            <button className="btn-primary w-full text-sm" disabled={openMatter.isPending}>Open matter</button>
          </form>
        )}

        {err && <p className="mt-3 text-sm text-red-600">{err}</p>}

        <div className="mt-6">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-navy/60">Stage history</p>
          <div className="space-y-1 text-xs text-ink/60">
            {history.length === 0 && <p>No transitions yet.</p>}
            {history.map((h, i) => (
              <p key={i}>{fmtDate(h.created_at)} · {LABELS[h.from_status] || h.from_status} → <b>{LABELS[h.to_status] || h.to_status}</b>{h.note ? ` — ${h.note}` : ""}</p>
            ))}
          </div>
        </div>

        <button className="btn-outline mt-6 w-full" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
