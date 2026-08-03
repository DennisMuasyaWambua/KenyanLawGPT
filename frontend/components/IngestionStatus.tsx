"use client";

// Document upload + ingestion-status view (Task 7). Design reference:
// Perplexity's file-upload/processing rows (gummble
// sc_5cc4b39f195847b9ad3bd48aa1346060, sc_9c2d6b14389848b992ddc2057266c5fb)
// and the notifications/status pattern family — a list where each document
// advances through explicit processing steps with a progress bar and terminal
// success/failure states. Mirrors the backend async pipeline stages
// (QUEUED → FETCHING → PARSING → CHUNKING → EMBEDDING → GRAPHING → DONE).

import { useRef } from "react";

export type IngestDoc = {
  id: string;
  filename: string;
  doc_kind?: string;
  stage: string; // QUEUED|FETCHING|PARSING|CHUNKING|EMBEDDING|GRAPHING|DONE|FAILED
  progress_pct: number;
  message?: string;
  error?: string;
};

const STEPS = ["QUEUED", "FETCHING", "PARSING", "CHUNKING", "EMBEDDING", "GRAPHING", "DONE"];
const STEP_LABEL: Record<string, string> = {
  QUEUED: "Queued",
  FETCHING: "Fetching",
  PARSING: "Parsing",
  CHUNKING: "Chunking",
  EMBEDDING: "Embedding",
  GRAPHING: "Graphing",
  DONE: "Done",
};

function StatusRow({ doc, onRetry }: { doc: IngestDoc; onRetry?: (id: string) => void }) {
  const failed = doc.stage === "FAILED";
  const done = doc.stage === "DONE";
  const activeIdx = Math.max(0, STEPS.indexOf(doc.stage));

  return (
    <div className="card !p-4">
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-semibold text-navy">{doc.filename}</span>
        {doc.doc_kind && (
          <span className="badge-private capitalize">{doc.doc_kind.replace(/_/g, " ")}</span>
        )}
        <span
          className={`ml-auto text-xs font-semibold ${
            failed ? "text-red-600" : done ? "text-green-600" : "text-ink/50"
          }`}
        >
          {failed ? "Failed" : done ? "✓ Ingested" : `${doc.progress_pct}%`}
        </span>
      </div>

      {!failed && (
        <>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-navy/10">
            <div
              className={`h-full rounded-full transition-all ${done ? "bg-green-500" : "bg-gold"}`}
              style={{ width: `${done ? 100 : doc.progress_pct}%` }}
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {STEPS.map((s, i) => (
              <span
                key={s}
                className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  i < activeIdx || done
                    ? "bg-navy/10 text-navy/50"
                    : i === activeIdx
                    ? "bg-gold/20 text-gold-dim"
                    : "bg-navy/5 text-ink/30"
                }`}
              >
                {STEP_LABEL[s]}
              </span>
            ))}
          </div>
        </>
      )}

      {failed && (
        <div className="mt-2 flex items-center gap-2">
          <p className="text-xs text-red-600">{doc.error || "Ingestion failed."}</p>
          {onRetry && (
            <button onClick={() => onRetry(doc.id)} className="ml-auto text-xs font-semibold text-navy hover:underline">
              Retry
            </button>
          )}
        </div>
      )}
      {!failed && doc.message && <p className="mt-2 text-xs text-ink/50">{doc.message}</p>}
    </div>
  );
}

export default function IngestionStatus({
  documents,
  onUpload,
  onRetry,
  uploading,
}: {
  documents: IngestDoc[];
  onUpload?: (files: FileList) => void;
  onRetry?: (id: string) => void;
  uploading?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-4">
      {onUpload && (
        <div className="card flex items-center gap-4 border-dashed">
          <div>
            <p className="text-sm font-semibold text-navy">Upload firm documents</p>
            <p className="text-xs text-ink/50">
              Pleadings, submissions, contracts or internal notes (PDF/DOCX/TXT). Ingested privately
              into your firm&rsquo;s partition — never shared with other firms.
            </p>
          </div>
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => e.target.files && onUpload(e.target.files)}
          />
          <button
            className="btn-gold ml-auto shrink-0"
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
          >
            {uploading ? "Uploading…" : "Choose files"}
          </button>
        </div>
      )}

      {documents.length === 0 ? (
        <div className="card text-center text-sm text-ink/50">
          No documents yet. Upload a pleading or submission to build your firm&rsquo;s private
          knowledge graph.
        </div>
      ) : (
        documents.map((d) => <StatusRow key={d.id} doc={d} onRetry={onRetry} />)
      )}
    </div>
  );
}
