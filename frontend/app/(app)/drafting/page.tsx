"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, streamDraft } from "@/lib/api";
import { downloadDocx, exportToGoogleDocs, googleDocsConfigured } from "@/lib/export";

const DOC_TYPES = [
  { value: "pleading", label: "Pleading (Statement of Claim)" },
  { value: "affidavit", label: "Affidavit" },
  { value: "demand_letter", label: "Demand letter" },
  { value: "contract", label: "Contract / Agreement" },
  { value: "correspondence", label: "Correspondence" },
];

export default function DraftingPage() {
  const [docType, setDocType] = useState("demand_letter");
  const [fileId, setFileId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [contextQuery, setContextQuery] = useState("");
  const [output, setOutput] = useState("");
  const [citations, setCitations] = useState<any[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState<"" | "docx" | "gdoc">("");
  const [exportError, setExportError] = useState("");
  const outRef = useRef<HTMLPreElement>(null);

  // A stable, human-readable name for the exported file / Google Doc.
  function exportName(): string {
    const label = DOC_TYPES.find((d) => d.value === docType)?.value || "draft";
    const stamp = new Date().toISOString().slice(0, 10);
    return `${label}-${stamp}`;
  }

  async function onDownloadDocx() {
    setExportError(""); setExporting("docx");
    try {
      await downloadDocx(output, exportName());
    } catch (e: any) {
      setExportError(e?.message || "Could not build the .docx");
    } finally {
      setExporting("");
    }
  }

  async function onExportGoogleDocs() {
    setExportError(""); setExporting("gdoc");
    try {
      const url = await exportToGoogleDocs(output, exportName());
      window.open(url, "_blank", "noopener");
    } catch (e: any) {
      setExportError(e?.message || "Could not export to Google Docs");
    } finally {
      setExporting("");
    }
  }

  const { data: filesData } = useQuery({ queryKey: ["files", ""], queryFn: () => api("/api/v1/files") });

  async function start() {
    setOutput(""); setCitations([]); setError(""); setStreaming(true);
    await streamDraft(
      { doc_type: docType, instructions, file_id: fileId || undefined, context_query: contextQuery || undefined },
      (t) => {
        setOutput((o) => o + t);
        outRef.current?.scrollTo({ top: outRef.current.scrollHeight });
      },
      (done) => { setCitations(done.citations || []); setStreaming(false); },
      (msg) => { setError(msg); setStreaming(false); }
    );
  }

  return (
    <div className="grid h-[calc(100vh-6rem)] grid-cols-1 gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2">
        <h2 className="font-display text-3xl font-bold text-navy">Drafting</h2>
        <div className="card mt-4 space-y-3">
          <div>
            <label className="label">Document type</label>
            <select className="input" value={docType} onChange={(e) => setDocType(e.target.value)}>
              {DOC_TYPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label">File (grounds parties &amp; facts)</label>
            <select className="input" value={fileId} onChange={(e) => setFileId(e.target.value)}>
              <option value="">— none —</option>
              {(filesData?.files || []).map((m: any) => (
                <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Instructions</label>
            <textarea className="input" rows={5} value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Demand letter to the employer for unpaid terminal dues following unfair termination; 14 days to comply…" />
          </div>
          <div>
            <label className="label">Legal grounding query (optional)</label>
            <input className="input" value={contextQuery} onChange={(e) => setContextQuery(e.target.value)}
              placeholder="unfair termination remedies Employment Act" />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button className="btn-gold w-full" onClick={start} disabled={streaming || !instructions.trim()}>
            {streaming ? "Drafting (streaming)…" : "Generate draft"}
          </button>
        </div>
        {citations.length > 0 && (
          <div className="card mt-4">
            <p className="mb-2 text-xs font-bold uppercase tracking-wide text-navy/60">Grounded on</p>
            {citations.map((c, i) => (
              <p key={i} className="text-xs">
                <span className={c.source_type === "SOURCE_TYPE_PUBLIC" ? "badge-public" : "badge-private"}>
                  {c.source_type === "SOURCE_TYPE_PUBLIC" ? "public" : "private"}
                </span>{" "}
                {c.citation || c.source_id}
              </p>
            ))}
          </div>
        )}
      </div>
      <div className="lg:col-span-3">
        <div className="card flex h-full flex-col !bg-white">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs font-bold uppercase tracking-wide text-navy/60">
              Draft {streaming && <span className="text-gold-dim">· streaming…</span>}
            </p>
            {output && !streaming && (
              <div className="flex items-center gap-2">
                <button className="btn-outline text-xs" onClick={onDownloadDocx}
                  disabled={!!exporting}>
                  {exporting === "docx" ? "Preparing…" : "Download .docx"}
                </button>
                {googleDocsConfigured() && (
                  <button className="btn-outline text-xs" onClick={onExportGoogleDocs}
                    disabled={!!exporting}>
                    {exporting === "gdoc" ? "Exporting…" : "Open in Google Docs"}
                  </button>
                )}
              </div>
            )}
          </div>
          {exportError && <p className="mb-2 text-xs text-red-600">{exportError}</p>}
          <pre ref={outRef}
            className="flex-1 overflow-y-auto whitespace-pre-wrap font-display text-sm leading-relaxed text-ink">
            {output || "The draft will stream here token by token."}
          </pre>
        </div>
      </div>
    </div>
  );
}
