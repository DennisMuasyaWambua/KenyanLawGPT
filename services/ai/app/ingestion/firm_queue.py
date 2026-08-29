"""Async job queue for tenant document ingestion.

Firm uploads must not block the API on parsing/embedding large batches, so the
gRPC handler only *enqueues*; a pool of background workers drains the queue and
runs the ingestion, publishing per-document status that the handler (or a later
status endpoint) tails.

Backend selection:
  * Redis (``REDIS_URL`` set and reachable) — multi-instance safe.
  * In-process ``asyncio.Queue`` fallback — single-instance dev/test, no Redis
    required, so the offline suite and ``make up`` both work.

Isolation note: a job is only ever enqueued after ``validate_tenant_id``; the
worker passes that same tenant id straight into ``TenantIngestor`` (which scopes
every write), so a queued job can never touch another tenant's partition.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Optional

from ..config import Config
from ..logging_setup import log
from ..tenancy import validate_tenant_id

QUEUE_KEY = "wakili:firm_ingest:queue"
STATUS_KEY = "wakili:firm_ingest:status:"  # + archive_id
STATUS_TTL_SECONDS = 24 * 3600


@dataclass
class IngestJob:
    tenant_id: str
    archive_id: str
    object_key: str
    filename: str
    mime_type: str
    file_id: Optional[str] = None
    trace_id: str = ""


class FirmIngestQueue:
    def __init__(self, ingestor, cfg: Config, concurrency: int = 2) -> None:
        self.ingestor = ingestor
        self.cfg = cfg
        self.concurrency = concurrency
        self._redis = None
        self._mem_queue: Optional[asyncio.Queue] = None
        self._mem_status: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        self._redis = await self._connect_redis()
        if self._redis is None:
            self._mem_queue = asyncio.Queue()
        self._stopping = False
        for _ in range(self.concurrency):
            self._tasks.append(asyncio.create_task(self._worker()))
        log().info("firm ingest queue started (%s backend, concurrency=%d)",
                   "redis" if self._redis else "in-process", self.concurrency)

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def _connect_redis(self):
        if not getattr(self.cfg, "redis_url", ""):
            return None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.cfg.redis_url, decode_responses=True)
            await client.ping()
            return client
        except Exception as exc:
            log().warning("redis unavailable (%s) — firm ingest using in-process queue", exc)
            return None

    # -- producer -----------------------------------------------------------
    async def enqueue(self, job: IngestJob) -> None:
        validate_tenant_id(job.tenant_id)  # defense in depth: never queue a bad tenant
        await self._set_status(job.archive_id, "QUEUED", "queued for ingestion", 0, False, "")
        payload = json.dumps(asdict(job))
        if self._redis is not None:
            await self._redis.rpush(QUEUE_KEY, payload)
        else:
            assert self._mem_queue is not None
            await self._mem_queue.put(payload)

    # -- consumer -----------------------------------------------------------
    async def _worker(self) -> None:
        while not self._stopping:
            try:
                payload = await self._dequeue()
                if payload is None:
                    continue
                job = IngestJob(**json.loads(payload))
                await self._run_job(job)
            except asyncio.CancelledError:
                break
            except Exception:
                log().exception("firm ingest worker loop error")

    async def _dequeue(self) -> Optional[str]:
        if self._redis is not None:
            res = await self._redis.blpop(QUEUE_KEY, timeout=1)
            return res[1] if res else None
        assert self._mem_queue is not None
        try:
            return await asyncio.wait_for(self._mem_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    async def _run_job(self, job: IngestJob) -> None:
        try:
            async for stage, message, pct in self.ingestor.ingest(
                job.tenant_id, job.archive_id, job.object_key,
                job.filename, job.mime_type, job.file_id or None,
            ):
                await self._set_status(job.archive_id, stage, message, pct, stage == "DONE", "")
        except Exception as exc:
            log().exception("firm ingestion failed for document %s", job.archive_id)
            await self._set_status(job.archive_id, "FAILED", "ingestion failed", 0, True, str(exc))

    # -- status -------------------------------------------------------------
    async def _set_status(self, archive_id: str, stage: str, message: str,
                          pct: int, done: bool, error: str) -> None:
        status = {"stage": stage, "message": message, "progress_pct": pct,
                  "done": done, "error": error}
        if self._redis is not None:
            await self._redis.set(STATUS_KEY + archive_id, json.dumps(status), ex=STATUS_TTL_SECONDS)
        else:
            self._mem_status[archive_id] = status

    async def get_status(self, archive_id: str) -> Optional[dict]:
        if self._redis is not None:
            raw = await self._redis.get(STATUS_KEY + archive_id)
            return json.loads(raw) if raw else None
        return self._mem_status.get(archive_id)
