"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRecorder } from "@/lib/recorder";

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

/** Floating status for a meeting recording while the user is elsewhere in the
 *  app: stop it from any page, and see when the transcript and notes are ready.
 *  The recordings page shows all of this itself, so the dock stays out of the way there. */
export default function RecorderDock() {
  const rec = useRecorder();
  const pathname = usePathname();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!rec.recording) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [rec.recording]);

  if (pathname.startsWith("/recordings")) return null;
  const uploading = !!rec.busy || rec.sending.length > 0;
  const problem = rec.sessionExpired ? "Session expired — the recording is saved on this device." : rec.error;
  // Still on this device and not uploading right now (e.g. an upload failed).
  const waiting = rec.localRecs.filter((r) => r.id !== rec.currentId && !rec.sending.includes(r.id)).length;
  if (!rec.recording && !uploading && !problem && !rec.notice && !waiting && rec.processing.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-72 space-y-2 rounded-lg border border-navy/10 bg-white p-3 text-xs shadow-xl">
      {rec.recording && (
        <div className="flex items-center gap-2">
          <span className="animate-pulse text-red-600">●</span>
          <span className="font-semibold text-navy">Recording {rec.startedAt ? clock(now - rec.startedAt) : ""}</span>
          <span className="h-1.5 w-10 overflow-hidden rounded bg-navy/10" title="Microphone input level">
            <span className="block h-full bg-green-600" style={{ width: `${Math.round(rec.level * 100)}%` }} />
          </span>
          <button className="ml-auto rounded bg-red-700 px-2 py-1 font-semibold text-white" onClick={rec.stop}>
            ■ Stop
          </button>
        </div>
      )}
      {rec.recording && rec.screenAwake === false && (
        <p className="text-amber-700">
          This browser can&apos;t keep the screen on. Don&apos;t let the phone lock — the microphone stops when it does.
        </p>
      )}
      {rec.notice && (
        <p className="text-amber-700">
          {rec.notice}
          <button className="ml-2 text-ink/50" aria-label="Dismiss" onClick={rec.clearMessages}>✕</button>
        </p>
      )}
      {rec.interrupted && !rec.recording && (
        <button className="w-full rounded bg-red-700 px-2 py-1.5 font-semibold text-white" onClick={() => void rec.resume()}>
          ● Continue recording
        </button>
      )}
      {uploading && <p className="text-gold-dim">Uploading recording…</p>}
      {!uploading && waiting > 0 && (
        <p className="text-ink/70">
          {waiting === 1 ? "A recording is" : `${waiting} recordings are`} saved on this device, not uploaded yet.{" "}
          <Link className="font-semibold underline" href="/recordings">Upload</Link>
        </p>
      )}
      {problem && (
        <p className="text-red-600">
          {problem}{" "}
          <Link className="font-semibold underline" href="/recordings">Open recordings</Link>
          <button className="ml-2 text-ink/50" aria-label="Dismiss" onClick={rec.clearMessages}>✕</button>
        </p>
      )}
      {rec.processing.map((p) => (
        <div key={p.id} className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-ink/70" title={p.filename}>{p.filename}</span>
          {p.status === "complete" ? (
            <Link className="font-semibold text-green-700 hover:underline" href="/recordings"
              onClick={() => rec.dismissProcessing(p.id)}>Notes ready →</Link>
          ) : p.status === "failed" ? (
            <Link className="font-semibold text-red-600 hover:underline" href="/recordings"
              onClick={() => rec.dismissProcessing(p.id)}>Failed — view</Link>
          ) : (
            <span className="text-amber-700">{p.status === "summarizing" ? "writing notes…" : "transcribing…"}</span>
          )}
          <button className="text-ink/40" aria-label="Dismiss" onClick={() => rec.dismissProcessing(p.id)}>✕</button>
        </div>
      ))}
    </div>
  );
}
