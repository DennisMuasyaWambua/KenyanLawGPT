"""Meeting-recording processor: transcribe + attribute speakers (local Whisper
and on-box diarization), then write meeting notes.

Client-meeting audio is privileged, KDPA/POCAMLA-sensitive material:

  * audio never leaves the box — transcription uses ``make_transcriber``, which
    never auto-selects a cloud STT, and diarization runs locally;
  * the Kenyan-English proofreading pass (``transcript_cleanup``) and the
    notes step (summary, decisions, agreed action points) send the
    TRANSCRIPT TEXT to GMI Cloud when RECORDINGS_SUMMARY_PROVIDER=gmi (the
    operator's choice; GMI's synthetic-data gate still applies outside prod),
    falling back to local Ollama. RECORDINGS_SUMMARY_PROVIDER=local keeps it
    entirely on-box.

The worker polls every active tenant for recordings in the ``transcribing``
state (set by the gateway once audio has landed in R2), mirroring the
AutoUpdateWatcher background-task pattern. No gRPC surface is added.
"""

from __future__ import annotations

import asyncio
import json
import logging

from minio import Minio
from minio.error import S3Error

from .config import Config
from .db import tenant_tx
from .diarization import format_transcript
from .llm import GMICloudProvider, OllamaProvider
from .tenancy import validate_tenant_id
from . import transcript_cleanup
from .transcription import LazyTranscriber, TranscriptionProvider

log = logging.getLogger("recordings")

_SUMMARY_SYSTEM = (
    "You take the minutes of meetings at a Kenyan law firm — usually an advocate "
    "and a client, sometimes colleagues, witnesses or opposing parties. The "
    "transcript comes from speech recognition, so expect some misheard words; it "
    "may be in English, Swahili or a mix. When speakers are labelled "
    '"Speaker 1", "Speaker 2", … the labels reliably tell you who said what, but '
    "not their names.\n\n"
    "Return a strictly valid JSON object with these keys:\n\n"
    "executive_summary: 2-4 sentences on the purpose of the meeting and its outcome.\n\n"
    "speakers: an array of objects, one per speaker label, each with label (e.g. "
    '"Speaker 1"), role (who they appear to be: "Advocate", "Client", "Witness", '
    '"Colleague", or "Unknown") and name (only if clearly stated in the '
    "conversation, otherwise null). Empty array if speakers are not labelled.\n\n"
    "key_discussion_points: an array of strings covering the main topics.\n\n"
    "decisions_made: an array of strings — only what was actually decided or agreed.\n\n"
    "action_items: an array of objects, one per task someone AGREED or COMMITTED "
    "to do (not ideas, options or suggestions nobody took up). Each has assignee "
    "(the person who will do it — their name if known, otherwise role and label, "
    'e.g. "Advocate (Speaker 1)"; "Unassigned" if unclear), task_description (a '
    "specific, self-contained instruction), deadline (exactly as stated, e.g. "
    '"by Friday" or "14 March", otherwise null), agreed_by (the speaker label(s) '
    "who agreed to it, or null) and source (a short verbatim quote, at most 20 "
    "words, from where it was agreed).\n\n"
    "open_questions: an array of strings — unresolved issues or matters deferred.\n\n"
    "Rules: write the notes in English even when the meeting was in Swahili or "
    "mixed, keeping names, places, case numbers, amounts and legal terms exactly "
    "as spoken. Never invent facts, names, amounts or deadlines that are not in "
    "the transcript. Use empty arrays when there is nothing to report. Output ONLY "
    "the JSON object — no markdown fences, preamble or commentary."
)

_SUMMARY_TEMPLATE = "Transcript:\n\n{transcript}"

# How much transcript each notes model sees. The local model's context is small;
# GMI's hosted models take a long meeting whole.
_LOCAL_TRANSCRIPT_CHARS = 12000
_SUMMARIZING_STALE_MINUTES = 5
_UPLOAD_GIVE_UP_MINUTES = 60
# A recording that has started processing this many times without finishing is
# assumed to be crashing the worker (e.g. OOM) and is failed rather than retried.
_MAX_ATTEMPTS = 3


def _clip_transcript(transcript: str, limit: int) -> str:
    """Fit a long transcript into ``limit`` chars by dropping the middle. The end
    is kept generously: agreements and next steps are usually settled as a
    meeting wraps up, which plain truncation used to cut off."""
    if len(transcript) <= limit:
        return transcript
    head = limit // 3
    tail = limit - head
    return (transcript[:head] + "\n[… middle of the meeting omitted for length …]\n"
            + transcript[-tail:])


