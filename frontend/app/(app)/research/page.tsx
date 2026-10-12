"use client";

import { useState } from "react";
import { streamResearch } from "@/lib/api";
import { Chunk } from "@/components/CitationCard";
import CitationChain from "@/components/CitationChain";
import JudgeInsightPanel, { JudgePattern } from "@/components/JudgeInsightPanel";

type Result = {
  answer: string;
  intent: string;
  chunks: Chunk[];
  steps?: { hop: number; description: string; edge_types: string[] }[];
  // Present when ENABLE_JUDGE_REASONING and the query named a judge (the
  // gateway surfaces the JudgeReasoner pattern alongside the answer).
  judge_pattern?: JudgePattern;
};

type Item = { id: string; q: string; mode: "query" | "reason"; r: Result; status: "searching" | "writing" | "done"; error?: string };

export default function ResearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"query" | "reason">("query");
  const [includeSuperseded, setIncludeSuperseded] = useState(false);
  const [history, setHistory] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);

  // The answer is streamed: sources (or the reasoning trace) appear as soon as
  // retrieval finishes, then the answer fills in as the model writes it.
  async function ask() {
    const id = crypto.randomUUID();
    const q = query;
    const update = (f: (it: Item) => Item) => setHistory((h) => h.map((it) => (it.id === id ? f(it) : it)));
    setHistory((h) => [{ id, q, mode, r: { answer: "", intent: "", chunks: [] }, status: "searching" }, ...h]);
    setQuery("");
    setBusy(true);
    try {
      await streamResearch(mode, { query: q, include_superseded: includeSuperseded, max_hops: 3 }, {
        onStart: (p) => update((it) => ({
          ...it, status: "writing",
          r: { ...it.r, intent: p.intent || "", chunks: p.chunks || p.context || [], steps: p.steps },
        })),
        onText: (t) => update((it) => ({ ...it, status: "writing", r: { ...it.r, answer: it.r.answer + t } })),
      });
      update((it) => ({ ...it, status: "done" }));
    } catch (e) {
      update((it) => ({ ...it, status: "done", error: (e as Error).message }));
    } finally {
      setBusy(false);
    }
  }

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
        onSubmit={(e) => { e.preventDefault(); if (query.trim() && !busy) ask(); }}
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
          <button className="btn-gold" disabled={busy}>
            {busy ? "Researching…" : "Ask"}
          </button>
        </div>
      </form>

      <div className="mt-8 space-y-8">
        {history.map((item) => (
          <div key={item.id}>
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
            {item.r.judge_pattern && (
              <div className="mb-3">
                <JudgeInsightPanel pattern={item.r.judge_pattern} />
              </div>
            )}
            {item.status === "searching" ? (
              <div className="card animate-pulse text-sm text-ink/50">
                {item.mode === "reason" ? "Tracing authorities through the law graph…" : "Searching Kenyan law and your firm's documents…"}
              </div>
            ) : (
              (item.r.answer || item.status === "writing") && (
                <div className="card whitespace-pre-line text-sm leading-relaxed">
                  {item.r.answer}
                  {item.status === "writing" && (
                    <span className="ml-0.5 inline-block animate-pulse text-gold">{item.r.answer ? "▍" : "Writing the answer…"}</span>
                  )}
                </div>
              )
            )}
            {item.error && <p className="mt-2 text-sm text-red-600">{item.error}</p>}
            {item.r.chunks.length > 0 && (
              <div className="mt-3">
                <CitationChain chunks={item.r.chunks} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
