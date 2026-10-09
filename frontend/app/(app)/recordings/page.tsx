"use client";

import { useEffect, useRef, useState } from "react";
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
// "recording" is included: a row whose upload confirmation was lost is recovered
// server-side after a couple of minutes and must show up without a manual reload.
const PENDING = ["recording", "uploading", "transcribing", "summarizing"];

// MediaRecorder container support differs by browser (Chrome/Firefox: webm/ogg,
// Safari: mp4). Pick one the browser can actually produce.
const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
function pickMime(): string {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}
function extFor(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

type ActionItem = { assignee?: string; task_description?: string; deadline?: string | null };
type Insights = {
  executive_summary?: string;
  key_discussion_points?: string[];
  decisions_made?: string[];
  action_items?: ActionItem[];
  open_questions?: string[];
};

// The AI worker stores the summary as a structured-JSON object. Parse it so the
// UI can render sections; fall back to raw text if it isn't the expected shape.
function parseInsights(s: string): Insights | null {
  if (!s) return null;
  try {
    const o = JSON.parse(s);
    if (o && typeof o === "object" && !Array.isArray(o) &&
        ("executive_summary" in o || "key_discussion_points" in o || "action_items" in o)) {
      return o as Insights;
    }
  } catch {
    /* not JSON — caller shows raw text */
  }
  return null;
}

function insightsToText(ins: Insights): string {
  const lines: string[] = [];
  if (ins.executive_summary) lines.push("EXECUTIVE SUMMARY", ins.executive_summary, "");
  const list = (title: string, items?: string[]) => {
    if (items && items.length) {
      lines.push(title, ...items.map((i) => `  • ${i}`), "");
    }
  };
  list("KEY DISCUSSION POINTS", ins.key_discussion_points);
  list("DECISIONS MADE", ins.decisions_made);
  if (ins.action_items && ins.action_items.length) {
    lines.push("ACTION ITEMS");
    for (const a of ins.action_items) {
      const who = a.assignee || "Unassigned";
      const dl = a.deadline ? ` (due ${a.deadline})` : "";
      lines.push(`  • [${who}] ${a.task_description || ""}${dl}`);
    }
    lines.push("");
  }
  list("OPEN QUESTIONS", ins.open_questions);
  return lines.join("\n").trim();
}

function buildNotesFile(r: Recording): string {
  const ins = parseInsights(r.summary_text);
  const summary = ins ? insightsToText(ins) : r.summary_text || "(no summary)";
  return [
    `Meeting notes — ${r.filename}`,
    `${fmtDate(r.created_at)} · ${r.duration_seconds}s`,
    "=".repeat(48),
    "",
    summary,
    "",
    "FULL TRANSCRIPT",
    "-".repeat(48),
    r.transcript_text || "(no transcript)",
  ].join("\n");
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
  const streamRef = useRef<MediaStream | null>(null);
  // Live input level: lets the user see the mic is actually picking up sound,
  // and lets us refuse to upload a recording that is pure silence.
  const [level, setLevel] = useState(0);
  const peakRef = useRef(0);
  const meterRef = useRef<{ ctx: AudioContext; raf: number } | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedRef = useRef<number>(0);

  const { data } = useQuery({
    queryKey: ["recordings"],
    queryFn: () => api(`/api/v1/recordings${canAll ? "?scope=all" : ""}`),
    refetchInterval: (q) => ((q.state.data?.recordings || []).some((r: Recording) => PENDING.includes(r.status)) ? 4000 : false),
  });
  const recordings: Recording[] = data?.recordings || [];
  // Release the microphone if the user navigates away mid-recording.
  function stopMeter() {
    const m = meterRef.current;
    if (m) { cancelAnimationFrame(m.raf); m.ctx.close().catch(() => {}); }
    meterRef.current = null;
    setLevel(0);
  }

  function startMeter(stream: MediaStream) {
    peakRef.current = 0;
    try {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const tick = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        const rms = Math.sqrt(sum / buf.length);
        peakRef.current = Math.max(peakRef.current, rms);
        setLevel(Math.min(1, rms * 8));
        meterRef.current!.raf = requestAnimationFrame(tick);
      };
      meterRef.current = { ctx, raf: requestAnimationFrame(tick) };
    } catch {
      peakRef.current = 1; // no Web Audio: don't block uploads on a meter we couldn't run
    }
  }

  useEffect(() => () => {
    stopMeter();
    const mr = mediaRef.current;
    if (mr && mr.state !== "inactive") { mr.onstop = null; mr.stop(); }
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);
  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files"), enabled: canCreate });

  const finalize = useMutation({
    mutationFn: async (blob: Blob) => {
      const mime = blob.type || "audio/webm";
      const filename = `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.${extFor(mime)}`;
      // 1) create the row (consent gate) + get a presigned R2 URL
      const res = await api<{ recording: Recording; upload_url: string }>("/api/v1/recordings", {
        method: "POST",
        body: JSON.stringify({ file_id: fileId || undefined, filename, mime_type: mime, consent_confirmed: true }),
      });
      // 2) upload audio straight to R2
      let put: Response;
      try {
        put = await fetch(res.upload_url, { method: "PUT", body: blob, headers: { "Content-Type": mime } });
      } catch {
        // fetch rejects (no status) on network/CORS/mixed-content failures.
        throw new Error("Could not reach file storage to upload the audio. Check your connection and try again.");
      }
      if (!put.ok) throw new Error(`upload failed (${put.status})`);
      // 3) hand off to the transcription worker
      const duration = Math.round((Date.now() - startedRef.current) / 1000);
      await api(`/api/v1/recordings/${res.recording.id}/uploaded`, { method: "POST", body: JSON.stringify({ duration_seconds: duration }) });
    },
    onSuccess: () => { setBusy(""); qc.invalidateQueries({ queryKey: ["recordings"] }); },
    onError: (e) => {
      setBusy("");
      setError((e as Error).message);
      qc.invalidateQueries({ queryKey: ["recordings"] });
    },
  });

  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/recordings/${id}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recordings"] }),
    onError: (e) => setError((e as Error).message),
  });

  async function start() {
    setError("");
    if (!consent) { setError("Confirm client consent before recording."); return; }
    try {
      if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
        setError("This browser cannot record audio (or the page is not served over HTTPS).");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMime();
      const mr = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      mr.onerror = () => setError("Recording failed — the microphone was interrupted.");
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        stopMeter();
        if (peakRef.current < 0.002) {
          setError("No sound was picked up by the microphone, so nothing was uploaded. Check that the right microphone is selected and unmuted, then try again.");
          return;
        }
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || mimeType || "audio/webm" });
        if (blob.size === 0) { setError("No audio was captured. Check your microphone and try again."); return; }
        setBusy("Uploading & transcribing…");
        finalize.mutate(blob);
      };
      startMeter(stream);
      startedRef.current = Date.now();
      // A timeslice flushes data periodically so a long meeting isn't held in one buffer.
      mr.start(5000);
      mediaRef.current = mr;
      setRecording(true);
    } catch (e) {
      const name = (e as DOMException)?.name;
      setError(name === "NotFoundError" ? "No microphone found."
        : name === "NotAllowedError" ? "Microphone access was denied — allow it in your browser settings."
        : "Microphone unavailable.");
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
            {recording && (
              <span className="flex items-center gap-2 text-xs text-ink/60" title="Microphone input level">
                mic
                <span className="h-2 w-24 overflow-hidden rounded bg-navy/10">
                  <span className="block h-full bg-green-600 transition-[width] duration-75" style={{ width: `${Math.round(level * 100)}%` }} />
                </span>
              </span>
            )}
            {busy && <span className="text-sm text-gold-dim">{busy}</span>}
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {recordings.length === 0 && <p className="card text-sm text-ink/60">No recordings yet.</p>}
        {recordings.map((r) => (
          <RecordingCard key={r.id} r={r} onRetry={() => retry.mutate(r.id)} retrying={retry.isPending && retry.variables === r.id} />
        ))}
      </div>
    </div>
  );
}

