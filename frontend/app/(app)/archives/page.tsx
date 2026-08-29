"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, uploadArchive, fmtDate } from "@/lib/api";
import IngestionStatus, { IngestDoc } from "@/components/IngestionStatus";

const DOC_KINDS = [
  "other", "statute", "authority", "research",
  "contract", "pleading", "correspondence", "evidence", "precedent_note",
];

// Archive sections. The three doc-kind sections filter uploaded archives by
// doc_kind; "Closed files" lists files whose matter has been closed.
const SECTIONS: { key: string; label: string; kind: string | null }[] = [
  { key: "all", label: "All", kind: null },
  { key: "statute", label: "Statutes", kind: "statute" },
  { key: "research", label: "Researches", kind: "research" },
  { key: "authority", label: "Authorities", kind: "authority" },
  { key: "closed", label: "Closed files", kind: null },
];

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
  const [docKind, setDocKind] = useState("statute");
  const [live, setLive] = useState<LiveUpload[]>([]);
  const [section, setSection] = useState("all");
  const [openDoc, setOpenDoc] = useState<IngestDoc | null>(null);

  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files") });

  const { data: persisted = [] } = useQuery<IngestDoc[]>({
    queryKey: ["archives"],
    queryFn: async () => {
      const r = await api<{ archives: any[] }>(`/api/v1/archives`);
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
    setTimeout(() => setLive((prev) => prev.filter((u) => u.stage !== "DONE")), 2500);
  }

  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/archives/${id}/ingest`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["archives"] }),
  });

  function selectSection(key: string) {
    setSection(key);
    const s = SECTIONS.find((x) => x.key === key);
    if (s?.kind) setDocKind(s.kind);
  }

  const activeSection = SECTIONS.find((s) => s.key === section)!;
  const allDocs: IngestDoc[] = [...live.filter((u) => u.stage !== "DONE"), ...persisted];
  const shownDocs = activeSection.kind ? allDocs.filter((d) => d.doc_kind === activeSection.kind) : allDocs;
  const closedFiles = (filesData?.files || []).filter((f: any) => f.status === "closed");

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Archives</h2>
      <p className="mt-1 text-sm text-ink/60">
        Organise firm knowledge into statutes, researches and authorities, and review closed files.
        Uploaded documents are parsed, embedded and linked into your firm&rsquo;s private knowledge
        graph — isolated from every other firm.
      </p>

      {/* Section tabs */}
      <div className="mt-4 flex flex-wrap gap-2">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => selectSection(s.key)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              section === s.key ? "bg-navy text-white" : "bg-white text-navy border border-navy/20 hover:border-gold"
            }`}
          >
            {s.label}
            {s.key === "closed" && closedFiles.length > 0 && (
              <span className="ml-1 text-xs opacity-70">({closedFiles.length})</span>
            )}
          </button>
        ))}
      </div>

      {section === "closed" ? (
        <div className="mt-6 card overflow-x-auto !p-0">
          <table className="w-full text-sm">
            <thead className="bg-navy/5 text-left text-xs uppercase tracking-wide text-navy/60">
              <tr>
                <th className="p-3">Reference</th><th className="p-3">Title</th>
                <th className="p-3">Court</th><th className="p-3">Closed</th>
              </tr>
            </thead>
            <tbody>
              {closedFiles.map((f: any) => (
                <tr key={f.id} className="border-t border-navy/5">
                  <td className="p-3 font-medium">{f.reference}</td>
                  <td className="p-3">{f.title}</td>
                  <td className="p-3">{f.court || "—"}</td>
                  <td className="p-3">{f.closed_at ? fmtDate(f.closed_at) : "—"}</td>
                </tr>
              ))}
              {closedFiles.length === 0 && (
                <tr><td colSpan={4} className="p-6 text-center text-ink/50">No closed files yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="mt-6 card flex flex-col gap-3 border-dashed sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="label">File (per-case, optional)</label>
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
            {shownDocs.length === 0 ? (
              <p className="text-sm text-ink/50">
                No {activeSection.key === "all" ? "documents" : activeSection.label.toLowerCase()} yet — upload a
                document{activeSection.kind ? ` and set its type to “${activeSection.kind}”` : ""}.
              </p>
            ) : (
              <IngestionStatus archives={shownDocs} onRetry={(id) => retry.mutate(id)} onOpen={setOpenDoc} />
            )}
          </div>
        </>
      )}

      {openDoc && <DocumentDrawer doc={openDoc} onClose={() => setOpenDoc(null)} />}
    </div>
  );
}

