"""Public-corpus ingestion pipeline (internal batch path — NOT exposed over
gRPC). Change detection by content hash; amended/overturned law is never
silently overwritten: prior versions are renamed to ``<doc_id>@v<n>``, marked
with a status, and linked to the new node with explicit AMENDS / OVERTURNS /
DISTINGUISHES / SUPERSEDED_BY edges.
"""
from __future__ import annotations

import json
from typing import Optional

import asyncpg
import httpx

from ..chunking import chunk_text
from ..config import Config
from ..db import vec_literal
from ..embeddings import EmbeddingProvider
from ..graph.client import Graph
from ..logging_setup import log
from .models import LegalDocument, RunReport
from .registry import BaseCrawler, all_crawlers
from . import crawlers as _crawlers  # noqa: F401  (import registers the crawlers)

_LABELS = {
    "constitution": "Statute",
    "statute": "Statute",
    "case_law": "CaseLaw",
    "judgment": "Judgment",
    "gazette": "GazetteNotice",
    "guideline": "Guideline",
    "cause_list": "CauseList",
    "bill": "Bill",
    "treaty": "Treaty",
    "tribunal": "TribunalDecision",
}

_STATUS_FOR_REL = {"AMENDS": "amended", "OVERTURNS": "overturned",
                   "DISTINGUISHES": "distinguished", "SUPERSEDED_BY": "superseded"}


class PublicCorpusWriter:
    """The ONLY component allowed to write to the public law graph. It lives
    in the batch pipeline; request-path modules import the read-only
    PublicGraphQuery instead."""

    def __init__(self, graph: Graph) -> None:
        self._graph = graph

    async def upsert_document(self, doc: LegalDocument) -> None:
        label = _LABELS.get(doc.doc_type, "Statute")
        await self._graph._run_internal(
            f"""MERGE (d:{label}:Public {{doc_id: $doc_id}})
                SET d.title = $title, d.status = $status, d.version = $version,
                    d.citation = $citation, d.court = $court, d.year = $year,
                    d.source_url = $source_url, d.doc_type = $doc_type""",
            {"doc_id": doc.doc_id, "title": doc.title, "status": doc.status,
             "version": doc.version, "citation": doc.citation, "court": doc.court,
             "year": doc.year, "source_url": doc.source_url, "doc_type": doc.doc_type},
        )
        # Bench composition + per-judge opinions as first-class nodes.
        for judge in doc.authored_by:
            await self._graph._run_internal(
                f"""MATCH (d:{label}:Public {{doc_id: $doc_id}})
                    MERGE (j:Judge:Public {{name: $judge}})
                    MERGE (j)-[:AUTHORED]->(d)""",
                {"doc_id": doc.doc_id, "judge": judge},
            )
        for i, op in enumerate(doc.opinions):
            op_id = f"{doc.doc_id}#opinion-{i}-{op.kind}"
            await self._graph._run_internal(
                f"""MATCH (d:{label}:Public {{doc_id: $doc_id}})
                    MERGE (o:Opinion:Public {{doc_id: $op_id}})
                    SET o.kind = $kind, o.judge = $judge, o.title = $title,
                        o.status = d.status, o.doc_type = 'opinion'
                    MERGE (o)-[:PART_OF]->(d)
                    MERGE (j:Judge:Public {{name: $judge}})
                    MERGE (j)-[:AUTHORED]->(o)""",
                {"doc_id": doc.doc_id, "op_id": op_id, "kind": op.kind,
                 "judge": op.judge, "title": f"{op.kind.title()} opinion of {op.judge} in {doc.title}"},
            )

    async def link(self, src_doc_id: str, rel_type: str, dst_doc_id: str) -> None:
        if rel_type not in ("AMENDS", "OVERTURNS", "DISTINGUISHES", "CITES",
                            "INTERPRETS", "SUPERSEDED_BY"):
            raise ValueError(f"relation {rel_type} not allowed on public graph")
        await self._graph._run_internal(
            f"""MATCH (a:Public {{doc_id: $src}}), (b:Public {{doc_id: $dst}})
                MERGE (a)-[:{rel_type}]->(b)""",
            {"src": src_doc_id, "dst": dst_doc_id},
        )

    async def set_status(self, doc_id: str, status: str) -> None:
        await self._graph._run_internal(
            "MATCH (d:Public {doc_id: $doc_id}) SET d.status = $status",
            {"doc_id": doc_id, "status": status},
        )

    async def rename(self, old_doc_id: str, new_doc_id: str) -> None:
        await self._graph._run_internal(
            "MATCH (d:Public {doc_id: $old}) SET d.doc_id = $new",
            {"old": old_doc_id, "new": new_doc_id},
        )


