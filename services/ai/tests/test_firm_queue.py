"""Async firm-ingestion queue: in-process fallback drains jobs and tracks
status without Redis or live DBs (Task 3)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.firm_queue import FirmIngestQueue, IngestJob

TENANT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


class FakeIngestor:
    """Stands in for TenantIngestor.ingest — yields the progress stages."""
    def __init__(self):
        self.seen = []

    async def ingest(self, tenant_id, document_id, object_key, filename, mime_type, matter_id=None):
        self.seen.append((tenant_id, document_id))
        yield ("FETCHING", "fetching", 10)
        yield ("EMBEDDING", "embedding", 60)
        yield ("DONE", "done", 100)


@pytest.mark.asyncio
async def test_in_process_queue_drains_and_reports_done():
    cfg = SimpleNamespace(redis_url="")  # force in-process backend
    ing = FakeIngestor()
    q = FirmIngestQueue(ing, cfg, concurrency=1)
    await q.start()
    try:
        assert q._redis is None  # confirm in-process fallback
        await q.enqueue(IngestJob(TENANT, "doc-1", f"tenants/{TENANT}/documents/doc-1", "s.pdf", "application/pdf"))
        for _ in range(50):
            status = await q.get_status("doc-1")
            if status and status["done"]:
                break
            await asyncio.sleep(0.05)
        status = await q.get_status("doc-1")
        assert status is not None and status["done"] and status["stage"] == "DONE"
        assert ing.seen == [(TENANT, "doc-1")]
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_enqueue_rejects_invalid_tenant():
    from app.tenancy import TenantValidationError

    q = FirmIngestQueue(FakeIngestor(), SimpleNamespace(redis_url=""), concurrency=1)
    await q.start()
    try:
        with pytest.raises(TenantValidationError):
            await q.enqueue(IngestJob("not-a-uuid", "doc-x", "k", "f.pdf", "application/pdf"))
    finally:
        await q.stop()
