"use client";

// Citation card with provenance: the UI must always show whether a source is
// public Kenyan law or the firm's own confidential material.
export type Chunk = {
  chunk_id: string;
  text: string;
  score: number;
  provenance: {
    source_type: string; // SOURCE_TYPE_PUBLIC | SOURCE_TYPE_TENANT_PRIVATE
    source_id: string;
    citation: string;
    source_url: string;
    status: string;
    court: string;
    year: number;
  } | null;
};

export default function CitationCard({ chunk, index }: { chunk: Chunk; index: number }) {
  const p = chunk.provenance;
  const isPublic = p?.source_type === "SOURCE_TYPE_PUBLIC";
  const stale = p && p.status !== "DOC_STATUS_CURRENT" && p.status !== "DOC_STATUS_UNSPECIFIED";
  return (
    <div className="card !p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-bold text-navy/40">[{index}]</span>
        <span className={isPublic ? "badge-public" : "badge-private"}>
          {isPublic ? "Public law" : "Firm confidential"}
        </span>
        {stale && (
          <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold uppercase text-red-700">
            {p!.status.replace("DOC_STATUS_", "")}
          </span>
        )}
        <span className="ml-auto text-[10px] text-ink/40">score {chunk.score.toFixed(2)}</span>
      </div>
      <p className="text-sm font-semibold text-navy">{p?.citation || p?.source_id}</p>
      {p?.court && (
        <p className="text-xs text-ink/50">
          {p.court}
          {p.year ? ` · ${p.year}` : ""}
        </p>
      )}
      <p className="mt-2 line-clamp-4 whitespace-pre-line text-xs text-ink/70">{chunk.text}</p>
      {p?.source_url && isPublic && (
        <a href={p.source_url} target="_blank" rel="noreferrer"
          className="mt-2 inline-block text-xs text-gold-dim hover:underline">
          source ↗
        </a>
      )}
    </div>
  );
}
