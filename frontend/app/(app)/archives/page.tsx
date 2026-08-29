"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, uploadArchive } from "@/lib/api";
import IngestionStatus, { IngestDoc } from "@/components/IngestionStatus";

const DOC_KINDS = ["other", "contract", "pleading", "correspondence", "evidence", "precedent_note"];

// Persisted archives expose an ingest_status; map it onto the step-based view.
function statusToStage(s: string): { stage: string; progress_pct: number } {
  switch (s) {
    case "ingested":
      return { stage: "DONE", progress_pct: 100 };
    case "ingesting":
      return { stage: "EMBEDDING", progress_pct: 60 };
    case "failed":
      return { stage: "FAILED", progress_pct: 0 };
    default:
      return { stage: "QUEUED", progress_pct: 0 };
  }
}

type LiveUpload = IngestDoc & { key: string };

export default function ArchivesPage() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileId, setFileId] = useState("");
  const [docKind, setDocKind] = useState("other");
  const [live, setLive] = useState<LiveUpload[]>([]);

  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files") });

  const { data: persisted = [] } = useQuery<IngestDoc[]>({
    queryKey: ["archives", fileId],
    queryFn: async () => {
      const q = fileId ? `?file_id=${fileId}` : "";
      const r = await api<{ archives: any[] }>(`/api/v1/archives${q}`);
      return (r.archives || []).map((d) => ({
        id: d.id,
        filename: d.filename,
        doc_kind: d.doc_kind,
        ...statusToStage(d.ingest_status),
      }));
    },
    refetchInterval: (q) =>
      (q.state.data || []).some((d) => d.stage !== "DONE" && d.stage !== "FAILED") ? 3000 : false,
  });

  function patchLive(key: string, patch: Partial<LiveUpload>) {
    setLive((prev) => prev.map((u) => (u.key === key ? { ...u, ...patch } : u)));
  }

  async function handleFiles(files: FileList) {
    for (const file of Array.from(files)) {
      const key = crypto.randomUUID();
      setLive((prev) => [
        { key, id: key, filename: file.name, doc_kind: docKind, stage: "QUEUED", progress_pct: 5 },
        ...prev,
      ]);
      try {
        await uploadArchive(file, { fileId: fileId || null, docKind }, (stage, pct, msg) =>
          patchLive(key, { stage, progress_pct: pct, message: msg })
        );
      } catch (err) {
        patchLive(key, { stage: "FAILED", progress_pct: 0, error: (err as Error).message });
      }
      qc.invalidateQueries({ queryKey: ["archives"] });
    }
    // Clear finished live rows shortly after; the persisted list takes over.
    setTimeout(() => setLive((prev) => prev.filter((u) => u.stage !== "DONE")), 2500);
  }

  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/archives/${id}/ingest`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["archives"] }),
  });

  // Live uploads sit above the persisted list (dedup by not showing DONE twice).
  const allDocs: IngestDoc[] = [...live.filter((u) => u.stage !== "DONE"), ...persisted];

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Archives</h2>
      <p className="mt-1 text-sm text-ink/60">
        Upload pleadings, contracts and notes, or client-conversation recordings (auto-transcribed,
        multilingual). Attach to a file so the content becomes per-case context for AI research.
        Everything is parsed, embedded and linked into your firm&rsquo;s private knowledge graph —
        isolated from every other firm.
      </p>

      <div className="mt-6 card flex flex-col gap-3 border-dashed sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="label">File (per-case)</label>
          <select className="input" value={fileId} onChange={(e) => setFileId(e.target.value)}>
            <option value="">Unassigned</option>
            {(filesData?.files || []).map((m: any) => (
              <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="label">Type</label>
          <select className="input" value={docKind} onChange={(e) => setDocKind(e.target.value)}>
            {DOC_KINDS.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}
          </select>
        </div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt,.md,audio/*,.mp3,.wav,.m4a,.ogg,.flac,.webm"
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
        <button className="btn-gold shrink-0" onClick={() => fileRef.current?.click()}>
          Upload files
        </button>
      </div>

      <div className="mt-6">
        <IngestionStatus archives={allDocs} onRetry={(id) => retry.mutate(id)} />
      </div>
    </div>
  );
}