class IngestionPipeline:
    def __init__(self, pool: asyncpg.Pool, graph: Graph, embedder: EmbeddingProvider, cfg: Config) -> None:
        self.pool = pool
        self.writer = PublicCorpusWriter(graph)
        self.embedder = embedder
        self.cfg = cfg

    async def run(self, source_types: Optional[list[str]] = None) -> list[RunReport]:
        reports: list[RunReport] = []
        registry = all_crawlers()
        names = source_types or list(registry)
        async with httpx.AsyncClient(headers={"User-Agent": "WakiliAI-ingest/1.0"}) as http:
            for name in names:
                crawler_cls = registry.get(name)
                if crawler_cls is None:
                    continue
                crawler = crawler_cls(self.cfg)
                report = RunReport(source_type=name)
                docs: list[LegalDocument] = []
                if self.cfg.ingest_offline_samples:
                    docs = crawler.samples()
                else:
                    try:
                        async for doc in crawler.fetch(http):
                            docs.append(doc)
                    except Exception as exc:
                        report.errors.append(f"live fetch failed: {exc}")
                        log().warning("crawler %s live fetch failed (%s); using samples", name, exc)
                        docs = crawler.samples()
                for doc in docs:
                    try:
                        await self._ingest_doc(doc, report)
                    except Exception as exc:
                        report.errors.append(f"{doc.doc_id}: {exc}")
                        log().exception("ingest failed for %s", doc.doc_id)
                await self._record_run(report)
                reports.append(report)
        return reports

    async def _ingest_doc(self, doc: LegalDocument, report: RunReport) -> None:
        new_hash = doc.content_hash
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content_hash, version, status FROM public.public_documents WHERE doc_id = $1",
                doc.doc_id,
            )
            if row and row["content_hash"] == new_hash:
                report.unchanged_docs += 1
                return

            if row:  # content changed -> version the prior node, never overwrite
                old_version = row["version"]
                archived_id = f"{doc.doc_id}@v{old_version}"
                await conn.execute(
                    """UPDATE public.public_documents
                       SET doc_id = $2, status = 'superseded' WHERE doc_id = $1""",
                    doc.doc_id, archived_id,
                )
                await conn.execute(
                    "UPDATE public.public_vectors SET doc_id = $2 WHERE doc_id = $1",
                    doc.doc_id, archived_id,
                )
                await self.writer.rename(doc.doc_id, archived_id)
                await self.writer.set_status(archived_id, "superseded")
                doc.version = old_version + 1
                report.superseded_docs += 1

            await conn.execute(
                """INSERT INTO public.public_documents
                     (doc_id, title, doc_type, source_url, court, citation, year,
                      status, version, content_hash, authored_by, metadata, full_text)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13)""",
                doc.doc_id, doc.title, doc.doc_type, doc.source_url, doc.court,
                doc.citation, doc.year, doc.status, doc.version, new_hash,
                json.dumps(doc.authored_by), json.dumps(doc.metadata), doc.full_text,
            )

            # Vectors: opinions are embedded as their own chunks so a dissent
            # is retrievable independently of the majority holding.
            texts = chunk_text(doc.full_text)
            metas = [{"kind": "body"}] * len(texts)
            for op in doc.opinions:
                texts.append(f"{op.kind.upper()} opinion of {op.judge} in {doc.title}:\n{op.text}")
                metas.append({"kind": "opinion", "judge": op.judge, "opinion_kind": op.kind})
            if texts:
                embeddings = await self.embedder.embed(texts)
                await conn.executemany(
                    """INSERT INTO public.public_vectors (doc_id, chunk_index, chunk_text, embedding, metadata)
                       VALUES ($1,$2,$3,$4::vector,$5::jsonb)""",
                    [(doc.doc_id, i, t, vec_literal(e), json.dumps(m))
                     for i, (t, e, m) in enumerate(zip(texts, embeddings, metas))],
                )

        # Graph node + explicit treatment edges. The archived prior version
        # gets a SUPERSEDED_BY edge to the new node.
        await self.writer.upsert_document(doc)
        if row:
            archived_id = f"{doc.doc_id}@v{row['version']}"
            await self.writer.link(archived_id, "SUPERSEDED_BY", doc.doc_id)
        for rel in doc.relations:
            try:
                await self.writer.link(doc.doc_id, rel.rel_type, rel.target_doc_id)
                target_status = _STATUS_FOR_REL.get(rel.rel_type)
                if target_status:
                    await self.writer.set_status(rel.target_doc_id, target_status)
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE public.public_documents SET status=$2 WHERE doc_id=$1 AND status='current'",
                            rel.target_doc_id, target_status,
                        )
            except Exception as exc:
                report.errors.append(f"edge {doc.doc_id}-{rel.rel_type}->{rel.target_doc_id}: {exc}")
        report.new_docs += 1

    async def _record_run(self, report: RunReport) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO public.ingestion_runs
                     (source_type, new_docs, amended_docs, superseded_docs, unchanged_docs, errors, finished_at)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb, now())""",
                report.source_type, report.new_docs, report.amended_docs,
                report.superseded_docs, report.unchanged_docs, json.dumps(report.errors),
            )
        log().info(
            "ingestion run: %s new=%d superseded=%d unchanged=%d errors=%d",
            report.source_type, report.new_docs, report.superseded_docs,
            report.unchanged_docs, len(report.errors),
        )
