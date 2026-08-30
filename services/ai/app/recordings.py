"""Meeting-recording processor: transcribe (local Whisper) then summarize
(local LLM), entirely on-box.

Client-meeting audio is privileged, KDPA/POCAMLA-sensitive material. Two hard
rules are enforced here:

  * transcription uses ``make_transcriber`` which never auto-selects a cloud STT;
  * summarization is pinned to the LOCAL Ollama provider directly — a real
    transcript is never sent to GMI Cloud regardless of ``LLM_PROVIDER``, until
    the operator explicitly changes this flow.

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
from .llm import OllamaProvider
from .tenancy import validate_tenant_id
from .transcription import make_transcriber

log = logging.getLogger("recordings")

_SUMMARY_SYSTEM = (
    "You are an expert AI meeting assistant and technical note-taker. Your task is "
    "to analyze the provided raw transcription and extract structured, actionable "
    "insights.\n\n"
    "Analyze the text and return a strictly valid JSON object containing the "
    "following keys:\n\n"
    "executive_summary: A concise 2-3 sentence overview of the main purpose and "
    "outcome of the discussion.\n\n"
    "key_discussion_points: An array of strings detailing the major topics "
    "covered.\n\n"
    "decisions_made: An array of strings noting any formal or informal agreements "
    "reached.\n\n"
    "action_items: An array of objects for tasks assigned. Each object must include "
    'assignee (use "Unassigned" if unclear), task_description, and deadline (if '
    "mentioned, otherwise null).\n\n"
    "open_questions: An array of strings highlighting unresolved issues or items "
    "tabled for future discussion.\n\n"
    "Constraint: Output ONLY the raw JSON object. Do not include markdown blocks "
    "(like ```json), conversational preamble, or formatting artifacts."
)

_SUMMARY_TEMPLATE = "Raw transcription:\n\n{transcript}"

_MAX_TRANSCRIPT_CHARS = 12000


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
    def __init__(self, pool, cfg: Config) -> None:
        self.pool = pool
        self.cfg = cfg
        self._task = None
        self._stopping = False
        self._transcriber = None  # lazily built (Whisper model load is heavy)
        self._llm = None
        self._minio = Minio(
            cfg.s3_endpoint, access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key, secure=cfg.s3_use_ssl,
        )

    async def start(self) -> None:
        self._stopping = False

        async def _loop() -> None:
            while not self._stopping:
                try:
                    await self.run_once()
                except Exception:  # noqa: BLE001 — a bad tenant must not kill the loop
                    log.exception("recordings: processing pass failed")
                await asyncio.sleep(max(5, self.cfg.recordings_poll_seconds))

        self._task = asyncio.create_task(_loop())
        log.info("recording processor started (poll=%ss, whisper=%s, summary=local Ollama)",
                 self.cfg.recordings_poll_seconds, self.cfg.whisper_model)

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
                "SELECT id::text AS id, object_key, filename, mime_type "
                "FROM meeting_recordings WHERE status = 'transcribing' ORDER BY created_at LIMIT 5")
            # Safety net: a recording whose browser uploaded the audio but never
            # confirmed via POST /uploaded is stuck in 'recording'. After a grace
            # window (so we don't race a still-in-progress upload) pick it up too,
            # but only once the audio is actually present in storage.
            stuck = await conn.fetch(
                "SELECT id::text AS id, object_key, filename, mime_type "
                "FROM meeting_recordings WHERE status = 'recording' "
                "AND created_at < now() - interval '2 minutes' ORDER BY created_at LIMIT 5")
        handled = 0
        for rec in pending:
            await self._process_one(tenant_id, rec["id"], rec["object_key"], rec["filename"], rec["mime_type"])
            handled += 1
        for rec in stuck:
            if not await self._object_exists(rec["object_key"]):
                continue  # still recording, or audio never landed — leave as-is
            log.info("recovering stuck recording %s (uploaded but not confirmed)", rec["id"])
            await self._update(tenant_id, rec["id"], status="transcribing")
            await self._process_one(tenant_id, rec["id"], rec["object_key"], rec["filename"], rec["mime_type"])
            handled += 1
        return handled

    async def _process_one(self, tenant_id: str, rec_id: str, object_key: str,
                           filename: str, mime_type: str) -> None:
        try:
            audio = await self._fetch_object(tenant_id, object_key)
            if not self._transcriber:
                self._transcriber = make_transcriber(self.cfg)
            result = await self._transcriber.transcribe(audio, filename or "audio", mime_type or "")
            transcript = (result.text or "").strip()

            await self._update(tenant_id, rec_id,
                               status="summarizing", transcript_text=transcript)

            summary, err = await self._summarize(transcript)
            await self._update(tenant_id, rec_id, status="complete",
                               summary_text=summary, error=err)
            log.info("recording %s transcribed (%d chars) + summarized", rec_id, len(transcript))
        except Exception as exc:  # noqa: BLE001
            log.exception("recording %s failed", rec_id)
            await self._update(tenant_id, rec_id, status="failed", error=str(exc)[:500])

    async def _summarize(self, transcript: str) -> tuple[str, str]:
        """Extract structured meeting insights (JSON) with the LOCAL provider only.
        Best-effort: if the local LLM is unavailable we still deliver the
        transcript (empty summary + note). The stored summary is a JSON object
        (see ``_SUMMARY_SYSTEM``); non-JSON responses are passed through and the
        UI/email formatter render them verbatim."""
        if not transcript:
            return "", "empty transcript"
        try:
            if not self._llm:
                self._llm = OllamaProvider(self.cfg)  # hard local pin — never GMI
            clipped = transcript[:_MAX_TRANSCRIPT_CHARS]
            prompt = _SUMMARY_TEMPLATE.format(transcript=clipped)
            summary = await self._llm.complete(_SUMMARY_SYSTEM, prompt, max_tokens=2000)
            return _extract_json(summary or ""), ""
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
