"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";

const CHANNELS = ["", "sms", "email", "whatsapp", "inapp"];

export default function InboxPage() {
  const qc = useQueryClient();
  const [channel, setChannel] = useState("");
  const [showCompose, setShowCompose] = useState(false);

  const { data } = useQuery({
    queryKey: ["messages", channel],
    queryFn: () => api(`/api/v1/messages?channel=${channel}`),
  });
  const { data: clientsData } = useQuery({ queryKey: ["clients"], queryFn: () => api("/api/v1/clients") });

  const [sendError, setSendError] = useState("");
  const [sentNote, setSentNote] = useState("");
  const send = useMutation({
    mutationFn: (body: any) => api("/api/v1/messages/send", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ["messages"] });
      // The API answers 201 even when the provider rejected the message; keep the
      // form open and say why, rather than silently closing on a failed send.
      if (res?.message?.status === "failed") {
        setSendError(res.error ? `Message was not delivered: ${res.error}` : "Message was not delivered.");
        return;
      }
      setSendError("");
      setSentNote(res?.message?.status === "queued"
        ? "Saved as queued — this channel isn't connected to a delivery provider yet."
        : "");
      setShowCompose(false);
    },
    onError: (e) => setSendError((e as Error).message),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Communications Hub</h2>
        <button className="btn-gold" onClick={() => { setSendError(""); setSentNote(""); setShowCompose(true); }}>+ Compose</button>
      </div>
      {sentNote && <p className="mt-3 rounded bg-amber-100 px-3 py-2 text-xs text-amber-800">{sentNote}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        {CHANNELS.map((c) => (
          <button key={c}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              channel === c ? "bg-navy text-white" : "bg-navy/10 text-navy"}`}
            onClick={() => setChannel(c)}>
            {c === "" ? "all" : c}
          </button>
        ))}
      </div>
      <div className="mt-4 space-y-2">
        {(data?.messages || []).map((m: any) => (
          <div key={m.id} className="card !p-3">
            <div className="flex items-center gap-2 text-xs text-ink/50">
              <span className="badge-public">{m.channel}</span>
              <span>{m.direction}</span>
              <span>→ {m.to_addr || "in-app"}</span>
              <span className={`ml-auto font-semibold ${
                m.status === "delivered" ? "text-green-700" :
                m.status === "failed" ? "text-red-600" : "text-amber-600"}`}>
                {m.status}
              </span>
              <span>{fmtDate(m.created_at)}</span>
            </div>
            <p className="mt-1 text-sm">{m.body}</p>
          </div>
        ))}
        {(data?.messages || []).length === 0 && (
          <p className="text-sm text-ink/50">No messages on this channel yet.</p>
        )}
      </div>

      {showCompose && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4">
          <form className="card w-full max-w-lg space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              send.mutate({
                channel: fd.get("channel"), to: fd.get("to"), subject: fd.get("subject"),
                body: fd.get("body"), client_id: fd.get("client_id") || null,
              });
            }}>
            <h3 className="font-display text-xl font-bold text-navy">Send message</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Channel</label>
                <select name="channel" className="input">
                  <option value="sms">SMS (Africa's Talking)</option>
                  <option value="email">Email</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="inapp">In-app</option>
                </select>
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
            </div>
            <div>
              <label className="label">To (07XX…, +2547XX… or email)</label>
              <input name="to" className="input" placeholder="Leave blank to use the selected client's contact" />
            </div>
            <div><label className="label">Subject (email)</label><input name="subject" className="input" /></div>
            <div><label className="label">Message</label><textarea name="body" className="input" rows={4} required /></div>
            {sendError && <p className="text-sm text-red-600">{sendError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-primary !bg-ink/20 !text-ink" onClick={() => setShowCompose(false)}>Cancel</button>
              <button className="btn-gold" disabled={send.isPending}>Send</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
