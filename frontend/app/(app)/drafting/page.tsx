"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, streamDraft } from "@/lib/api";

const DOC_TYPES = [
  { value: "pleading", label: "Pleading (Statement of Claim)" },
  { value: "affidavit", label: "Affidavit" },
  { value: "demand_letter", label: "Demand letter" },
  { value: "contract", label: "Contract / Agreement" },
  { value: "correspondence", label: "Correspondence" },
];

export default function DraftingPage() {
  const [docType, setDocType] = useState("demand_letter");
  const [matterId, setMatterId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [contextQuery, setContextQuery] = useState("");
  const [output, setOutput] = useState("");
  const [citations, setCitations] = useState<any[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const outRef = useRef<HTMLPreElement>(null);

  const { data: mattersData } = useQuery({ queryKey: ["matters", ""], queryFn: () => api("/api/v1/matters") });

  async function start() {
    setOutput(""); setCitations([]); setError(""); setStreaming(true);
    await streamDraft(
      { doc_type: docType, instructions, matter_id: matterId || undefined, context_query: contextQuery || undefined },
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
            <label className="label">Matter (grounds parties &amp; facts)</label>
            <select className="input" value={matterId} onChange={(e) => setMatterId(e.target.value)}>
              <option value="">— none —</option>
              {(mattersData?.matters || []).map((m: any) => (
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
        <div className="card h-full !bg-white">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-navy/60">
            Draft {streaming && <span className="text-gold-dim">· streaming…</span>}
          </p>
          <pre ref={outRef}
            className="h-[calc(100%-2rem)] overflow-y-auto whitespace-pre-wrap font-display text-sm leading-relaxed text-ink">
            {output || "The draft will stream here token by token."}
          </pre>
        </div>
      </div>
    </div>
  );
}
