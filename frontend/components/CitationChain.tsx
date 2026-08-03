"use client";

// Citation-chain component (Task 7). Design reference: source-trail / cited-
// answer layouts (gummble Binance sc_defe853fe73f4a97ab98e05d4a5345c6, and the
// Perplexity/Sana search-source patterns) — an ordered, connected list showing
// the chain of sources behind an answer, each expandable, each provenance-
// tagged so public Kenyan law is never confused with the firm's own material.

import { useState } from "react";
import { Chunk } from "./CitationCard";

export default function CitationChain({ chunks }: { chunks: Chunk[] }) {
  const [open, setOpen] = useState<number | null>(0);
  if (!chunks.length) return null;

  return (
    <div className="card !p-4">
      <p className="label">Source chain</p>
      <ol className="relative ml-1 border-l border-navy/15">
        {chunks.map((c, i) => {
          const p = c.provenance;
          const isPublic = p?.source_type === "SOURCE_TYPE_PUBLIC";
          const stale =
            p && p.status !== "DOC_STATUS_CURRENT" && p.status !== "DOC_STATUS_UNSPECIFIED";
          const expanded = open === i;
          return (
            <li key={c.chunk_id + i} className="relative mb-3 pl-4 last:mb-0">
              <span className="absolute -left-[7px] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-navy" />
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : i)}
                className="flex w-full items-center gap-2 text-left"
              >
                <span className="text-xs font-bold text-navy/40">[{i + 1}]</span>
                <span className={isPublic ? "badge-public" : "badge-private"}>
                  {isPublic ? "Public law" : "Firm confidential"}
                </span>
                {stale && (
                  <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold uppercase text-red-700">
                    {p!.status.replace("DOC_STATUS_", "")}
                  </span>
                )}
                <span className="truncate text-sm font-semibold text-navy">
                  {p?.citation || p?.source_id}
                </span>
                <span className="ml-auto shrink-0 text-xs text-ink/30">{expanded ? "–" : "+"}</span>
              </button>
              {p?.court && (
                <p className="pl-6 text-xs text-ink/50">
                  {p.court}
                  {p.year ? ` · ${p.year}` : ""}
                </p>
              )}
              {expanded && (
                <p className="mt-1 whitespace-pre-line pl-6 text-xs leading-relaxed text-ink/70">
                  {c.text}
                </p>
              )}
              {expanded && p?.source_url && isPublic && (
                <a
                  href={p.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block pl-6 text-xs text-gold-dim hover:underline"
                >
                  source ↗
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