function RecordingCard({ r, onRetry, retrying }: { r: Recording; onRetry: () => void; retrying: boolean }) {
  const [open, setOpen] = useState(false);
  const insights = parseInsights(r.summary_text);
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
      {r.status === "failed" && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {r.error && <p className="text-xs text-red-600">{r.error}</p>}
          <button className="text-xs font-semibold text-navy hover:underline disabled:opacity-50" disabled={retrying} onClick={onRetry}>
            {retrying ? "Retrying…" : "↻ Retry"}
          </button>
        </div>
      )}
      {r.status === "complete" && r.error && <p className="mt-2 text-xs text-amber-700">Note: {r.error}</p>}
      {/* The transcript is saved before the (slower, local-LLM) summary runs, so
          show it right away instead of making the user wait for the notes. */}
      {r.status === "summarizing" && r.transcript_text && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">
            Transcript <span className="font-normal normal-case text-ink/50">· notes are still being generated…</span>
          </p>
          <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink/80">{r.transcript_text}</pre>
        </div>
      )}
      {r.status === "complete" && (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button className="text-xs text-navy hover:underline" onClick={() => setOpen(!open)}>
              {open ? "Hide" : "Show"} transcript &amp; notes
            </button>
            <button
              className="text-xs text-navy hover:underline"
              onClick={() => downloadText(`${r.filename.replace(/\.[^.]+$/, "")}-notes.txt`, buildNotesFile(r))}
            >
              ⬇ Download
            </button>
            <ShareViaEmail id={r.id} />
          </div>
          {open && (
            <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">Notes</p>
                {insights ? (
                  <InsightsView ins={insights} />
                ) : (
                  <pre className="whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink">{r.summary_text || "—"}</pre>
                )}
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

function InsightsView({ ins }: { ins: Insights }) {
  const Section = ({ title, items }: { title: string; items?: string[] }) =>
    items && items.length ? (
      <div>
        <p className="text-[11px] font-bold uppercase tracking-wide text-navy/50">{title}</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-ink/80">
          {items.map((it, i) => (
            <li key={i}>{it}</li>
          ))}
        </ul>
      </div>
    ) : null;
  return (
    <div className="space-y-3 rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink">
      {ins.executive_summary && <p>{ins.executive_summary}</p>}
      <Section title="Key discussion points" items={ins.key_discussion_points} />
      <Section title="Decisions made" items={ins.decisions_made} />
      {ins.action_items && ins.action_items.length > 0 && (
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wide text-navy/50">Action items</p>
          <ul className="mt-1 space-y-1 text-xs text-ink/80">
            {ins.action_items.map((a, i) => (
              <li key={i}>
                <span className="font-semibold text-navy">{a.assignee || "Unassigned"}</span>
                {a.deadline ? <span className="text-ink/50"> · due {a.deadline}</span> : null}
                <br />
                {a.task_description}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Section title="Open questions" items={ins.open_questions} />
    </div>
  );
}

function ShareViaEmail({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const share = useMutation({
    mutationFn: () => api(`/api/v1/recordings/${id}/share`, { method: "POST", body: JSON.stringify({ email }) }),
  });
  if (!open) {
    return (
      <button className="text-xs text-navy hover:underline" onClick={() => setOpen(true)}>
        ✉ Share via email
      </button>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <input
        type="email"
        className="input !w-56 !py-1 text-xs"
        placeholder="name@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button
        className="btn-primary !py-1 text-xs"
        disabled={!email || share.isPending}
        onClick={() => share.mutate()}
      >
        {share.isPending ? "Sending…" : "Send"}
      </button>
      {share.isSuccess && <span className="text-xs text-green-700">Sent ✓</span>}
      {share.isError && <span className="text-xs text-red-600">{(share.error as Error).message || "Failed"}</span>}
    </span>
  );
}
