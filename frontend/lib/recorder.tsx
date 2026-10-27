"use client";

// The meeting recorder lives here, above every page, rather than inside the
// recordings page: navigating to another part of the app (or switching to
// another browser tab) leaves the microphone running and the upload going.
// Audio is still mirrored to IndexedDB chunk by chunk (lib/recordingStore), so
// even closing the tab only interrupts the recording — it is offered for upload
// on the next visit.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, currentUser, getTenant, holdSignOutRedirect, SESSION_EXPIRED } from "@/lib/api";
import {
  appendChunk, deleteSession, listSessions, loadAudio, saveSession, updateSession, type LocalRecording,
} from "@/lib/recordingStore";

// MediaRecorder container support differs by browser (Chrome/Firefox: webm/ogg,
// Safari: mp4). Pick one the browser can actually produce.
const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
function pickMime(): string {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}
export function extFor(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

const TITLE_PREFIX = "● REC · ";
const DONE = ["complete", "failed"];

/** An uploaded recording the server is still transcribing / writing notes for. */
export type Processing = { id: string; filename: string; status: string; error?: string };

type Recorder = {
  recording: boolean;
  /** When the current recording started (ms), for the elapsed-time display. */
  startedAt: number | null;
  /** Live input level 0..1. */
  level: number;
  busy: string;
  error: string;
  notice: string;
  sessionExpired: boolean;
  /** Last resort when the browser can't store audio locally and the upload failed. */
  unsaved: { url: string; name: string } | null;
  /** Recordings saved on this device that haven't reached cloud storage yet. */
  localRecs: LocalRecording[];
  sending: string[];
  /** The id of the on-device session being captured right now. */
  currentId: string | null;
  processing: Processing[];
  start: (opts: { fileId: string; numSpeakers: number }) => Promise<void>;
  stop: () => void;
  /** Stop without uploading (e.g. signing out): the audio stays on the device. */
  abandon: () => Promise<void>;
  send: (rec: LocalRecording, audio?: Blob) => Promise<boolean>;
  discard: (rec: LocalRecording) => Promise<void>;
  refreshLocal: () => Promise<void>;
  /** Upload anything stopped normally but never sent (e.g. the session had expired). */
  sendPending: () => Promise<void>;
  clearMessages: () => void;
  dismissProcessing: (id: string) => void;
};

const Ctx = createContext<Recorder | null>(null);

export function useRecorder(): Recorder {
  const r = useContext(Ctx);
  if (!r) throw new Error("useRecorder must be used inside <RecorderProvider>");
  return r;
}

export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [recording, setRecording] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);
  const [unsaved, setUnsaved] = useState<{ url: string; name: string } | null>(null);
  const [localRecs, setLocalRecs] = useState<LocalRecording[]>([]);
  const [sending, setSending] = useState<string[]>([]);
  const [processing, setProcessing] = useState<Processing[]>([]);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // Live input level: lets the user see the mic is actually picking up sound,
  // and lets us refuse to upload a recording that is pure silence.
  const [level, setLevel] = useState(0);
  const peakRef = useRef(0);
  const meterRef = useRef<{ ctx: AudioContext; timer: number } | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // The recording in progress, mirrored to IndexedDB chunk by chunk.
  const sessionRef = useRef<LocalRecording | null>(null);
  const writesRef = useRef<Promise<void>>(Promise.resolve());
  const persistedRef = useRef(true);
  // Set by abandon(): the onstop handler keeps the audio on the device instead
  // of uploading, then calls this once it is saved.
  const abandonRef = useRef<(() => void) | null>(null);
  const wakeRef = useRef<WakeLockSentinel | null>(null);
  const releaseHoldRef = useRef<(() => void) | null>(null);

  function stopMeter() {
    const m = meterRef.current;
    if (m) { clearInterval(m.timer); m.ctx.close().catch(() => {}); }
    meterRef.current = null;
    setLevel(0);
  }

  // Sampled on a timer rather than requestAnimationFrame: animation frames stop
  // entirely in a background tab, which would leave the silence check blind for
  // a meeting recorded while the user works in another tab. Timers keep running
  // there (throttled to about once a second, which is plenty for a peak).
  function startMeter(stream: MediaStream) {
    peakRef.current = 0;
    try {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const timer = window.setInterval(() => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        const rms = Math.sqrt(sum / buf.length);
        peakRef.current = Math.max(peakRef.current, rms);
        if (document.visibilityState === "visible") setLevel(Math.min(1, rms * 8));
      }, 100);
      meterRef.current = { ctx, timer };
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

  // The tab title shows the recording is live, so it can be spotted from another tab.
  function markTitle(on: boolean) {
    const t = document.title.startsWith(TITLE_PREFIX) ? document.title.slice(TITLE_PREFIX.length) : document.title;
    document.title = on ? TITLE_PREFIX + t : t;
  }

  const refreshLocal = useCallback(async () => {
    try {
      setLocalRecs(await listSessions(getTenant(), currentUser()?.id || ""));
    } catch {
      /* IndexedDB unavailable: nothing to recover */
    }
  }, []);

  /** Put a recording's audio in cloud storage and hand it to the transcription
   *  worker. Reuses the server row of an earlier, interrupted attempt. */
  async function upload(rec: LocalRecording, audio: Blob): Promise<string> {
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
          return id;
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
      const res = await api<{ recording: { id: string }; upload_url: string }>("/api/v1/recordings", {
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
    return id;
  }

  /** Upload a recording, deleting the on-device copy only once it's safely
   *  stored. One tab at a time per recording. Returns whether it was sent. */
  async function send(rec: LocalRecording, audio?: Blob): Promise<boolean> {
    const attempt = async (): Promise<boolean> => {
      setSending((s) => [...s, rec.id]);
      const release = holdSignOutRedirect();
      try {
        const id = await upload(rec, audio ?? (await loadAudio(rec)));
        await deleteSession(rec.id).catch(() => {});
        qc.invalidateQueries({ queryKey: ["recordings"] });
        setProcessing((p) => p.some((x) => x.id === id) ? p : [...p, {
          id, status: "transcribing",
          filename: `Meeting of ${new Date(rec.startedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`,
        }]);
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

  async function sendPending() {
    if (!currentUser()) return;
    try {
      const recs = await listSessions(getTenant(), currentUser()?.id || "");
      setLocalRecs(recs);
      for (const r of recs) if (r.state === "pending") await send(r);
    } catch {
      /* IndexedDB unavailable */
    }
  }

  useEffect(() => { void sendPending(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function stopped(mr: MediaRecorder, stream: MediaStream, session: LocalRecording) {
    stream.getTracks().forEach((t) => t.stop());
    stopMeter();
    releaseWake();
    markTitle(false);
    setRecording(false);
    setStartedAt(null);
    mediaRef.current = null;
    sessionRef.current = null;
    await writesRef.current; // every chunk is on the device before anything else happens
    const audio = new Blob(chunksRef.current, { type: mr.mimeType || session.mimeType });
    chunksRef.current = [];
    const durationSeconds = Math.round((Date.now() - session.startedAt) / 1000);
    const abandoned = abandonRef.current;
    if (abandoned) {
      abandonRef.current = null;
      if (persistedRef.current) {
        await updateSession(session.id, { mimeType: audio.type, durationSeconds, state: "pending" }).catch(() => {});
      }
      releaseHold();
      await refreshLocal();
      abandoned();
      return;
    }
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

  async function start({ fileId, numSpeakers }: { fileId: string; numSpeakers: number }) {
    setError("");
    setNotice("");
    setSessionExpired(false);
    if (mediaRef.current) return;
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
      abandonRef.current = null;
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
      markTitle(true);
      setStartedAt(now);
      setRecording(true);
      // Lets us say "notes ready" while the user is in another tab. Asked once,
      // never blocks recording.
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
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

  async function abandon() {
    const mr = mediaRef.current;
    if (!mr || mr.state === "inactive") return;
    const saved = new Promise<void>((resolve) => { abandonRef.current = resolve; });
    mr.stop();
    await saved;
  }

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
    const onPageHide = () => { if (mediaRef.current?.state === "recording") mediaRef.current.requestData(); };
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [active]);

  // Pages (e.g. the Shell setting the firm name) may overwrite the tab title
  // mid-recording; put the marker back.
  useEffect(() => {
    if (!recording) return;
    const t = window.setInterval(() => { if (!document.title.startsWith(TITLE_PREFIX)) markTitle(true); }, 2000);
    return () => clearInterval(t);
  }, [recording]);

  // Follow uploaded recordings through transcription and notes, wherever the
  // user is in the app, and tell them when each is ready.
  const pendingIds = processing.filter((p) => !DONE.includes(p.status)).map((p) => p.id).join(",");
  useEffect(() => {
    if (!pendingIds) return;
    const ids = pendingIds.split(",");
    const poll = async () => {
      for (const id of ids) {
        try {
          const { recording: r } = await api<{ recording: Processing }>(`/api/v1/recordings/${id}`);
          setProcessing((list) => list.map((p) => {
            if (p.id !== id || p.status === r.status) return p;
            if (DONE.includes(r.status)) {
              qc.invalidateQueries({ queryKey: ["recordings"] });
              if (document.visibilityState === "hidden" && typeof Notification !== "undefined" &&
                  Notification.permission === "granted") {
                try {
                  new Notification(r.status === "complete" ? "Meeting notes ready" : "Transcription failed", {
                    body: r.status === "complete" ? "The transcript and notes are ready to view." : r.error || "Open Recordings to retry.",
                  });
                } catch { /* some mobile browsers only allow notifications from a service worker */ }
              }
            }
            return { ...p, status: r.status, error: r.error };
          }));
        } catch {
          /* transient: try again on the next tick */
        }
      }
    };
    const t = window.setInterval(poll, 5000);
    return () => clearInterval(t);
  }, [pendingIds, qc]);

  const value: Recorder = {
    recording, startedAt, level, busy, error, notice, sessionExpired, unsaved, localRecs, sending,
    currentId: sessionRef.current?.id ?? null, processing,
    start, stop, abandon, send, discard, refreshLocal, sendPending,
    clearMessages: () => { setError(""); setNotice(""); setSessionExpired(false); },
    dismissProcessing: (id) => setProcessing((p) => p.filter((x) => x.id !== id)),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
