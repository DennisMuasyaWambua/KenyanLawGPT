"""Auto-update watcher for newly gazetted / amended Kenyan law (Task 5).

A scheduled job that, since its last successful run (a watermark), polls the
gazette + legislation sources, classifies each instrument as new / amends /
repeals, and ingests it through the existing pipeline — which versions prior
law (never deletes it), date-stamps repealed provisions, and refreshes the
vector index in the same pass so the graph and embeddings never drift apart.

Optional notification hook (stretch): when an amendment/repeal touches a
document, an event is emitted so firms can later be alerted that a law they
have cited changed. The default notifier only logs a PUBLIC event (doc id +
change) — it does not scan tenant partitions, so nothing crosses tenants.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx

from .. import db as dbx
from ..config import Config
from ..logging_setup import log
from .models import LegalDocument, RunReport
from .pipeline import IngestionPipeline
from .registry import all_crawlers, crawlers_for_schedule

Notifier = Callable[[LegalDocument, str], Awaitable[None]]


def classify_change(doc: LegalDocument, existing_hash: Optional[str]) -> str:
    """new | amends | repeals | unchanged — from the instrument's declared
    relations and whether we've seen this doc_id before."""
    if existing_hash is not None and existing_hash == doc.content_hash:
        return "unchanged"
    rels = {r.rel_type for r in doc.relations}
    if "REPEALS" in rels:
        return "repeals"
    if "AMENDS" in rels or existing_hash is not None:
        return "amends"
    return "new"


async def _default_notifier(doc: LegalDocument, change: str) -> None:
    log().info("auto-update event: %s %s (%s)", change, doc.doc_id, doc.title)


class AutoUpdateWatcher:
    SOURCE = "auto_update"

    def __init__(self, pool, pipeline: IngestionPipeline, cfg: Config,
                 notifier: Optional[Notifier] = None) -> None:
        self.pool = pool
        self.pipeline = pipeline
        self.cfg = cfg
        self.notifier = notifier or _default_notifier
        self._task = None
        self._stopping = False

    def _watched_sources(self) -> list[str]:
        # Where newly gazetted / amended law shows up: the daily bucket
        # (gazette, cause lists) plus the weekly legislation/constitution bucket.
        names: list[str] = []
        for sched in ("daily", "weekly"):
            names += [c.source_type for c in crawlers_for_schedule(sched)]
        return names or list(all_crawlers())

    async def _existing_hash(self, doc_id: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT content_hash FROM public.public_documents WHERE doc_id = $1", doc_id)

    async def _fetch(self, crawler, http: httpx.AsyncClient) -> list[LegalDocument]:
        if self.cfg.ingest_offline_samples:
            return list(crawler.samples())
        docs: list[LegalDocument] = []
        try:
            async for doc in crawler.fetch(http):
                docs.append(doc)
        except Exception as exc:
            log().warning("auto-update live fetch failed (%s); using samples", exc)
            docs = list(crawler.samples())
        return docs

    async def run_once(self, http: Optional[httpx.AsyncClient] = None) -> dict:
        since = await dbx.get_watermark(self.pool, self.SOURCE)
        run_started = datetime.now(timezone.utc)
        summary = {"since": since.isoformat() if since else None,
                   "new": [], "amended": [], "repealed": [], "unchanged": 0, "errors": []}
        registry = all_crawlers()
        owns_http = http is None
        client = http or httpx.AsyncClient(headers={"User-Agent": "WakiliAI-watcher/1.0"})
        try:
            for name in self._watched_sources():
                crawler_cls = registry.get(name)
                if crawler_cls is None:
                    continue
                for doc in await self._fetch(crawler_cls(self.cfg), client):
                    try:
                        change = classify_change(doc, await self._existing_hash(doc.doc_id))
                        if change == "unchanged":
                            summary["unchanged"] += 1
                            continue
                        await self.pipeline._ingest_doc(doc, RunReport(source_type=name))
                        summary[{"new": "new", "amends": "amended", "repeals": "repealed"}[change]].append(doc.doc_id)
                        if change in ("amends", "repeals"):
                            await self.notifier(doc, change)
                    except Exception as exc:
                        summary["errors"].append(f"{doc.doc_id}: {exc}")
                        log().exception("auto-update failed for %s", doc.doc_id)
        finally:
            if owns_http:
                await client.aclose()
        # Advance the watermark only after a completed pass.
        await dbx.set_watermark(self.pool, self.SOURCE, run_started)
        log().info("auto-update run: new=%d amended=%d repealed=%d unchanged=%d errors=%d",
                   len(summary["new"]), len(summary["amended"]), len(summary["repealed"]),
                   summary["unchanged"], len(summary["errors"]))
        return summary

    # -- scheduled loop -----------------------------------------------------
    async def start(self) -> None:
        import asyncio
        self._stopping = False

        async def _loop():
            # Initial pass on boot, then on the daily cadence. stop() cancels
            # the task, which interrupts the sleep immediately.
            while not self._stopping:
                try:
                    await self.run_once()
                except Exception:
                    log().exception("auto-update watcher cycle failed")
                await asyncio.sleep(max(1, self.cfg.ingest_daily_seconds))

        self._task = asyncio.create_task(_loop())
        log().info("auto-update watcher started (cadence %ds)", self.cfg.ingest_daily_seconds)

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (Exception, __import__("asyncio").CancelledError):
                pass
