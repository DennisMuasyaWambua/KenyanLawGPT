"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import CitationCard, { Chunk } from "@/components/CitationCard";

type Result = {
  answer: string;
  intent: string;
  chunks: Chunk[];
  steps?: { hop: number; description: string; edge_types: string[] }[];
};

export default function ResearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"query" | "reason">("query");
  const [includeSuperseded, setIncludeSuperseded] = useState(false);
  const [history, setHistory] = useState<{ q: string; r: Result }[]>([]);

  const ask = useMutation({
    mutationFn: async () => {
      const path = mode === "query" ? "/api/v1/research/query" : "/api/v1/research/reason";
      const r = await api<Result & { context?: Chunk[] }>(path, {
        method: "POST",
        body: JSON.stringify({ query, include_superseded: includeSuperseded, max_hops: 3 }),
      });
      return { ...r, chunks: r.chunks || r.context || [] };
    },
    onSuccess: (r) => {
      setHistory((h) => [{ q: query, r }, ...h]);
      setQuery("");
    },
  });

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">AI Legal Research</h2>
      <p className="mt-1 text-sm text-ink/60">
        Hybrid retrieval over Kenyan public law <span className="badge-public">Public law</span> and your
        firm's own documents <span className="badge-private">Firm confidential</span> — every citation is
        provenance-tagged.
      </p>

      <form
        className="card mt-6 space-y-3"
        onSubmit={(e) => { e.preventDefault(); if (query.trim()) ask.mutate(); }}
      >
        <textarea className="input" rows={3} value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "What must an employer prove for a termination to be fair under the Employment Act, and how have the courts applied it?"' />
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" checked={mode === "query"} onChange={() => setMode("query")} />
            Research answer
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" checked={mode === "reason"} onChange={() => setMode("reason")} />
            Graph reasoning (multi-hop)
          </label>
          <label className="ml-auto flex items-center gap-2 text-xs text-ink/60">
            <input type="checkbox" checked={includeSuperseded}
              onChange={(e) => setIncludeSuperseded(e.target.checked)} />
            include superseded/overturned law (historical)
          </label>
          <button className="btn-gold" disabled={ask.isPending}>
            {ask.isPending ? "Researching…" : "Ask"}
          </button>
        </div>
        {ask.isError && <p className="text-sm text-red-600">{(ask.error as Error).message}</p>}
      </form>

      <div className="mt-8 space-y-8">
        {history.map((item, i) => (
          <div key={i}>
            <p className="mb-2 text-sm font-semibold text-navy">Q: {item.q}</p>
            {item.r.intent && (
              <p className="mb-2 text-[10px] uppercase tracking-wide text-ink/40">
                intent: {item.r.intent.replace("QUERY_INTENT_", "").toLowerCase()}
              </p>
            )}
            {item.r.steps && item.r.steps.length > 0 && (
              <div className="card mb-3 !bg-navy !text-white">
                <p className="mb-2 text-xs font-bold uppercase tracking-wide text-gold">Reasoning trace</p>
                {item.r.steps.map((s) => (
                  <p key={s.hop} className="text-xs text-white/80">
                    <span className="text-gold">hop {s.hop}</span> — {s.description}
                  </p>
                ))}
              </div>
            )}
            <div className="card whitespace-pre-line text-sm leading-relaxed">{item.r.answer}</div>
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {item.r.chunks.map((c, j) => (
                <CitationCard key={c.chunk_id + j} chunk={c} index={j + 1} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
