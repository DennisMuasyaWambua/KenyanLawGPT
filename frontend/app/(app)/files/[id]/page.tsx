"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

const STATUSES = ["intake", "active", "awaiting_court", "appeal", "closed"];

export default function FileDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { can } = usePermissions();

  const { data } = useQuery({ queryKey: ["file", id], queryFn: () => api(`/api/v1/files/${id}`) });
  const { data: docs } = useQuery({
    queryKey: ["archives", id],
    queryFn: () => api(`/api/v1/archives?file_id=${id}`),
  });
  const { data: judiciary, refetch: refetchJudiciary, isFetching: judLoading } = useQuery({
    queryKey: ["judiciary", id],
    queryFn: () => api(`/api/v1/files/${id}/judiciary`),
    enabled: false,
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const presign = await api("/api/v1/archives/presign", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name, mime_type: file.type || "application/octet-stream",
          size_bytes: file.size, file_id: id, doc_kind: "evidence",
        }),
      });
      const put = await fetch(presign.upload_url, { method: "PUT", body: file });
      if (!put.ok) throw new Error("upload to storage failed");
      return api(`/api/v1/archives/${presign.archive.id}/ingest`, { method: "POST" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["archives", id] }),
  });

  // Case-status control (with optional auto-notify of the client on change).
  const [statusSel, setStatusSel] = useState("");
  const [notify, setNotify] = useState(true);
  const saveStatus = useMutation({
    mutationFn: () => {
      const cur = data?.file;
      return api(`/api/v1/files/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          reference: cur.reference, title: cur.title, description: cur.description || "",
          client_id: cur.client_id ?? null, status: statusSel || cur.status,
          practice_area: cur.practice_area || "", court: cur.court || "",
          court_case_number: cur.court_case_number || "", assigned_to: cur.assigned_to ?? null,
          notify_client: notify,
        }),
      });
    },
    onSuccess: () => { setStatusSel(""); qc.invalidateQueries({ queryKey: ["file", id] }); },
  });

  // Manual, free-text case-progress update to the client (email + SMS).
  const [updateMsg, setUpdateMsg] = useState("");
  const [chEmail, setChEmail] = useState(true);
  const [chSms, setChSms] = useState(true);
  const sendUpdate = useMutation({
    mutationFn: () => {
      const channels = [chEmail ? "email" : null, chSms ? "sms" : null].filter(Boolean);
      return api(`/api/v1/files/${id}/notify-client`, {
        method: "POST",
        body: JSON.stringify({ message: updateMsg, channels }),
      });
    },
    onSuccess: () => { setUpdateMsg(""); qc.invalidateQueries({ queryKey: ["file", id] }); },
  });

  const m = data?.file;
  if (!m) return <p className="text-sm text-ink/50">Loading…</p>;

  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink/40">{m.reference} · {m.practice_area}</p>
      <h2 className="font-display text-3xl font-bold text-navy">{m.title}</h2>
      <p className="mt-1 text-sm text-ink/60">
        {m.client_name && <>Client: <b>{m.client_name}</b> · </>}
        Status: <span className="capitalize">{m.status}</span>
        {m.court && <> · {m.court} {m.court_case_number}</>}
      </p>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <h3 className="mb-3 font-display text-lg font-bold text-navy">Timeline</h3>
          <div className="space-y-2">
            {(data?.events || []).map((e: any) => (
              <div key={e.id} className="border-l-2 border-gold pl-3 text-sm">
                <p className="font-medium">{e.event_type.replace("_", " ")}</p>
                <p className="text-xs text-ink/60">{e.note}</p>
                <p className="text-[10px] text-ink/40">{fmtDate(e.created_at)}</p>
              </div>
            ))}
          </div>
          {m.description && (
            <>
              <h3 className="mb-2 mt-6 font-display text-lg font-bold text-navy">Background</h3>
              <p className="text-sm text-ink/70">{m.description}</p>
            </>
          )}
        </div>

        <div className="space-y-6">
          {can("matters.edit") && (
            <div className="card">
              <h3 className="mb-3 font-display text-lg font-bold text-navy">Case status</h3>
              <select className="input" value={statusSel || m.status} onChange={(e) => setStatusSel(e.target.value)}>
                {Array.from(new Set([...STATUSES, m.status])).map((st) => (
                  <option key={st} value={st}>{st.replace(/_/g, " ")}</option>
                ))}
              </select>
              <label className="mt-3 flex items-center gap-2 text-xs text-ink/70">
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
                Notify client of this change (email + SMS)
              </label>
              <button
                className="btn-primary mt-3 w-full"
                disabled={saveStatus.isPending || (statusSel || m.status) === m.status}
                onClick={() => saveStatus.mutate()}
              >
                {saveStatus.isPending ? "Saving…" : "Update status"}
              </button>
              {saveStatus.isSuccess && <p className="mt-2 text-xs text-green-700">Status updated.</p>}
              {saveStatus.isError && <p className="mt-2 text-xs text-red-600">{(saveStatus.error as Error).message}</p>}
            </div>
          )}

          {can("comms.send") && (
            <div className="card">
              <h3 className="mb-3 font-display text-lg font-bold text-navy">Send update to client</h3>
              <textarea
                className="input"
                rows={3}
                placeholder="Progress update for the client…"
                value={updateMsg}
                onChange={(e) => setUpdateMsg(e.target.value)}
              />
              <div className="mt-2 flex gap-4 text-xs text-ink/70">
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={chEmail} onChange={(e) => setChEmail(e.target.checked)} /> Email
                </label>
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={chSms} onChange={(e) => setChSms(e.target.checked)} /> SMS
                </label>
              </div>
              <button
                className="btn-gold mt-3 w-full"
                disabled={sendUpdate.isPending || !updateMsg.trim() || (!chEmail && !chSms)}
                onClick={() => sendUpdate.mutate()}
              >
                {sendUpdate.isPending ? "Sending…" : "Send update"}
              </button>
              {sendUpdate.isSuccess && (
                <p className="mt-2 text-xs text-green-700">
                  Sent via {(sendUpdate.data as any).sent?.join(", ") || "—"}
                  {(sendUpdate.data as any).skipped?.length
                    ? ` · skipped: ${(sendUpdate.data as any).skipped.join(", ")}`
                    : ""}
                </p>
              )}
              {sendUpdate.isError && <p className="mt-2 text-xs text-red-600">{(sendUpdate.error as Error).message}</p>}
              <p className="mt-2 text-[10px] text-ink/40">
                Requires the client to have consented (KDPA). Updates also appear in the client portal.
              </p>
            </div>
          )}

          <div className="card">
            <h3 className="mb-3 font-display text-lg font-bold text-navy">Court status</h3>
            <button className="btn-primary w-full" onClick={() => refetchJudiciary()} disabled={judLoading}>
              {judLoading ? "Checking…" : "Check Judiciary status"}
            </button>
            {judiciary?.status && (
              <div className="mt-3 space-y-1 text-sm">
                <p><b>{judiciary.status.status}</b></p>
                <p className="text-xs text-ink/60">Next hearing: {judiciary.status.next_hearing}</p>
                <p className="text-xs text-ink/60">{judiciary.status.last_order}</p>
                {judiciary.status.from_cache && (
                  <p className="text-[10px] text-amber-600">served from cache (source unavailable)</p>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <h3 className="mb-3 font-display text-lg font-bold text-navy">Archives</h3>
            <label className="btn-gold block cursor-pointer text-center">
              {upload.isPending ? "Uploading & ingesting…" : "Upload archive"}
              <input type="file" className="hidden"
                onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
            {upload.isError && <p className="mt-2 text-xs text-red-600">{(upload.error as Error).message}</p>}
            <div className="mt-3 space-y-2">
              {(docs?.archives || []).map((d: any) => (
                <div key={d.id} className="flex items-center justify-between text-sm">
                  <span className="truncate">{d.filename}</span>
                  <span className={`ml-2 text-[10px] uppercase ${
                    d.ingest_status === "ingested" ? "text-green-700" : "text-amber-600"}`}>
                    {d.ingest_status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
