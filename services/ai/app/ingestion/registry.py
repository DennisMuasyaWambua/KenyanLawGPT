"""Crawler registry: new source types plug in without touching orchestration.

A crawler declares its ``source_type`` and ``schedule`` bucket and yields
normalized :class:`LegalDocument` items. Registration is a decorator, so
adding e.g. a Tribunal-decisions crawler is one new module with @register.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional, Type

import httpx

from ..config import Config
from .models import LegalDocument

_CRAWLERS: dict[str, Type["BaseCrawler"]] = {}


def register(cls: Type["BaseCrawler"]) -> Type["BaseCrawler"]:
    if not cls.source_type:
        raise ValueError("crawler must define source_type")
    _CRAWLERS[cls.source_type] = cls
    return cls


def all_crawlers() -> dict[str, Type["BaseCrawler"]]:
    return dict(_CRAWLERS)


def crawlers_for_schedule(schedule: str) -> list[Type["BaseCrawler"]]:
    return [c for c in _CRAWLERS.values() if c.schedule == schedule]


class BaseCrawler:
    source_type: str = ""
    schedule: str = "weekly"  # "daily" (gazette, cause lists) or "weekly"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        """Fetch live documents from the source. Implementations should yield
        as they parse; the pipeline handles hashing/diffing."""
        raise NotImplementedError
        yield  # pragma: no cover

    def samples(self) -> list[LegalDocument]:
        """Deterministic built-in sample docs, used when the deployment runs
        offline (INGEST_OFFLINE_SAMPLES) or a live fetch fails — keeps demo
        environments populated and tests hermetic."""
        return []