def _extract_json(text: str) -> str:
    """Best-effort recovery of the raw JSON object from an LLM response: strip any
    markdown code fence and slice from the first ``{`` to the last ``}``. Returns
    a normalized JSON string when it parses, otherwise the best-effort candidate
    (the frontend/email formatter fall back to showing it verbatim)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        candidate = t[start : end + 1]
        try:
            return json.dumps(json.loads(candidate), ensure_ascii=False)
        except Exception:
            return candidate
    return t


class RecordingProcessor:
    def __init__(self, pool, cfg: Config, transcriber: TranscriptionProvider | None = None) -> None:
        self.pool = pool
        self.cfg = cfg
        self._task = None
        self._stopping = False
        # Shared with archive ingestion (one Whisper model in memory), built lazily.
        self._transcriber = transcriber or LazyTranscriber(cfg)
        self._local_llm = None
        self._gmi_llm = None
        self._minio = Minio(
            cfg.s3_endpoint, access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key, secure=cfg.s3_use_ssl, region=cfg.s3_region or None,
        )

    async def start(self) -> None:
        self._stopping = False

        async def _loop() -> None:
            while not self._stopping:
                try:
                    await self.run_once()
                except Exception:  # noqa: BLE001 — a bad tenant must not kill the loop
                    log.exception("recordings: processing pass failed")
                await asyncio.sleep(max(2, self.cfg.recordings_poll_seconds))

        self._task = asyncio.create_task(_loop())
        if self.cfg.recordings_prewarm and hasattr(self._transcriber, "warm"):
            self._warm_task = asyncio.create_task(self._transcriber.warm())
        log.info("recording processor started (poll=%ss, whisper=%s, notes=%s)",
                 self.cfg.recordings_poll_seconds, self.cfg.whisper_model,
                 "GMI Cloud + local fallback" if self._use_gmi() else "local Ollama")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> int:
        """Process every pending recording across all active tenants. Returns the
        number handled."""
        async with self.pool.acquire() as conn:
            tenants = await conn.fetch(
                "SELECT id::text AS id FROM public.tenants WHERE status = 'active'")
        handled = 0
        for row in tenants:
            handled += await self._process_tenant(row["id"])
        return handled

    async def _process_tenant(self, tenant_id: str) -> int:
        try:
            validate_tenant_id(tenant_id)
        except Exception:
            return 0
        # Grab the pending queue in a short transaction, then process each one in
        # its own transaction so a slow transcription doesn't hold a connection.
        async with tenant_tx(self.pool, tenant_id) as conn:
            pending = await conn.fetch(
                "SELECT id::text AS id, object_key, filename, mime_type, num_speakers "
                "FROM meeting_recordings WHERE status = 'transcribing' ORDER BY created_at LIMIT 5")
            # Safety net: a recording whose browser uploaded the audio but never
            # confirmed via POST /uploaded is stuck in 'recording'. After a grace
            # window (so we don't race a still-in-progress upload) pick it up too,
            # but only once the audio is actually present in storage.
            stuck = await conn.fetch(
                "SELECT id::text AS id, object_key, filename, mime_type, num_speakers, "
                "EXTRACT(EPOCH FROM (now() - created_at)) / 60 AS age_minutes "
                "FROM meeting_recordings WHERE status = 'recording' "
                "AND created_at < now() - interval '2 minutes' ORDER BY created_at LIMIT 5")
            # A worker restart mid-summary strands the row in 'summarizing' (the
            # transcript is already saved). Re-run just the summary step.
            resummarize = await conn.fetch(
                "SELECT id::text AS id, transcript_text FROM meeting_recordings "
                "WHERE status = 'summarizing' "
                f"AND updated_at < now() - interval '{_SUMMARIZING_STALE_MINUTES} minutes' "
                "ORDER BY updated_at LIMIT 5")
        handled = 0
        for rec in resummarize:
            log.info("recovering recording %s stuck in 'summarizing'", rec["id"])
            await self._finish_summary(tenant_id, rec["id"], rec["transcript_text"] or "")
            handled += 1
        for rec in pending:
            await self._process_one(tenant_id, rec["id"], rec["object_key"], rec["filename"],
                                    rec["mime_type"], rec["num_speakers"])
            handled += 1
        for rec in stuck:
            if not await self._object_exists(rec["object_key"]):
                # Still uploading, or the browser never finished (tab closed, network
                # drop). Give up after a while so it doesn't sit "recording" forever.
                if rec["age_minutes"] > _UPLOAD_GIVE_UP_MINUTES:
                    await self._update(tenant_id, rec["id"], status="failed",
                                       error="audio upload never completed — please record again")
                continue
            log.info("recovering stuck recording %s (uploaded but not confirmed)", rec["id"])
            await self._update(tenant_id, rec["id"], status="transcribing")
            await self._process_one(tenant_id, rec["id"], rec["object_key"], rec["filename"],
                                    rec["mime_type"], rec["num_speakers"])
            handled += 1
        return handled

    async def _process_one(self, tenant_id: str, rec_id: str, object_key: str,
                           filename: str, mime_type: str, num_speakers: int = 0) -> None:
        try:
            attempt = await self._claim_attempt(tenant_id, rec_id)
            if attempt > _MAX_ATTEMPTS:
                await self._update(tenant_id, rec_id, status="failed", error=(
                    f"processing was interrupted {attempt - 1} times (the file may be too long "
                    "or too large for this server) — try a shorter recording"))
                return
            audio = await self._fetch_object(tenant_id, object_key)
            result = await self._transcriber.transcribe(
                audio, filename or "audio", mime_type or "", diarize=True, num_speakers=num_speakers or 0)
            if result.provider == "mock":
                # The offline mock emits a placeholder, not speech. Summarizing it
                # would fabricate "meeting notes" from nothing, so fail loudly.
                await self._update(tenant_id, rec_id, status="failed", error=(
                    "Speech-to-text is not available on this server (no local Whisper). "
                    "Install faster-whisper or set TRANSCRIBE_PROVIDER=openai."))
                return
            segments = result.segments or []
            raw = format_transcript(segments) if segments else (result.text or "").strip()
            if not raw:
                # Nothing intelligible: usually a muted/wrong microphone. Say so
                # rather than reporting an empty "complete" recording.
                await self._update(tenant_id, rec_id, status="failed", error=(
                    "No speech was detected in this recording. Check that the right "
                    "microphone is selected and unmuted, then record again."))
                return

            # Show the transcript straight away; correction and notes follow.
            await self._update(tenant_id, rec_id, status="summarizing", transcript_text=raw,
                               transcript_segments=json.dumps(segments, ensure_ascii=False))
            segments, transcript, note = await self._correct(segments, raw)
            if transcript != raw:
                await self._update(tenant_id, rec_id, transcript_text=transcript, transcript_raw=raw,
                                   transcript_segments=json.dumps(segments, ensure_ascii=False))
            await self._finish_summary(tenant_id, rec_id, transcript, note)
            log.info("recording %s transcribed (%d chars, lang=%s, speakers=%d)", rec_id, len(transcript),
                     result.language, len({u["speaker"] for u in segments}))
        except Exception as exc:  # noqa: BLE001
            log.exception("recording %s failed", rec_id)
            await self._update(tenant_id, rec_id, status="failed",
                               error=(str(exc) or exc.__class__.__name__)[:500])

    async def _claim_attempt(self, tenant_id: str, rec_id: str) -> int:
        """Record that processing is starting and return the attempt number. It is
        committed before the heavy work, so a hard crash still counts."""
        async with tenant_tx(self.pool, tenant_id) as conn:
            return await conn.fetchval(
                "UPDATE meeting_recordings SET attempts = attempts + 1, updated_at = now() "
                "WHERE id = $1 RETURNING attempts", rec_id)

    async def _finish_summary(self, tenant_id: str, rec_id: str, transcript: str, note: str = "") -> None:
        """Summarize a stored transcript and mark the recording complete. Never
        leaves the row in 'summarizing': any failure still yields 'complete' with
        the transcript and a note, because the transcript is the valuable part."""
        try:
            summary, err = await self._summarize(transcript)
        except Exception as exc:  # noqa: BLE001
            log.exception("recording %s summary step crashed", rec_id)
            summary, err = "", f"summary unavailable: {exc}"[:500]
        err = "; ".join(m for m in (note, err) if m)[:500]
        await self._update(tenant_id, rec_id, status="complete", summary_text=summary, error=err)

    def _use_gmi(self) -> bool:
        return (self.cfg.recordings_summary_provider or "").lower() == "gmi" and bool(self.cfg.gmi_cloud_api_key)

    def _gmi(self) -> GMICloudProvider:
        if not self._gmi_llm:
            self._gmi_llm = GMICloudProvider(self.cfg, model=self.cfg.recordings_summary_model or None)
        return self._gmi_llm

    async def _correct(self, segments: list[dict], transcript: str) -> tuple[list[dict], str, str]:
        """Proofread the Whisper transcript for Kenyan English (see
        ``transcript_cleanup``). Returns (segments, transcript, note). Best-effort:
        whatever can't be corrected keeps Whisper's text, and the recording is
        never failed here."""
        if not (self.cfg.recordings_transcript_cleanup and self._use_gmi()):
            return segments, transcript, ""
        try:
            if segments:
                segments, changed, failed = await transcript_cleanup.correct_segments(self._gmi(), segments)
                transcript = format_transcript(segments)
            else:
                transcript, changed, failed = await transcript_cleanup.correct_plain(self._gmi(), transcript)
        except Exception as exc:  # noqa: BLE001
            log.warning("transcript correction failed, keeping the Whisper transcript: %s", exc)
            return segments, transcript, f"transcript was not AI-corrected ({exc})"[:300]
        log.info("transcript corrected for Kenyan English: %d lines changed, %d batches failed", changed, failed)
        note = "parts of the transcript could not be AI-corrected and are shown as recognised" if failed else ""
        return segments, transcript, note

    async def _summarize(self, transcript: str) -> tuple[str, str]:
        """Extract structured meeting notes (JSON, see ``_SUMMARY_SYSTEM``) —
        GMI Cloud first when configured, else/then local Ollama. Best-effort: if
        no model answers we still deliver the transcript (empty summary + note).
        Non-JSON responses are passed through; the UI/email render them verbatim.
        Returns (summary, note)."""
        if not transcript:
            return "", "empty transcript"
        note = ""
        if self._use_gmi():
            try:
                prompt = _SUMMARY_TEMPLATE.format(
                    transcript=_clip_transcript(transcript, max(_LOCAL_TRANSCRIPT_CHARS,
                                                                self.cfg.recordings_summary_max_chars)))
                summary = await self._gmi().complete(_SUMMARY_SYSTEM, prompt, max_tokens=4000)
                if summary and summary.strip():
                    return _extract_json(summary), ""
                raise RuntimeError("empty response")
            except Exception as exc:  # noqa: BLE001
                log.warning("recording notes via GMI Cloud failed, using local model: %s", exc)
                note = f"notes were written by the on-box model because GMI Cloud failed ({exc})"[:500]
        try:
            if not self._local_llm:
                self._local_llm = OllamaProvider(self.cfg)
            prompt = _SUMMARY_TEMPLATE.format(transcript=_clip_transcript(transcript, _LOCAL_TRANSCRIPT_CHARS))
            summary = await self._local_llm.complete(_SUMMARY_SYSTEM, prompt, max_tokens=2000)
            return _extract_json(summary or ""), note
        except Exception as exc:  # noqa: BLE001
            log.warning("recording summary (local LLM) failed: %s", exc)
            return "", f"summary unavailable: {exc}"[:500]

    async def _update(self, tenant_id: str, rec_id: str, **fields) -> None:
        sets, args = [], []
        for k, v in fields.items():
            args.append(v)
            sets.append(f"{k} = ${len(args)}")
        sets.append("updated_at = now()")
        args.append(rec_id)
        sql = f"UPDATE meeting_recordings SET {', '.join(sets)} WHERE id = ${len(args)}"
        async with tenant_tx(self.pool, tenant_id) as conn:
            await conn.execute(sql, *args)

    async def _fetch_object(self, tenant_id: str, object_key: str) -> bytes:
        prefix = f"tenants/{tenant_id}/"
        if not object_key.startswith(prefix):
            raise PermissionError("object key outside tenant prefix")

        def _get() -> bytes:
            resp = self._minio.get_object(self.cfg.s3_bucket, object_key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(_get)

    async def _object_exists(self, object_key: str) -> bool:
        def _stat() -> bool:
            try:
                self._minio.stat_object(self.cfg.s3_bucket, object_key)
                return True
            except S3Error as exc:
                if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                    return False
                raise
        return await asyncio.to_thread(_stat)
