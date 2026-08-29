"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, fmtKES } from "@/lib/api";

export default function BillingPage() {
  const qc = useQueryClient();
  const [payingInvoice, setPayingInvoice] = useState<any>(null);
  const [phone, setPhone] = useState("2547");
  const [payMsg, setPayMsg] = useState("");

  const { data: invoicesData } = useQuery({ queryKey: ["invoices"], queryFn: () => api("/api/v1/invoices") });
  const { data: timeData } = useQuery({
    queryKey: ["time-entries"],
    queryFn: () => api("/api/v1/time-entries?unbilled=true"),
  });
  const { data: filesData } = useQuery({ queryKey: ["files", ""], queryFn: () => api("/api/v1/files") });

  const addTime = useMutation({
    mutationFn: (body: any) => api("/api/v1/time-entries", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["time-entries"] }),
  });

  const invoiceFromTime = useMutation({
    mutationFn: (m: any) =>
      api("/api/v1/invoices", {
        method: "POST",
        body: JSON.stringify({ client_id: m.client_id, file_id: m.id, from_time_entries: true }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["time-entries"] });
    },
  });

  const stk = useMutation({
    mutationFn: ({ id, phone }: { id: string; phone: string }) =>
      api(`/api/v1/invoices/${id}/stk-push`, { method: "POST", body: JSON.stringify({ phone }) }),
    onSuccess: (d) => setPayMsg(d.customer_message || "STK push sent — check the phone."),
    onError: (e) => setPayMsg((e as Error).message),
  });

  const unbilledByFile: Record<string, { minutes: number; file?: any }> = {};
  for (const t of timeData?.time_entries || []) {
    unbilledByFile[t.file_id] = unbilledByFile[t.file_id] || { minutes: 0 };
    unbilledByFile[t.file_id].minutes += t.minutes;
    unbilledByFile[t.file_id].file = (filesData?.files || []).find((m: any) => m.id === t.file_id);
  }

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Billing</h2>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="card">
          <h3 className="mb-3 font-display text-lg font-bold text-navy">Log time</h3>
          <form className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              addTime.mutate({
                file_id: fd.get("file_id"), description: fd.get("description"),
                minutes: Number(fd.get("minutes")), rate_kes: Number(fd.get("rate")),
              });
              (e.target as HTMLFormElement).reset();
            }}>
            <select name="file_id" className="input" required>
              <option value="">Select file…</option>
              {(filesData?.files || []).map((m: any) => (
                <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>
              ))}
            </select>
            <input name="description" className="input" placeholder="Description" required />
            <div className="grid grid-cols-2 gap-2">
              <input name="minutes" type="number" className="input" placeholder="Minutes" required />
              <input name="rate" type="number" className="input" placeholder="Rate KES/hr" required />
            </div>
            <button className="btn-primary w-full" disabled={addTime.isPending}>Add entry</button>
          </form>

          <h3 className="mb-2 mt-6 font-display text-lg font-bold text-navy">Unbilled time</h3>
          {Object.entries(unbilledByFile).map(([mid, info]) => (
            <div key={mid} className="mb-2 flex items-center justify-between text-sm">
              <span className="truncate">{info.file?.reference || mid} · {(info.minutes / 60).toFixed(1)}h</span>
              {info.file?.client_id && (
                <button className="btn-gold !px-2 !py-1 !text-xs"
                  onClick={() => invoiceFromTime.mutate(info.file)} disabled={invoiceFromTime.isPending}>
                  Invoice
                </button>
              )}
            </div>
          ))}
          {Object.keys(unbilledByFile).length === 0 && <p className="text-sm text-ink/50">Nothing unbilled.</p>}
        </div>

        <div className="card lg:col-span-2 overflow-x-auto !p-0">
          <table className="w-full text-sm">
            <thead className="bg-navy/5 text-left text-xs uppercase tracking-wide text-navy/60">
              <tr>
                <th className="p-3">Number</th><th className="p-3">Client</th><th className="p-3">Total</th>
                <th className="p-3">Status</th><th className="p-3">Due</th><th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {(invoicesData?.invoices || []).map((inv: any) => (
                <tr key={inv.id} className="border-t border-navy/5">
                  <td className="p-3 font-medium">{inv.number}</td>
                  <td className="p-3">{inv.client_name}</td>
                  <td className="p-3">{fmtKES(inv.total_kes)}</td>
                  <td className="p-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      inv.status === "paid" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                      {inv.status}
                    </span>
                  </td>
                  <td className="p-3">{inv.due_at ? fmtDate(inv.due_at) : "—"}</td>
                  <td className="p-3">
                    {inv.status !== "paid" && (
                      <button className="btn-gold !px-2 !py-1 !text-xs" onClick={() => { setPayingInvoice(inv); setPayMsg(""); }}>
                        M-Pesa
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {payingInvoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4">
          <div className="card w-full max-w-sm space-y-3">
            <h3 className="font-display text-xl font-bold text-navy">
              Pay {payingInvoice.number} · {fmtKES(payingInvoice.total_kes)}
            </h3>
            <p className="text-xs text-ink/60">An M-Pesa STK prompt will be pushed to the payer's phone.</p>
            <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="2547XXXXXXXX" />
            {payMsg && <p className="text-sm text-gold-dim">{payMsg}</p>}
            <div className="flex justify-end gap-2">
              <button className="btn-primary !bg-ink/20 !text-ink" onClick={() => setPayingInvoice(null)}>Close</button>
              <button className="btn-gold" disabled={stk.isPending}
                onClick={() => stk.mutate({ id: payingInvoice.id, phone })}>
                {stk.isPending ? "Sending…" : "Send STK push"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
