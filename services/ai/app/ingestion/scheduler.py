"""Standing scheduler for the self-updating corpus: daily bucket (gazette,
cause lists) and weekly bucket (constitution, legislation, case law, LSK).
Intervals are env-tunable so demos can tighten them.
"""
from __future__ import annotations

import asyncio

from ..config import Config
from ..logging_setup import log
from .pipeline import IngestionPipeline
from .registry import crawlers_for_schedule


class IngestionScheduler:
    def __init__(self, pipeline: IngestionPipeline, cfg: Config) -> None:
        self.pipeline = pipeline
        self.cfg = cfg
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        if self.cfg.ingest_on_start:
            try:
                await self.pipeline.run()  # initial full pass populates fresh deployments
            except Exception:
                log().exception("initial corpus ingestion failed")
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
            except Exception:
                log().exception("scheduled ingestion (%s) failed", schedule)
