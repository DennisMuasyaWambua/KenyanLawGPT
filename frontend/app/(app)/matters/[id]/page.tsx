"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";

export default function MatterDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  const { data } = useQuery({ queryKey: ["matter", id], queryFn: () => api(`/api/v1/matters/${id}`) });
  const { data: docs } = useQuery({
    queryKey: ["documents", id],
    queryFn: () => api(`/api/v1/documents?matter_id=${id}`),
  });
  const { data: judiciary, refetch: refetchJudiciary, isFetching: judLoading } = useQuery({
    queryKey: ["judiciary", id],
    queryFn: () => api(`/api/v1/matters/${id}/judiciary`),
    enabled: false,
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const presign = await api("/api/v1/documents/presign", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name, mime_type: file.type || "application/octet-stream",
          size_bytes: file.size, matter_id: id, doc_kind: "evidence",
        }),
      });
      const put = await fetch(presign.upload_url, { method: "PUT", body: file });
      if (!put.ok) throw new Error("upload to storage failed");
      return api(`/api/v1/documents/${presign.document.id}/ingest`, { method: "POST" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents", id] }),
  });

  const m = data?.matter;
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
            <h3 className="mb-3 font-display text-lg font-bold text-navy">Documents</h3>
            <label className="btn-gold block cursor-pointer text-center">
              {upload.isPending ? "Uploading & ingesting…" : "Upload document"}
              <input type="file" className="hidden"
                onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
            {upload.isError && <p className="mt-2 text-xs text-red-600">{(upload.error as Error).message}</p>}
            <div className="mt-3 space-y-2">
              {(docs?.documents || []).map((d: any) => (
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
