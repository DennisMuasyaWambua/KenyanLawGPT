"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, currentUser, fmtDate, getTenant, holdSignOutRedirect, loginPath, SESSION_EXPIRED } from "@/lib/api";
import {
  appendChunk, deleteSession, listSessions, loadAudio, saveSession, updateSession, type LocalRecording,
} from "@/lib/recordingStore";
import { usePermissions } from "@/lib/usePermissions";

type Utterance = { speaker: number; start: number; end: number; text: string };
type Recording = {
  id: string; file_id?: string | null; filename: string; status: string;
  duration_seconds: number; transcript_text: string; summary_text: string;
  error?: string; created_at: string;
  num_speakers?: number;
  transcript_segments?: Utterance[] | null;
  speaker_names?: Record<string, string> | null;
  /** Speech-to-text output before the Kenyan-English AI correction ("" = none). */
  transcript_raw?: string;
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

type ActionItem = {
  assignee?: string; task_description?: string; deadline?: string | null;
  agreed_by?: string | string[] | null; source?: string | null;
};
type SpeakerInfo = { label?: string; role?: string | null; name?: string | null };
type Insights = {
  executive_summary?: string;
  speakers?: SpeakerInfo[];
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

// --- Speakers ---------------------------------------------------------------

const SPEAKER_COLORS = ["text-navy", "text-gold-dim", "text-emerald-700", "text-rose-700", "text-sky-700", "text-violet-700"];

/** Display name for speaker label n: the name the user set, else what the
 *  notes model inferred ("Speaker 1 · Advocate"), else "Speaker n". */
function speakerName(n: number, names: Record<string, string> | null | undefined, ins: Insights | null): string {
  const set = names?.[String(n)];
  if (set) return set;
  const guess = ins?.speakers?.find((sp) => sp.label?.trim().toLowerCase() === `speaker ${n}`);
  if (guess?.name) return guess.name;
  if (guess?.role && guess.role.toLowerCase() !== "unknown") return `Speaker ${n} · ${guess.role}`;
  return `Speaker ${n}`;
}

const clock = (t: number) => {
  const s = Math.floor(t), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

/** Utterances with display names, consecutive lines by the same name merged
 *  (so naming two labels identically merges a speaker the diarizer split). */
function namedTurns(r: Recording, ins: Insights | null) {
  const out: { who: string; speaker: number; start: number; text: string }[] = [];
  for (const u of r.transcript_segments || []) {
    const who = speakerName(u.speaker, r.speaker_names, ins);
    const last = out[out.length - 1];
    if (last && last.who === who) last.text += " " + u.text;
    else out.push({ who, speaker: u.speaker, start: u.start, text: u.text });
  }
  return out;
}

function transcriptAsText(r: Recording, ins: Insights | null): string {
  const turns = namedTurns(r, ins);
  if (!turns.length) return r.transcript_text || "";
  return turns.map((t) => `[${clock(t.start)}] ${t.who}: ${t.text}`).join("\n");
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
      if (a.source) lines.push(`      “${a.source}”`);
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
    transcriptAsText(r, ins) || "(no transcript)",
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
  // Knowing the head-count makes speaker labels far more accurate than guessing.
  const [numSpeakers, setNumSpeakers] = useState(2);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // Live input level: lets the user see the mic is actually picking up sound,
  // and lets us refuse to upload a recording that is pure silence.
  const [level, setLevel] = useState(0);
  const peakRef = useRef(0);
  const meterRef = useRef<{ ctx: AudioContext; raf: number } | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // The recording in progress, mirrored to IndexedDB chunk by chunk (see
  // lib/recordingStore) so it survives a lock screen, crash or lost session.
  const sessionRef = useRef<LocalRecording | null>(null);
  const writesRef = useRef<Promise<void>>(Promise.resolve());
  const persistedRef = useRef(true);
  const wakeRef = useRef<WakeLockSentinel | null>(null);
  const releaseHoldRef = useRef<(() => void) | null>(null);
  // Recordings saved on this device that haven't reached cloud storage yet.
  const [localRecs, setLocalRecs] = useState<LocalRecording[]>([]);
  const [sending, setSending] = useState<string[]>([]);
  // Last resort when the browser can't store audio locally and the upload failed.
  const [unsaved, setUnsaved] = useState<{ url: string; name: string } | null>(null);

  const { data } = useQuery({
    queryKey: ["recordings"],
    queryFn: () => api(`/api/v1/recordings${canAll ? "?scope=all" : ""}`),
    refetchInterval: (q) => ((q.state.data?.recordings || []).some((r: Recording) => PENDING.includes(r.status)) ? 4000 : false),
  });
  const recordings: Recording[] = data?.recordings || [];

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

  // Keep the screen on while recording: an auto-locking device can suspend the
  // microphone. The browser drops the lock whenever the page is hidden, so it is
  // re-taken each time the page comes back.
  async function keepAwake() {
    try {
      wakeRef.current = (await navigator.wakeLock?.request("screen")) ?? null;
    } catch {
      /* unsupported, or refused (e.g. battery saver) — recording carries on */
    }
  }
  function releaseWake() {
    wakeRef.current?.release().catch(() => {});
    wakeRef.current = null;
  }

  function releaseHold() {
    releaseHoldRef.current?.();
    releaseHoldRef.current = null;
  }

  async function refreshLocal() {
    try {
      setLocalRecs(await listSessions(getTenant(), currentUser()?.id || ""));
    } catch {
      /* IndexedDB unavailable: nothing to recover */
    }
  }

  /** Put a recording's audio in cloud storage and hand it to the transcription
   *  worker. Reuses the server row of an earlier, interrupted attempt. */
  async function upload(rec: LocalRecording, audio: Blob) {
    if (audio.size === 0) throw new Error("No audio was captured. Check your microphone and try again.");
    const mime = audio.type || rec.mimeType || "audio/webm";
    const duration = JSON.stringify({ duration_seconds: rec.durationSeconds });
    let id = rec.serverId;
    let url = "";
    if (id) {
      try {
        const r = await api<{ uploaded: boolean; status?: string; upload_url?: string }>(
          `/api/v1/recordings/${id}/upload-url`, { method: "POST" });
        if (r.uploaded) {
          // The audio got there last time; only the hand-off may be missing.
          if (r.status === "recording") await api(`/api/v1/recordings/${id}/uploaded`, { method: "POST", body: duration });
          return;
        }
        url = r.upload_url || "";
      } catch (e) {
        if ((e as Error).message === SESSION_EXPIRED) throw e;
        id = undefined; // that row can no longer take the audio: start a new one
      }
    }
    if (!id || !url) {
      const filename = `recording-${new Date(rec.startedAt).toISOString().replace(/[:.]/g, "-")}.${extFor(mime)}`;
      // Consent was confirmed before this recording could start.
      const res = await api<{ recording: Recording; upload_url: string }>("/api/v1/recordings", {
        method: "POST",
        body: JSON.stringify({
          file_id: rec.fileId || undefined, filename, mime_type: mime, consent_confirmed: true, num_speakers: rec.numSpeakers,
        }),
      });
      id = res.recording.id;
      url = res.upload_url;
      rec.serverId = id;
      await updateSession(rec.id, { serverId: id }).catch(() => {});
    }
    let put: Response;
    try {
      put = await fetch(url, { method: "PUT", body: audio, headers: { "Content-Type": mime } });
    } catch {
      // fetch rejects (no status) on network/CORS/mixed-content failures.
      throw new Error("Could not reach file storage to upload the audio. Check your connection.");
    }
    if (!put.ok) throw new Error(`Upload failed (${put.status}).`);
    await api(`/api/v1/recordings/${id}/uploaded`, { method: "POST", body: duration });
  }

  /** Upload a recording, deleting the on-device copy only once it's safely
   *  stored. One tab at a time per recording. Returns whether it was sent. */
  async function send(rec: LocalRecording, audio?: Blob): Promise<boolean> {
    const attempt = async (): Promise<boolean> => {
      setSending((s) => [...s, rec.id]);
      const release = holdSignOutRedirect();
      try {
        await upload(rec, audio ?? (await loadAudio(rec)));
        await deleteSession(rec.id).catch(() => {});
        qc.invalidateQueries({ queryKey: ["recordings"] });
        return true;
      } catch (e) {
        const msg = (e as Error).message;
        await updateSession(rec.id, { error: msg }).catch(() => {});
        if (msg === SESSION_EXPIRED) setSessionExpired(true);
        else setError(msg);
        return false;
      } finally {
        release();
        setSending((s) => s.filter((x) => x !== rec.id));
        refreshLocal();
      }
    };
    const locks = navigator.locks;
    if (!locks?.request) return attempt();
    return locks.request(`advocatus-upload-${rec.id}`, { ifAvailable: true }, (lock) => (lock ? attempt() : false));
  }

  async function discard(rec: LocalRecording) {
    if (!confirm("Delete this recording from this device? It has not been uploaded and cannot be recovered.")) return;
    await deleteSession(rec.id).catch(() => {});
    refreshLocal();
  }

  // On arrival: upload anything stopped normally but never sent (e.g. the
  // session had expired), and list interrupted recordings for the user to decide.
  useEffect(() => {
    (async () => {
      try {
        const recs = await listSessions(getTenant(), currentUser()?.id || "");
        setLocalRecs(recs);
        for (const r of recs) if (r.state === "pending") await send(r);
      } catch {
        /* IndexedDB unavailable */
      }
    })();
  }, []);

  // While recording or uploading: re-take the screen wake lock when the page
  // returns, flush buffered audio to the device when it is hidden (a locked or
  // backgrounded tab may be killed), and warn before closing the tab.
  const active = recording || sending.length > 0 || !!busy;
  useEffect(() => {
    if (!active) return;
    const onVisibility = () => {
      const mr = mediaRef.current;
      if (document.visibilityState === "visible") {
        if (mr?.state === "recording") keepAwake();
      } else if (mr?.state === "recording") {
        mr.requestData();
      }
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [active]);

  // Leaving the page mid-recording stops the microphone but keeps what was
  // recorded on the device; it is uploaded on the next visit.
  useEffect(() => () => {
    stopMeter();
    releaseWake();
    releaseHold();
    const mr = mediaRef.current;
    const session = sessionRef.current;
    if (mr && mr.state !== "inactive") {
      mr.onstop = () => {
        if (session && persistedRef.current) {
          const durationSeconds = Math.round((Date.now() - session.startedAt) / 1000);
          writesRef.current.then(() => updateSession(session.id, { state: "pending", durationSeconds })).catch(() => {});
        }
      };
      mr.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);
  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files"), enabled: canCreate });

  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/recordings/${id}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recordings"] }),
    onError: (e) => setError((e as Error).message),
  });

  async function stopped(mr: MediaRecorder, stream: MediaStream, session: LocalRecording) {
    stream.getTracks().forEach((t) => t.stop());
    stopMeter();
    releaseWake();
    setRecording(false);
    mediaRef.current = null;
    sessionRef.current = null;
    await writesRef.current; // every chunk is on the device before anything else happens
    const audio = new Blob(chunksRef.current, { type: mr.mimeType || session.mimeType });
    chunksRef.current = [];
    const durationSeconds = Math.round((Date.now() - session.startedAt) / 1000);
    if (peakRef.current < 0.002 || audio.size === 0) {
      await deleteSession(session.id).catch(() => {});
      releaseHold();
      setError(audio.size === 0
        ? "No audio was captured. Check your microphone and try again."
        : "No sound was picked up by the microphone, so nothing was uploaded. Check that the right microphone is selected and unmuted, then try again.");
      return;
    }
    const rec: LocalRecording = { ...session, mimeType: audio.type, durationSeconds, state: "pending" };
    if (persistedRef.current) {
      await updateSession(session.id, { mimeType: rec.mimeType, durationSeconds, state: "pending" }).catch(() => {});
    } else {
      await deleteSession(session.id).catch(() => {}); // incomplete on-device copy
    }
    setBusy("Uploading…");
    const ok = await send(rec, audio);
    setBusy("");
    releaseHold();
    if (!ok && !persistedRef.current) {
      setUnsaved({ url: URL.createObjectURL(audio), name: `recording-${new Date(session.startedAt).toISOString().slice(0, 16)}.${extFor(audio.type)}` });
    }
    refreshLocal();
  }

  async function start() {
    setError("");
    setNotice("");
    setSessionExpired(false);
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
      const now = Date.now();
      const session: LocalRecording = {
        id: crypto.randomUUID(), tenant: getTenant(), userId: currentUser()?.id || "",
        startedAt: now, updatedAt: now, mimeType: mr.mimeType || mimeType || "audio/webm",
        fileId, numSpeakers, durationSeconds: 0, state: "recording",
      };
      sessionRef.current = session;
      persistedRef.current = true;
      writesRef.current = saveSession(session).catch(() => { persistedRef.current = false; });
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size === 0) return;
        chunksRef.current.push(e.data);
        const secs = Math.round((Date.now() - session.startedAt) / 1000);
        writesRef.current = writesRef.current
          .then(() => (persistedRef.current ? appendChunk(session.id, e.data, secs) : undefined))
          .catch(() => { persistedRef.current = false; });
      };
      mr.onerror = () => setError("Recording failed — the microphone was interrupted.");
      mr.onstop = () => { void stopped(mr, stream, session); };
      // The OS can take the microphone away (device locked, a phone call):
      // finish with what was captured instead of losing it.
      stream.getAudioTracks().forEach((t) => {
        t.onended = () => {
          if (mr.state === "inactive") return;
          setNotice("The microphone was cut off (the device may have locked or another app took it). The audio recorded up to that point has been kept.");
          mr.stop();
        };
      });
      startMeter(stream);
      // A timeslice flushes data every few seconds, which is what gets saved to
      // the device as the meeting goes on.
      mr.start(5000);
      mediaRef.current = mr;
      releaseHoldRef.current = holdSignOutRedirect();
      keepAwake();
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
  }

  // A recording counts as interrupted once its heartbeat is stale; a fresh one
  // is still being captured (here or in another tab).
  const unsent = localRecs.filter((r) =>
    r.id !== sessionRef.current?.id && (r.state === "pending" || Date.now() - r.updatedAt > 60_000));

  return (
    <div>
      <h2 className="font-display text-3xl font-bold text-navy">Meeting recordings</h2>
      <p className="mt-1 text-sm text-ink/60">
        The audio is kept in secure cloud storage so you can listen back. Speech-to-text and speaker identification run
        on our own servers; to correct Kenyan English and write the notes and agreed action points, the transcript text
        is processed by our AI model provider.
      </p>

      {canCreate && (
        <div className="card mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <select className="input" value={fileId} onChange={(e) => setFileId(e.target.value)} disabled={recording}
              aria-label="Link to file">
              <option value="">No file linked</option>
              {(filesData?.files || []).map((m: any) => <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>)}
            </select>
            <select className="input" value={numSpeakers} onChange={(e) => setNumSpeakers(Number(e.target.value))}
              disabled={recording} aria-label="People speaking in this meeting">
              {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} {n === 1 ? "person" : "people"} speaking</option>)}
              <option value={0}>Not sure — detect automatically</option>
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
          {recording && (
            <p className="text-xs text-ink/50">
              Audio is saved on this device as you record, so it isn&apos;t lost if the page closes. Keep this tab open
              until the meeting ends.
            </p>
          )}
          {notice && <p className="text-sm text-amber-700">{notice}</p>}
          {sessionExpired && (
            <p className="text-sm text-red-600">
              Your session expired before the recording could be uploaded. It is saved on this device —{" "}
              <a className="font-semibold underline" href={loginPath()}>sign in again</a> and it will upload automatically.
            </p>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {unsaved && (
            <p className="text-sm text-red-600">
              This browser could not keep a copy of the audio.{" "}
              <a className="font-semibold underline" href={unsaved.url} download={unsaved.name}>Save the audio file</a>{" "}
              before leaving this page so the meeting isn&apos;t lost.
            </p>
          )}
        </div>
      )}

      {unsent.length > 0 && (
        <div className="card mt-4 border border-amber-300 bg-amber-50">
          <p className="text-sm font-semibold text-navy">Saved on this device — not uploaded yet</p>
          <ul className="mt-2 space-y-2">
            {unsent.map((r) => {
              const isSending = sending.includes(r.id);
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-3 text-xs text-ink/70">
                  <span>
                    {fmtDate(new Date(r.startedAt).toISOString())} · {clock(r.durationSeconds)}
                    {r.state === "recording" && " · interrupted"}
                  </span>
                  {r.error && !isSending && <span className="text-red-600">{r.error}</span>}
                  <button className="font-semibold text-navy hover:underline disabled:opacity-50" disabled={isSending}
                    onClick={() => send(r)}>
                    {isSending ? "Uploading…" : "⇪ Upload now"}
                  </button>
                  {!isSending && (
                    <button className="text-red-700 hover:underline" onClick={() => discard(r)}>Discard</button>
                  )}
                </li>
              );
            })}
          </ul>
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
  const [showRaw, setShowRaw] = useState(false);
  const insights = parseInsights(r.summary_text);
  const hasSpeakers = (r.transcript_segments || []).length > 0;
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
      {r.status !== "recording" && <AudioControls id={r.id} />}
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
          {hasSpeakers ? <TranscriptView r={r} ins={null} /> : (
            <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink/80">{r.transcript_text}</pre>
          )}
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
              <div className="min-w-0">
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-navy/60">Notes</p>
                {insights ? (
                  <InsightsView ins={insights} fileId={r.file_id} />
                ) : (
                  <pre className="whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink">{r.summary_text || "—"}</pre>
                )}
              </div>
              <div className="min-w-0">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="text-xs font-bold uppercase tracking-wide text-navy/60">
                    Transcript
                    {r.transcript_raw && (
                      <button className="ml-2 font-normal normal-case text-navy hover:underline"
                        title="The transcript was proofread by AI for Kenyan English (names, places, legal terms)."
                        onClick={() => setShowRaw(!showRaw)}>
                        {showRaw ? "· show AI-corrected" : "· AI-corrected — show original"}
                      </button>
                    )}
                  </p>
                  {hasSpeakers && !showRaw && <SpeakerNamer r={r} ins={insights} />}
                </div>
                {showRaw && r.transcript_raw ? (
                  <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink/80">{r.transcript_raw}</pre>
                ) : hasSpeakers ? <TranscriptView r={r} ins={insights} /> : (
                  <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded bg-navy/5 p-3 text-xs leading-relaxed text-ink/80">{r.transcript_text || "—"}</pre>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Listen to or download the original audio, kept alongside the transcript.
 *  Links are short-lived, so they are fetched on demand. */
function AudioControls({ id }: { id: string }) {
  const [src, setSrc] = useState("");
  const [err, setErr] = useState("");
  const links = () => api<{ url: string; download_url: string }>(`/api/v1/recordings/${id}/audio`);
  async function listen() {
    setErr("");
    try { setSrc((await links()).url); } catch (e) { setErr((e as Error).message); }
  }
  async function download() {
    setErr("");
    try { window.location.href = (await links()).download_url; } catch (e) { setErr((e as Error).message); }
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3">
      {src ? (
        // A long pause can outlive the signed link; fetch a fresh one on error.
        <audio controls autoPlay src={src} className="h-8 w-full max-w-md" onError={() => setSrc("")} />
      ) : (
        <button className="text-xs text-navy hover:underline" onClick={listen}>▶ Listen</button>
      )}
      <button className="text-xs text-navy hover:underline" onClick={download}>⬇ Audio</button>
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  );
}

function TranscriptView({ r, ins }: { r: Recording; ins: Insights | null }) {
  const turns = namedTurns(r, ins);
  return (
    <div className="max-h-96 space-y-2 overflow-y-auto rounded bg-navy/5 p-3 text-xs leading-relaxed">
      {turns.map((t, i) => (
        <p key={i}>
          <span className="mr-1 font-mono text-[10px] text-ink/40">{clock(t.start)}</span>
          <span className={`font-semibold ${SPEAKER_COLORS[(t.speaker - 1) % SPEAKER_COLORS.length]}`}>{t.who}:</span>{" "}
          <span className="text-ink/80">{t.text}</span>
        </p>
      ))}
    </div>
  );
}

/** Rename speaker labels. Giving two labels the same name merges them. */
function SpeakerNamer({ r, ins }: { r: Recording; ins: Insights | null }) {
  const qc = useQueryClient();
  const labels = Array.from(new Set((r.transcript_segments || []).map((u) => u.speaker))).sort((a, b) => a - b);
  const [open, setOpen] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => api(`/api/v1/recordings/${r.id}/speakers`, { method: "PUT", body: JSON.stringify({ names }) }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["recordings"] }); },
  });
  if (!open) {
    return (
      <button className="text-xs text-navy hover:underline"
        onClick={() => { setNames({ ...(r.speaker_names || {}) }); setOpen(true); }}>
        ✎ Name speakers
      </button>
    );
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setOpen(false)}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-lg font-bold text-navy">Who&apos;s speaking?</h3>
        <p className="mt-1 text-xs text-ink/60">
          If one person was split into two speakers, give both the same name and they&apos;ll be merged.
        </p>
        <div className="mt-4 space-y-2">
          {labels.map((n) => {
            const first = (r.transcript_segments || []).find((u) => u.speaker === n);
            return (
              <label key={n} className="block">
                <span className="text-xs font-semibold text-navy/70">
                  Speaker {n}
                  {first && <span className="font-normal text-ink/50"> — “{first.text.slice(0, 60)}{first.text.length > 60 ? "…" : ""}”</span>}
                </span>
                <input className="input mt-1" value={names[String(n)] || ""} maxLength={80}
                  placeholder={speakerName(n, null, ins)}
                  onChange={(e) => setNames((prev) => ({ ...prev, [String(n)]: e.target.value }))} />
              </label>
            );
          })}
        </div>
        {save.isError && <p className="mt-2 text-xs text-red-600">{(save.error as Error).message}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-outline" onClick={() => setOpen(false)}>Cancel</button>
          <button className="btn-gold" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save names"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddAsTask({ fileId, item }: { fileId: string; item: ActionItem }) {
  const create = useMutation({
    mutationFn: () => api("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify({
        file_id: fileId,
        title: (item.task_description || "Action point").slice(0, 200),
        description: [
          item.assignee && `Agreed owner: ${item.assignee}`,
          item.deadline && `Deadline as discussed: ${item.deadline}`,
          item.source && `From the meeting: “${item.source}”`,
        ].filter(Boolean).join("\n"),
      }),
    }),
  });
  if (create.isSuccess) return <span className="text-[11px] text-green-700">✓ added to tasks</span>;
  return (
    <button className="text-[11px] font-semibold text-navy hover:underline disabled:opacity-50"
      disabled={create.isPending} onClick={() => create.mutate()}
      title={create.isError ? (create.error as Error).message : "Create a task on this file"}>
      {create.isPending ? "Adding…" : create.isError ? "Retry add as task" : "+ Add as task"}
    </button>
  );
}

function InsightsView({ ins, fileId }: { ins: Insights; fileId?: string | null }) {
  const { can } = usePermissions();
  const canTask = !!fileId && can("tasks.create");
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
          <p className="text-[11px] font-bold uppercase tracking-wide text-navy/50">Agreed action points</p>
          <ul className="mt-1 space-y-2 text-xs text-ink/80">
            {ins.action_items.map((a, i) => (
              <li key={i} className="rounded border border-navy/10 bg-white p-2">
                <span className="font-semibold text-navy">{a.assignee || "Unassigned"}</span>
                {a.deadline ? <span className="text-ink/50"> · due {a.deadline}</span> : null}
                <br />
                {a.task_description}
                {a.source && <span className="mt-1 block italic text-ink/50">“{a.source}”</span>}
                {canTask && <span className="mt-1 block"><AddAsTask fileId={fileId!} item={a} /></span>}
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