function DocumentDrawer({ doc, onClose }: { doc: IngestDoc; onClose: () => void }) {
  const qc = useQueryClient();
  const verRef = useRef<HTMLInputElement>(null);
  const [body, setBody] = useState("");
  const [uploading, setUploading] = useState(false);
  const [restricted, setRestricted] = useState(false);
  const [shared, setShared] = useState<string[]>([]);

  const { data: verData } = useQuery({ queryKey: ["archive-versions", doc.id], queryFn: () => api(`/api/v1/archives/${doc.id}/versions`) });
  const versions = verData?.versions || [];
  const { data: shareData } = useQuery({ queryKey: ["archive-shares", doc.id], queryFn: () => api(`/api/v1/archives/${doc.id}/shares`) });
  const { data: comData } = useQuery({ queryKey: ["archive-comments", doc.id], queryFn: () => api(`/api/v1/archives/${doc.id}/comments`) });
  const comments = comData?.comments || [];
  const users = (shareData?.users || []).filter((u: any) => u.role !== "client");

  useEffect(() => {
    if (shareData) { setRestricted(!!shareData.restricted); setShared(shareData.shared_user_ids || []); }
  }, [shareData]);

  const addComment = useMutation({
    mutationFn: () => api(`/api/v1/archives/${doc.id}/comments`, { method: "POST", body: JSON.stringify({ body }) }),
    onSuccess: () => { setBody(""); qc.invalidateQueries({ queryKey: ["archive-comments", doc.id] }); },
  });
  const saveShares = useMutation({
    mutationFn: () => api(`/api/v1/archives/${doc.id}/shares`, { method: "PUT", body: JSON.stringify({ restricted, user_ids: restricted ? shared : [] }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["archive-shares", doc.id] }); qc.invalidateQueries({ queryKey: ["archives"] }); },
  });

  async function newVersion(files: FileList) {
    if (!files[0]) return;
    setUploading(true);
    try {
      await uploadArchive(files[0], { replacesId: doc.id });
      qc.invalidateQueries({ queryKey: ["archives"] });
      onClose();
    } finally { setUploading(false); }
  }

  const toggleShared = (id: string) =>
    setShared((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy/40" onClick={onClose}>
      <div className="flex h-full w-full max-w-md flex-col bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-navy/10 p-4">
          <div className="min-w-0">
            <h3 className="truncate font-display text-lg font-bold text-navy">{doc.filename}</h3>
            <p className="text-xs text-ink/50">Document collaboration</p>
          </div>
          <button onClick={onClose} className="shrink-0 text-lg text-ink/50 hover:text-navy">✕</button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-4">
          <section>
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wide text-navy/60">Version history</h4>
              <button onClick={() => verRef.current?.click()} disabled={uploading}
                className="text-xs font-semibold text-gold-dim hover:underline">{uploading ? "Uploading…" : "+ New version"}</button>
              <input ref={verRef} type="file" className="hidden"
                accept=".pdf,.docx,.doc,.txt,.md,audio/*" onChange={(e) => e.target.files && newVersion(e.target.files)} />
            </div>
            <div className="mt-2 space-y-1">
              {versions.map((v: any, i: number) => (
                <div key={v.id} className="flex items-center justify-between rounded-md border border-navy/10 px-2 py-1 text-xs">
                  <span className="truncate">v{v.version} · {v.filename}</span>
                  <span className="text-ink/40">{i === 0 ? "current" : fmtDate(v.created_at)}</span>
                </div>
              ))}
              {versions.length <= 1 && <p className="text-xs text-ink/40">One version. Upload a new version to keep history.</p>}
            </div>
          </section>

          <section>
            <h4 className="text-xs font-bold uppercase tracking-wide text-navy/60">Access</h4>
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={restricted} onChange={(e) => setRestricted(e.target.checked)} />
              Restrict this document to specific people
            </label>
            {restricted && (
              <div className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded-md border border-navy/10 p-2">
                {users.length === 0 && <p className="text-xs text-ink/40">No other members to share with.</p>}
                {users.map((u: any) => (
                  <label key={u.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={shared.includes(u.id)} onChange={() => toggleShared(u.id)} />
                    <span className="truncate">{u.full_name || u.email}</span>
                    <span className="ml-auto text-[11px] text-ink/40">{u.role}</span>
                  </label>
                ))}
              </div>
            )}
            <button onClick={() => saveShares.mutate()} disabled={saveShares.isPending}
              className="mt-2 rounded-md border border-navy/20 px-3 py-1 text-xs font-semibold text-navy transition hover:border-gold hover:text-gold-dim">
              {saveShares.isPending ? "Saving…" : "Save access"}
            </button>
            <p className="mt-1 text-[11px] text-ink/40">Restricted documents are visible only to the uploader, the people you pick, and the Managing Partner.</p>
          </section>

          <section>
            <h4 className="text-xs font-bold uppercase tracking-wide text-navy/60">Discussion</h4>
            <div className="mt-2 space-y-2">
              {comments.length === 0 && <p className="text-sm text-ink/50">No comments yet — start the discussion.</p>}
              {comments.map((c: any) => (
                <div key={c.id} className="rounded-md border border-navy/10 bg-navy/5 p-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-navy">{c.author_name || "Someone"}</span>
                    <span className="text-ink/40">{fmtDate(c.created_at)}</span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-ink/80">{c.body}</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <form className="border-t border-navy/10 p-3"
          onSubmit={(e) => { e.preventDefault(); if (body.trim()) addComment.mutate(); }}>
          <textarea className="input" rows={2} placeholder="Add a comment…" value={body}
            onChange={(e) => setBody(e.target.value)} />
          <button className="btn-gold mt-2 w-full" disabled={!body.trim() || addComment.isPending}>
            {addComment.isPending ? "Posting…" : "Post comment"}
          </button>
        </form>
      </div>
    </div>
  );
}
