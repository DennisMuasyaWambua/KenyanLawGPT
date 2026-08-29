"""Tenant-private document ingestion (the gRPC IngestDocument path).

Fetch from tenant-prefixed object storage -> parse -> chunk -> embed into the
tenant schema's archive_chunks -> upsert tenant graph nodes (through
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
from ..transcription import TranscriptionProvider, is_audio, make_transcriber
from .extraction import ExtractedEntities, classify_doc_kind, extract_entities


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s[:80] or "unknown"
# NOTE: citation/entity regexes now live in extraction.py (single source).


class TenantIngestor:
    def __init__(self, pool: asyncpg.Pool, graph: Graph, embedder: EmbeddingProvider, cfg: Config,
                 transcriber: Optional[TranscriptionProvider] = None) -> None:
        self.pool = pool
        self.graph = graph
        self.embedder = embedder
        self.cfg = cfg
        # Audio documents (client-conversation recordings) are transcribed to
        # text before the normal chunk/embed/graph pipeline runs.
        self.transcriber = transcriber or make_transcriber(cfg)
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
        archive_id: str,
        object_key: str,
        filename: str,
        mime_type: str,
        file_id: Optional[str] = None,
    ) -> AsyncIterator[tuple[str, str, int]]:
        """Yields (stage, message, progress_pct); raises on failure."""
        yield ("FETCHING", f"fetching {object_key}", 10)
        raw = await self._fetch_object(tenant_id, object_key)

        if is_audio(filename, mime_type):
            # Client-conversation recording: transcribe (multilingual) so the
            # spoken content becomes citable, per-case context for the AI.
            yield ("PARSING", f"transcribing {filename} ({len(raw)} bytes)", 25)
            result = await self.transcriber.transcribe(raw, filename, mime_type)
            text = result.text
            log().info("transcribed %s via %s (lang=%s, %d chars)",
                       filename, result.provider, result.language, len(text))
            if not text.strip():
                raise ValueError("transcription produced no text")
        else:
            yield ("PARSING", f"parsing {filename} ({len(raw)} bytes)", 25)
            text = self._extract_text(raw, mime_type, filename)
            if not text.strip():
                raise ValueError("document contains no extractable text")

        yield ("CHUNKING", "chunking", 40)
        chunks = chunk_text(text)

        yield ("EMBEDDING", f"embedding {len(chunks)} chunk(s)", 60)
        embeddings = await self.embedder.embed(chunks)
        async with dbx.tenant_tx(self.pool, tenant_id) as conn:
            await dbx.delete_chunks(conn, [archive_id])  # idempotent re-ingest
            await dbx.insert_chunks(conn, archive_id, chunks, embeddings,
                                    metadata={"filename": filename})

        yield ("GRAPHING", "updating tenant knowledge graph", 80)
        entities = extract_entities(text, filename)
        await self._graph_upsert(tenant_id, archive_id, filename, file_id, entities)

        doc_kind = classify_doc_kind(filename, text)
        if doc_kind in ("submission", "ruling"):
            yield ("GRAPHING", "linking advocate / file / judge / outcome", 90)
            await self._graph_upsert_submission(
                tenant_id, archive_id, filename, file_id, entities)

        yield ("DONE", f"ingested {len(chunks)} chunk(s) [{doc_kind}]", 100)

    async def _graph_upsert(self, tenant_id: str, archive_id: str, filename: str,
                            file_id: Optional[str], entities: ExtractedEntities) -> None:
        q = (TenantScopedGraphQuery(tenant_id)
             .merge_node("d", "Archive", {"id": archive_id}, {"filename": filename})
             .build())
        await self.graph.write(q)

        if file_id:
            q = (TenantScopedGraphQuery(tenant_id)
                 .merge_node("m", "File", {"id": file_id})
                 .merge_node("d", "Archive", {"id": archive_id})
                 .merge_rel("m", "LINKED_TO", "d")
                 .build())
            await self.graph.write(q)

        # Cross-partition CITES edges: tenant Archive -> public authority.
        await self._link_citations(tenant_id, "d", "Archive", archive_id, entities)

    async def _link_citations(self, tenant_id: str, alias: str, label: str,
                              node_id: str, entities: ExtractedEntities) -> None:
        """MERGE CITES edges from a tenant node (Archive or Submission) to the
        public authorities it references. Public nodes are only ever matched,
        never written, from tenant scope."""
        for needle in entities.act_citations + entities.case_citations:
            rows = await dbx.find_public_docs_by_title(self.pool, needle, limit=1)
            for r in rows:
                public_label = "Statute" if r["doc_type"] in ("statute", "constitution") else "CaseLaw"
                q = (TenantScopedGraphQuery(tenant_id)
                     .merge_node(alias, label, {"id": node_id})
                     .match_public("s", public_label, doc_id=r["doc_id"])
                     .merge_rel(alias, "CITES", "s")
                     .build())
                try:
                    await self.graph.write(q)
                except Exception as exc:
                    log().warning("cites edge failed for %s: %s", r["doc_id"], exc)

    async def _graph_upsert_submission(self, tenant_id: str, archive_id: str, filename: str,
                                       file_id: Optional[str], entities: ExtractedEntities) -> None:
        """Build the judge-reasoning subgraph for a court filing:

            (Advocate)-[:AUTHORED]->(Submission)-[:FILED_IN]->(File)
            (File)-[:DECIDED_BY]->(Judge:Public)   # best-effort, if judge known publicly
            (File)-[:RESULTED_IN]->(Outcome)
            (Submission)-[:CITES]->(Statute|CaseLaw:Public)

        Everything except the public Judge/Statute/CaseLaw nodes carries
        tenant_id via TenantScopedGraphQuery. The judge name is also stored as a
        property on File/Outcome so judge-aware retrieval works even before
        that judge appears in the public corpus.
        """
        submission_props = {"filename": filename}
        if entities.parties:
            submission_props["parties"] = entities.parties
        if entities.case_ref:
            submission_props["case_ref"] = entities.case_ref
        q = (TenantScopedGraphQuery(tenant_id)
             .merge_node("s", "Submission", {"id": archive_id}, submission_props)
             .build())
        await self.graph.write(q)

        for advocate in entities.advocates:
            q = (TenantScopedGraphQuery(tenant_id)
                 .merge_node("a", "Advocate", {"id": _slug(advocate)}, {"name": advocate})
                 .merge_node("s", "Submission", {"id": archive_id})
                 .merge_rel("a", "AUTHORED", "s")
                 .build())
            await self.graph.write(q)

        # Resolve the case/file: explicit file_id wins, else derive a stable
        # key from the case reference so repeat filings land on the same File.
        file_key = file_id or (_slug(entities.case_ref) if entities.case_ref else None)
        if file_key:
            file_props: dict = {}
            if entities.case_ref:
                file_props["case_ref"] = entities.case_ref
            if entities.judge_name:
                file_props["judge_name"] = entities.judge_name
            q = (TenantScopedGraphQuery(tenant_id)
                 .merge_node("m", "File", {"id": file_key}, file_props or None)
                 .merge_node("s", "Submission", {"id": archive_id})
                 .merge_rel("s", "FILED_IN", "m")
                 .build())
            await self.graph.write(q)

            # Best-effort DECIDED_BY to the public Judge (only links if present).
            if entities.judge_name:
                try:
                    q = (TenantScopedGraphQuery(tenant_id)
                         .merge_node("m", "File", {"id": file_key})
                         .match_public("j", "Judge", name=entities.judge_name)
                         .merge_rel("m", "DECIDED_BY", "j")
                         .build())
                    await self.graph.write(q)
                except Exception as exc:
                    log().info("DECIDED_BY skipped (judge %r not in public graph): %s",
                               entities.judge_name, exc)

            if entities.outcome:
                oc = entities.outcome
                q = (TenantScopedGraphQuery(tenant_id)
                     .merge_node("o", "Outcome", {"id": f"{file_key}:outcome"}, {
                         "result": oc.get("result", ""),
                         "date": oc.get("date", ""),
                         "notes": oc.get("notes", ""),
                         "judge_name": entities.judge_name or "",
                     })
                     .merge_node("m", "File", {"id": file_key})
                     .merge_rel("m", "RESULTED_IN", "o")
                     .build())
                await self.graph.write(q)

        # The Section/Case law the submission cited (for "what wins" reasoning).
        await self._link_citations(tenant_id, "s", "Submission", archive_id, entities)

    # --- KDPA erasure cascade (graph + vectors) ---
    async def erase_subject(self, tenant_id: str, subject_type: str, subject_id: str,
                            archive_ids: list[str]) -> tuple[int, int]:
        vector_rows = 0
        if archive_ids:
            async with dbx.tenant_tx(self.pool, tenant_id) as conn:
                vector_rows = await dbx.delete_chunks(conn, archive_ids)

        nodes_deleted = 0
        if archive_ids:
            q = (TenantScopedGraphQuery(tenant_id)
                 .match("d", "Archive")
                 .where_in("d", "id", archive_ids)
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
