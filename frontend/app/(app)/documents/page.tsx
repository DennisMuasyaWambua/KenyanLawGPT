"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import IngestionStatus, { IngestDoc } from "@/components/IngestionStatus";

// Firm document ingestion status. Polls the gateway for per-document ingestion
// state (backed by the async queue's status store). Degrades to a small sample
// set if the documents endpoint isn't wired yet, so the surface is reviewable.
const SAMPLE: IngestDoc[] = [
  { id: "s1", filename: "Replying_Submissions_ELC_123_of_2019.pdf", doc_kind: "submission",
    stage: "DONE", progress_pct: 100, message: "ingested 14 chunk(s) [submission]" },
  { id: "s2", filename: "Ruling_HCCC_45_of_2018.pdf", doc_kind: "ruling",
    stage: "EMBEDDING", progress_pct: 60, message: "embedding 9 chunk(s)" },
  { id: "s3", filename: "Lease_Agreement_Kilimani.docx", doc_kind: "contract",
    stage: "FAILED", progress_pct: 0, error: "document contains no extractable text" },
];

export default function DocumentsPage() {
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);

  const { data: documents = [] } = useQuery<IngestDoc[]>({
    queryKey: ["documents"],
    queryFn: async () => {
      try {
        const r = await api<{ documents: IngestDoc[] }>("/api/v1/documents");
        return r.documents || [];
      } catch {
        return SAMPLE; // endpoint not available yet — show the surface
      }
    },
    // Poll while anything is still in flight so the steps animate live.
    refetchInterval: (q) =>
      (q.state.data || []).some((d) => d.stage !== "DONE" && d.stage !== "FAILED") ? 3000 : false,
  });

  const upload = useMutation({
    mutationFn: async (files: FileList) => {
      setUploading(true);
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        // Content-Type is set by the browser for multipart; api() adds auth+tenant.
        await api("/api/v1/documents", { method: "POST", body: form, headers: {} as any });
      }
    },
    onSettled: () => {
      setUploading(false);
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}/reingest`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Documents</h2>
      <p className="mt-1 text-sm text-ink/60">
        Upload and track ingestion of your firm&rsquo;s pleadings, submissions and notes. Each
        document is parsed, embedded and linked into your firm&rsquo;s private knowledge graph —
        strictly isolated from every other firm on the platform.
      </p>

      <div className="mt-6">
        <IngestionStatus
          documents={documents}
          uploading={uploading || upload.isPending}
          onUpload={(files) => upload.mutate(files)}
          onRetry={(id) => retry.mutate(id)}
        />
      </div>
      {upload.isError && (
        <p className="mt-3 text-sm text-red-600">{(upload.error as Error).message}</p>
      )}
    </div>
  );
}
