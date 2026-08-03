"""Standing scheduler for the self-updating corpus: daily bucket (gazette,
cause lists) and weekly bucket (constitution, legislation, case law, LSK).
Intervals are env-tunable so demos can tighten them.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from ..config import Config
from ..logging_setup import log
from .pipeline import IngestionPipeline
from .registry import crawlers_for_schedule


class IngestionScheduler:
    def __init__(self, pipeline: IngestionPipeline, cfg: Config,
                 post_run: Optional[Callable[[], Awaitable[None]]] = None) -> None:
        self.pipeline = pipeline
        self.cfg = cfg
        # Optional hook run after each ingestion pass (e.g. judge-profile
        # recompute) so derived data stays in sync with freshly ingested law.
        self.post_run = post_run
        self._tasks: list[asyncio.Task] = []

    async def _run_post(self) -> None:
        if self.post_run is None:
            return
        try:
            await self.post_run()
        except Exception:
            log().exception("scheduler post_run hook failed")

    async def start(self) -> None:
        if self.cfg.ingest_on_start:
            try:
                await self.pipeline.run()  # initial full pass populates fresh deployments
            except Exception:
                log().exception("initial corpus ingestion failed")
            await self._run_post()
        self._tasks = [
            asyncio.create_task(self._loop("daily", self.cfg.ingest_daily_seconds)),
            asyncio.create_task(self._loop("weekly", self.cfg.ingest_weekly_seconds)),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _loop(self, schedule: str, interval: int) -> None:
        names = [c.source_type for c in crawlers_for_schedule(schedule)]
        if not names:
            return
        while True:
            await asyncio.sleep(interval)
            try:
                await self.pipeline.run(source_types=names)
                await self._run_post()
            except Exception:
                log().exception("scheduled ingestion (%s) failed", schedule)
