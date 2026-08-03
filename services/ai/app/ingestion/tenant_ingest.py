"""Tenant-private document ingestion (the gRPC IngestDocument path).

Fetch from tenant-prefixed object storage -> parse -> chunk -> embed into the
tenant schema's document_chunks -> upsert tenant graph nodes (through
TenantScopedGraphQuery only) -> auto-link CITES edges to public statutes and
cases the document mentions.
"""
from __future__ import annotations

import asyncio
import io
import re
from typing import AsyncIterator, Optional

import asyncpg
from minio import Minio

from .. import db as dbx
from ..chunking import chunk_text
from ..config import Config
from ..embeddings import EmbeddingProvider
from ..graph import Graph, TenantScopedGraphQuery
from ..logging_setup import log

# Loose patterns for Kenyan citations worth graph-linking.
_ACT_RE = re.compile(r"\b([A-Z][A-Za-z' ]{2,40} Act)(?:[, ]+(?:No\.? ?\d+ of )?(\d{4}))?", re.M)
_EKLR_RE = re.compile(r"\[(\d{4})\]\s*eKLR")
_CONSTITUTION_RE = re.compile(r"\bArticle\s+\d+\b|\bConstitution of Kenya\b", re.I)


class TenantIngestor:
    def __init__(self, pool: asyncpg.Pool, graph: Graph, embedder: EmbeddingProvider, cfg: Config) -> None:
        self.pool = pool
        self.graph = graph
        self.embedder = embedder
        self.cfg = cfg
        self._minio = Minio(
            cfg.s3_endpoint, access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key, secure=cfg.s3_use_ssl,
        )

    async def _fetch_object(self, tenant_id: str, object_key: str) -> bytes:
        # Isolation guard: this service will only read inside the caller's prefix.
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

    @staticmethod
    def _extract_text(raw: bytes, mime_type: str, filename: str) -> str:
        if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(raw))
                return "\n\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as exc:
                log().warning("pdf extraction failed (%s); falling back to raw decode", exc)
        return raw.decode("utf-8", errors="replace")

    async def ingest(
        self,
        tenant_id: str,
        document_id: str,
        object_key: str,
        filename: str,
        mime_type: str,
        matter_id: Optional[str] = None,
    ) -> AsyncIterator[tuple[str, str, int]]:
        """Yields (stage, message, progress_pct); raises on failure."""
        yield ("FETCHING", f"fetching {object_key}", 10)
        raw = await self._fetch_object(tenant_id, object_key)

        yield ("PARSING", f"parsing {filename} ({len(raw)} bytes)", 25)
        text = self._extract_text(raw, mime_type, filename)
        if not text.strip():
            raise ValueError("document contains no extractable text")

        yield ("CHUNKING", "chunking", 40)
        chunks = chunk_text(text)

        yield ("EMBEDDING", f"embedding {len(chunks)} chunk(s)", 60)
        embeddings = await self.embedder.embed(chunks)
        async with dbx.tenant_tx(self.pool, tenant_id) as conn:
            await dbx.delete_chunks(conn, [document_id])  # idempotent re-ingest
            await dbx.insert_chunks(conn, document_id, chunks, embeddings,
                                    metadata={"filename": filename})

        yield ("GRAPHING", "updating tenant knowledge graph", 80)
        await self._graph_upsert(tenant_id, document_id, filename, matter_id, text)

        yield ("DONE", f"ingested {len(chunks)} chunk(s)", 100)

    async def _graph_upsert(self, tenant_id: str, document_id: str, filename: str,
                            matter_id: Optional[str], text: str) -> None:
        q = (TenantScopedGraphQuery(tenant_id)
             .merge_node("d", "Document", {"id": document_id}, {"filename": filename})
             .build())
        await self.graph.write(q)

        if matter_id:
            q = (TenantScopedGraphQuery(tenant_id)
                 .merge_node("m", "Matter", {"id": matter_id})
                 .merge_node("d", "Document", {"id": document_id})
                 .merge_rel("m", "LINKED_TO", "d")
                 .build())
            await self.graph.write(q)

        # Cross-partition CITES edges: tenant Document -> public authority.
        for needle in self._citation_needles(text):
            rows = await dbx.find_public_docs_by_title(self.pool, needle, limit=1)
            for r in rows:
                q = (TenantScopedGraphQuery(tenant_id)
                     .merge_node("d", "Document", {"id": document_id})
                     .match_public("s", "Statute" if r["doc_type"] in ("statute", "constitution") else "CaseLaw",
                                   doc_id=r["doc_id"])
                     .merge_rel("d", "CITES", "s")
                     .build())
                try:
                    await self.graph.write(q)
                except Exception as exc:
                    log().warning("cites edge failed for %s: %s", r["doc_id"], exc)

    @staticmethod
    def _citation_needles(text: str) -> list[str]:
        needles = {m.group(1).strip() for m in _ACT_RE.finditer(text)}
        if _CONSTITUTION_RE.search(text):
            needles.add("Constitution of Kenya")
        return list(needles)[:8]

    # --- KDPA erasure cascade (graph + vectors) ---
    async def erase_subject(self, tenant_id: str, subject_type: str, subject_id: str,
                            document_ids: list[str]) -> tuple[int, int]:
        vector_rows = 0
        if document_ids:
            async with dbx.tenant_tx(self.pool, tenant_id) as conn:
                vector_rows = await dbx.delete_chunks(conn, document_ids)

        nodes_deleted = 0
        if document_ids:
            q = (TenantScopedGraphQuery(tenant_id)
                 .match("d", "Document")
                 .where_in("d", "id", document_ids)
                 .detach_delete("d")
                 .build())
            counters = await self.graph.write(q)
            nodes_deleted += counters.get("nodes_deleted", 0)
        if subject_type == "client":
            q = (TenantScopedGraphQuery(tenant_id)
                 .match("p", "Party", id=subject_id)
                 .detach_delete("p")
                 .build())
            counters = await self.graph.write(q)
            nodes_deleted += counters.get("nodes_deleted", 0)
        return nodes_deleted, vector_rows
