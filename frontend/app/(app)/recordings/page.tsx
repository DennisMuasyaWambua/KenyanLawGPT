"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type Recording = {
  id: string; file_id?: string | null; filename: string; status: string;
  duration_seconds: number; transcript_text: string; summary_text: string;
  error?: string; created_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  recording: "recording", uploading: "uploading", transcribing: "transcribing…",
  summarizing: "summarizing…", complete: "complete", failed: "failed",
};
const PENDING = ["uploading", "transcribing", "summarizing"];

export default function RecordingsPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const canCreate = can("recordings.create");
  const canAll = can("recordings.view_all");

  const [consent, setConsent] = useState(false);
  const [fileId, setFileId] = useState("");
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedRef = useRef<number>(0);

  const { data } = useQuery({
    queryKey: ["recordings"],
    queryFn: () => api(`/api/v1/recordings${canAll ? "?scope=all" : ""}`),
    refetchInterval: (q) => ((q.state.data?.recordings || []).some((r: Recording) => PENDING.includes(r.status)) ? 4000 : false),
  });
  const recordings: Recording[] = data?.recordings || [];
  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files"), enabled: canCreate });

  const finalize = useMutation({
    mutationFn: async (blob: Blob) => {
      const mime = blob.type || "audio/webm";
      const filename = `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`;
      // 1) create the row (consent gate) + get a presigned R2 URL
      const res = await api<{ recording: Recording; upload_url: string }>("/api/v1/recordings", {
        method: "POST",
        body: JSON.stringify({ file_id: fileId || undefined, filename, mime_type: mime, consent_confirmed: true }),
      });
      // 2) upload audio straight to R2
      const put = await fetch(res.upload_url, { method: "PUT", body: blob, headers: { "Content-Type": mime } });
      if (!put.ok) throw new Error(`upload failed (${put.status})`);
      // 3) hand off to the transcription worker
      const duration = Math.round((Date.now() - startedRef.current) / 1000);
      await api(`/api/v1/recordings/${res.recording.id}/uploaded`, { method: "POST", body: JSON.stringify({ duration_seconds: duration }) });
    },
    onSuccess: () => { setBusy(""); qc.invalidateQueries({ queryKey: ["recordings"] }); },
    onError: (e) => { setBusy(""); setError((e as Error).message); },
  });

  async function start() {
    setError("");
    if (!consent) { setError("Confirm client consent before recording."); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || "audio/webm" });
        setBusy("Uploading & transcribing…");
        finalize.mutate(blob);
      };
      startedRef.current = Date.now();
      mr.start();
      mediaRef.current = mr;
      setRecording(true);
    } catch (e) {
      setError("Microphone access denied or unavailable.");
    }
  }

  function stop() {
    mediaRef.current?.stop();
    setRecording(false);
  }

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Meeting recordings</h2>
      <p className="mt-1 text-sm text-ink/60">
        Audio is transcribed and summarized on-box (local Whisper + local LLM). Recordings never leave your infrastructure.
      </p>

      {canCreate && (
        <div className="card mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <select className="input" value={fileId} onChange={(e) => setFileId(e.target.value)} disabled={recording}>
              <option value="">No file linked</option>
              {(filesData?.files || []).map((m: any) => <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink/80">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} disabled={recording} />
            I confirm the client has consented to this meeting being recorded and transcribed.
          </label>
          <div className="flex items-center gap-3">
            {!recording ? (
              <button className="btn-gold" onClick={start} disabled={!consent || !!busy}>● Start recording</button>
            ) : (
              <button className="btn-primary !bg-red-700" onClick={stop}>■ Stop &amp; process</button>
            )}
            {recording && <span className="animate-pulse text-sm text-red-600">● recording…</span>}
            {busy && <span className="text-sm text-gold-dim">{busy}</span>}
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {recordings.length === 0 && <p className="card text-sm text-ink/60">No recordings yet.</p>}
        {recordings.map((r) => <RecordingCard key={r.id} r={r} />)}
      </div>
    </div>
  );
}

function RecordingCard({ r }: { r: Recording }) {
  const [open, setOpen] = useState(false);
  const badge = r.status === "complete" ? "bg-green-100 text-green-800"
    : r.status === "failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800";
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div>
          <span className="font-medium text-navy">{r.filename}</span>
          <span className="ml-2 text-xs text-ink/50">{fmtDate(r.created_at)} · {r.duration_seconds}s</span>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${badge}`}>{STATUS_LABEL[r.status] || r.status}</span>
      </div>
      {r.status === "failed" && r.error && <p className="mt-2 text-xs text-red-600">{r.error}</p>}
      {r.status === "complete" && (
        <>
          <button className="mt-2 text-xs text-navy hover:underline" onClick={() => setOpen(!open)}>
            {open ? "Hide" : "Show"} transcript &amp; summary
          </button>
          {open && (
            <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">Summary</p>
                <pre className="whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink">{r.summary_text || "—"}</pre>
              </div>
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">Transcript</p>
                <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink/80">{r.transcript_text || "—"}</pre>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
