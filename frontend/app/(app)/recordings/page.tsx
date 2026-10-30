"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, loginPath } from "@/lib/api";
import { useRecorder } from "@/lib/recorder";
import { usePermissions } from "@/lib/usePermissions";
import NewFileDialog from "@/components/NewFileDialog";

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
  const [newFile, setNewFile] = useState(false);

  const [consent, setConsent] = useState(false);
  const [fileId, setFileId] = useState("");
  // Knowing the head-count makes speaker labels far more accurate than guessing.
  const [numSpeakers, setNumSpeakers] = useState(2);
  // The recorder itself lives app-wide (lib/recorder) so it keeps going when
  // the user moves to another page or tab.
  const {
    recording, level, busy, error, notice, sessionExpired, unsaved, localRecs, sending, currentId,
    interrupted, screenAwake, start: startRecorder, resume, stop, send, discard, sendPending,
  } = useRecorder();
  const [consentError, setConsentError] = useState("");

  const { data } = useQuery({
    queryKey: ["recordings"],
    queryFn: () => api(`/api/v1/recordings${canAll ? "?scope=all" : ""}`),
    refetchInterval: (q) => ((q.state.data?.recordings || []).some((r: Recording) => PENDING.includes(r.status)) ? 4000 : false),
  });
  const recordings: Recording[] = data?.recordings || [];

  // On arrival: upload anything stopped normally but never sent, and list
  // interrupted recordings for the user to decide.
  useEffect(() => { void sendPending(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files"), enabled: canCreate });

  const [retryError, setRetryError] = useState("");
  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/recordings/${id}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recordings"] }),
    onError: (e) => setRetryError((e as Error).message),
  });

  function start() {
    setConsentError("");
    setRetryError("");
    if (!consent) { setConsentError("Confirm client consent before recording."); return; }
    void startRecorder({ fileId, numSpeakers });
  }

  // A recording counts as interrupted once its heartbeat is stale; a fresh one
  // is still being captured (here or in another tab).
  const unsent = localRecs.filter((r) =>
    r.id !== currentId && (r.state === "pending" || Date.now() - r.updatedAt > 60_000));

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
            <div className="flex gap-2">
              <select className="input min-w-0 flex-1" value={fileId} onChange={(e) => setFileId(e.target.value)} disabled={recording}
                aria-label="Link to file">
                <option value="">No file linked</option>
                {(filesData?.files || []).map((m: any) => <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>)}
              </select>
              {can("matters.create") && (
                <button type="button" className="btn-outline shrink-0 whitespace-nowrap" disabled={recording}
                  title="Register a new file and link this recording to it" onClick={() => setNewFile(true)}>
                  + New file
                </button>
              )}
            </div>
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
              Recording continues while you use other pages or switch tabs — stop it from here or from the
              recording panel in the corner. Audio is saved on this device as you record, so it isn&apos;t lost if the
              tab is closed, but the microphone stops then: keep this tab open until the meeting ends.
            </p>
          )}
          {recording && screenAwake === false && (
            <p className="text-sm text-amber-700">
              This browser can&apos;t keep the screen on while recording. Don&apos;t let the phone lock (tap the screen now and
              then, or lengthen the screen timeout) — the microphone stops when it locks.
            </p>
          )}
          {notice && <p className="text-sm text-amber-700">{notice}</p>}
          {interrupted && !recording && (
            <button className="btn-primary !bg-red-700" onClick={() => void resume()}>● Continue recording</button>
          )}
          {sessionExpired && (
            <p className="text-sm text-red-600">
              Your session expired before the recording could be uploaded. It is saved on this device —{" "}
              <a className="font-semibold underline" href={loginPath()}>sign in again</a> and it will upload automatically.
            </p>
          )}
          {(consentError || error || retryError) && (
            <p className="text-sm text-red-600">{consentError || error || retryError}</p>
          )}
          {unsaved && (
            <p className="text-sm text-red-600">
              This browser could not keep a copy of the audio.{" "}
              <a className="font-semibold underline" href={unsaved.url} download={unsaved.name}>Save the audio file</a>{" "}
              before leaving this page so the meeting isn&apos;t lost.
            </p>
          )}
        </div>
      )}

      {newFile && <NewFileDialog onClose={() => setNewFile(false)} onCreated={(f) => setFileId(f.id)} />}

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
