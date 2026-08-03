"""Retrieval orchestrator: intent classification -> hybrid retrieval
(pgvector + knowledge graph, public + tenant partitions) -> merge/re-rank ->
provenance tagging -> cited answer synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import asyncpg

from . import db as dbx
from .config import Config
from .embeddings import EmbeddingProvider
from .graph import Graph, PublicGraphQuery, TenantScopedGraphQuery
from .llm import CONFIDENTIALITY_PREAMBLE, LLMProvider
from .logging_setup import log

INTENTS = ("statute_lookup", "case_law_research", "matter_reasoning", "drafting")


@dataclass
class RankedChunk:
    chunk_id: str
    text: str
    score: float
    source_type: str  # "PUBLIC" | "TENANT_PRIVATE"
    source_id: str
    citation: str = ""
    source_url: str = ""
    status: str = "current"
    court: str = ""
    year: int = 0
    metadata: dict = field(default_factory=dict)


class RetrievalOrchestrator:
    def __init__(self, pool: asyncpg.Pool, graph: Graph, embedder: EmbeddingProvider,
                 llm: LLMProvider, cfg: Config) -> None:
        self.pool = pool
        self.graph = graph
        self.embedder = embedder
        self.llm = llm
        self.cfg = cfg

    # -- 1. intent -----------------------------------------------------------
    async def classify_intent(self, query: str) -> str:
        q = query.lower()
        # Cheap heuristic first; LLM (fast model) refines ambiguous cases.
        if any(w in q for w in ("draft", "prepare a", "write a letter", "write an agreement")):
            return "drafting"
        heuristic = None
        if any(w in q for w in ("our client", "this matter", "our matter", "my case", "our case")):
            heuristic = "matter_reasoning"
        elif any(w in q for w in ("held", "ruling", "judgment", "precedent", "case law", "decided", "court of appeal", "supreme court")):
            heuristic = "case_law_research"
        elif any(w in q for w in ("act", "section", "article", "constitution", "regulation", "statute")):
            heuristic = "statute_lookup"
        if heuristic:
            return heuristic
        try:
            answer = await self.llm.complete(
                system="You classify Kenyan legal research queries. Reply with exactly one of: "
                       "statute_lookup, case_law_research, matter_reasoning, drafting.",
                prompt=query, max_tokens=16, fast=True,
            )
            label = answer.strip().lower()
            if label in INTENTS:
                return label
        except Exception as exc:  # classification must never break retrieval
            log().warning("intent classification failed: %s", exc)
        return "case_law_research"

    # -- 2+3. hybrid retrieval + merge/re-rank --------------------------------
    async def retrieve(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 12,
        include_superseded: bool = False,
        matter_id: Optional[str] = None,
    ) -> tuple[list[RankedChunk], str]:
        intent = await self.classify_intent(query)
        [qvec] = await self.embedder.embed([query])

        fetch_n = max(top_k, 8)
        public_rows = await dbx.search_public_chunks(self.pool, qvec, fetch_n, include_superseded)
        async with dbx.tenant_tx(self.pool, tenant_id) as conn:
            tenant_rows = await dbx.search_tenant_chunks(conn, qvec, fetch_n)

        # Graph expansion: docs connected to the anchor matter get boosted, and
        # status edges on retrieved public docs surface "overturned by X" facts.
        matter_doc_ids: set[str] = set()
        if matter_id:
            matter_doc_ids = await self._matter_document_ids(tenant_id, matter_id)
        status_notes = await self._status_annotations([r["doc_id"] for r in public_rows])

        chunks: list[RankedChunk] = []
        for r in public_rows:
            status = r.get("status") or "current"
            score = float(r["score"])
            score *= 1.0 if status == "current" else (1.0 if include_superseded else 0.45)
            if intent == "statute_lookup" and r.get("doc_type") == "statute":
                score *= 1.15
            if intent == "case_law_research" and r.get("doc_type") in ("case_law", "judgment"):
                score *= 1.12
            note = status_notes.get(r["doc_id"], "")
            text = r["chunk_text"] + (f"\n[NOTE: {note}]" if note else "")
            chunks.append(RankedChunk(
                chunk_id=str(r["chunk_id"]), text=text, score=score,
                source_type="PUBLIC", source_id=r["doc_id"],
                citation=r.get("citation") or r.get("title") or "",
                source_url=r.get("source_url") or "", status=status,
                court=r.get("court") or "", year=int(r.get("year") or 0),
                metadata={"title": r.get("title") or "", "doc_type": r.get("doc_type") or ""},
            ))
        for r in tenant_rows:
            score = float(r["score"])
            if intent == "matter_reasoning":
                score *= 1.2
            if r["document_id"] in matter_doc_ids:
                score *= 1.25
            chunks.append(RankedChunk(
                chunk_id=str(r["chunk_id"]), text=r["chunk_text"], score=score,
                source_type="TENANT_PRIVATE", source_id=r["document_id"],
                citation=r.get("filename") or "internal document",
                metadata={"doc_kind": r.get("doc_kind") or ""},
            ))

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k], intent

    async def _matter_document_ids(self, tenant_id: str, matter_id: str) -> set[str]:
        try:
            q = (TenantScopedGraphQuery(tenant_id)
                 .match("m", "Matter", id=matter_id)
                 .match_rel("m", ["LINKED_TO", "CITES", "INVOLVES"], "d", "Document")
                 .returns("d.id AS doc_id").limit(100).build())
            rows = await self.graph.read(q)
            return {r["doc_id"] for r in rows if r.get("doc_id")}
        except Exception as exc:
            log().warning("matter graph expansion failed: %s", exc)
            return set()

    async def _status_annotations(self, doc_ids: list[str]) -> dict[str, str]:
        """For each retrieved public doc, check AMENDS/OVERTURNS/DISTINGUISHES
        edges so stale law is flagged instead of silently served."""
        notes: dict[str, str] = {}
        if not doc_ids:
            return notes
        try:
            for label in ("Statute", "CaseLaw"):
                q = (PublicGraphQuery()
                     .match("old", label)
                     .where_in("old", "doc_id", doc_ids)
                     .match_rel("old", ["AMENDS", "OVERTURNS", "DISTINGUISHES", "SUPERSEDED_BY"],
                                "new", label, direction="any")
                     .returns("old.doc_id AS old_id", "new.title AS new_title", "new.doc_id AS new_id")
                     .limit(50).build())
                for r in await self.graph.read(q):
                    if r.get("old_id") and r.get("new_title"):
                        notes[r["old_id"]] = f"related version/treatment: {r['new_title']} ({r.get('new_id','')})"
        except Exception as exc:
            log().warning("status annotation lookup failed: %s", exc)
        return notes

    # -- 4. answer synthesis ---------------------------------------------------
    async def answer(self, query: str, chunks: list[RankedChunk], intent: str) -> str:
        if not chunks:
            return ("No relevant sources found in the corpus yet. If this deployment is fresh, "
                    "run the public-corpus ingestion (it runs automatically at startup) or "
                    "ingest firm documents first.")
        ctx_lines = []
        for i, c in enumerate(chunks, 1):
            label = c.source_type
            cite = c.citation or c.source_id
            status = f", status={c.status}" if c.status != "current" else ""
            ctx_lines.append(f"[{i}] ({label}{status}) {cite}\n{c.text}")
        prompt = (
            f"Question from a Kenyan advocate: {query}\n\n"
            f"Query intent: {intent}\n\n"
            "--- CONTEXT ---\n" + "\n\n".join(ctx_lines) + "\n--- END CONTEXT ---\n\n"
            "Answer the question for a Kenyan legal audience. Cite sources inline as [n] "
            "matching the context numbering. If a source is marked superseded/overturned, "
            "say so explicitly rather than presenting it as current law. If the context is "
            "insufficient, say what is missing."
        )
        system = (
            "You are WakiliAI, a legal research assistant for Kenyan law firms. "
            "You are not a substitute for an advocate's own judgment. "
            + CONFIDENTIALITY_PREAMBLE
        )
        return await self.llm.complete(system=system, prompt=prompt, max_tokens=2048)
