"""Retrieval orchestrator: intent classification -> hybrid retrieval
(pgvector + knowledge graph, public + tenant partitions) -> merge/re-rank ->
provenance tagging -> cited answer synthesis.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import asyncpg

from . import db as dbx
from .config import Config
from .embeddings import EmbeddingProvider
from .fusion import cap_per_source, rrf_fuse
from .graph import Graph, PublicGraphQuery, TenantScopedGraphQuery
from .judge import JudgeReasoner
from .llm import CONFIDENTIALITY_PREAMBLE, LLMProvider
from .logging_setup import log

INTENTS = ("statute_lookup", "case_law_research", "file_reasoning", "drafting")

MAX_CHUNKS_PER_SOURCE = 3


def _has_word(q: str, words: tuple[str, ...]) -> bool:
    """Whole-word / phrase match. Plain ``in`` made "act" fire on "contract" and
    "fact", and "held" on "withheld", mislabelling intent and skewing scores."""
    return any(re.search(r"\b" + re.escape(w) + r"s?\b", q) for w in words)


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
        self.judge = JudgeReasoner(pool, graph, cfg)

    # -- 1. intent -----------------------------------------------------------
    async def classify_intent(self, query: str) -> str:
        q = query.lower()
        # Cheap heuristic first; LLM (fast model) refines ambiguous cases.
        if _has_word(q, ("draft", "prepare a", "write a letter", "write an agreement")):
            return "drafting"
        heuristic = None
        if _has_word(q, ("our client", "this file", "our file", "my case", "our case")):
            heuristic = "file_reasoning"
        elif _has_word(q, ("held", "ruling", "judgment", "precedent", "case law", "decided", "court of appeal", "supreme court")):
            heuristic = "case_law_research"
        elif _has_word(q, ("act", "section", "article", "constitution", "regulation", "statute")):
            heuristic = "statute_lookup"
        if heuristic:
            return heuristic
        try:
            answer = await self.llm.complete(
                system="You classify Kenyan legal research queries. Reply with exactly one of: "
                       "statute_lookup, case_law_research, file_reasoning, drafting.",
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
        file_id: Optional[str] = None,
        as_of: Optional[str] = None,
    ) -> tuple[list[RankedChunk], str]:
        # Intent (possibly an LLM call) only re-weights scores at the end, so it
        # runs alongside the embedding and both searches instead of ahead of them.
        intent_task = asyncio.ensure_future(self.classify_intent(query))
        try:
            return await self._retrieve(intent_task, tenant_id, query, top_k,
                                        include_superseded, file_id, as_of)
        finally:
            intent_task.cancel()  # no-op once awaited; stops it on an early error

    async def _retrieve(self, intent_task: asyncio.Future, tenant_id: str, query: str, top_k: int,
                        include_superseded: bool, file_id: Optional[str],
                        as_of: Optional[str]) -> tuple[list[RankedChunk], str]:
        [qvec] = await self.embedder.embed([query])
        fetch_n = max(top_k, 8)

        async def tenant_search() -> list[dict[str, Any]]:
            async with dbx.tenant_tx(self.pool, tenant_id) as conn:
                dense = await dbx.search_tenant_chunks(conn, qvec, fetch_n)
                lexical = await self._lexical(dbx.search_tenant_chunks_lexical(conn, query, fetch_n))
            return rrf_fuse(dense, lexical)

        async def public_search() -> list[dict[str, Any]]:
            dense, lexical = await asyncio.gather(
                dbx.search_public_chunks(self.pool, qvec, fetch_n, include_superseded, as_of=as_of),
                self._lexical(dbx.search_public_chunks_lexical(
                    self.pool, query, fetch_n, include_superseded, as_of=as_of)))
            return rrf_fuse(dense, lexical)

        async def file_ids() -> set[str]:
            return await self._file_archive_ids(tenant_id, file_id) if file_id else set()

        # Graph expansion: docs connected to the anchor file get boosted, and
        # status edges on retrieved public docs surface "overturned by X" facts.
        # as_of => period-accurate law (the version in force on that date).
        public_rows, tenant_rows, file_doc_ids = await asyncio.gather(
            public_search(),
            tenant_search(),
            file_ids(),
        )
        status_notes, intent = await asyncio.gather(
            self._status_annotations([r["doc_id"] for r in public_rows]), intent_task)

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
            if intent == "file_reasoning":
                score *= 1.2
            if r["archive_id"] in file_doc_ids:
                score *= 1.25
            chunks.append(RankedChunk(
                chunk_id=str(r["chunk_id"]), text=r["chunk_text"], score=score,
                source_type="TENANT_PRIVATE", source_id=r["archive_id"],
                citation=r.get("filename") or "internal document",
                metadata={"doc_kind": r.get("doc_kind") or ""},
            ))

        chunks.sort(key=lambda c: c.score, reverse=True)
        return cap_per_source(chunks, MAX_CHUNKS_PER_SOURCE, top_k), intent

    @staticmethod
    async def _lexical(coro) -> list[dict[str, Any]]:
        """Lexical search is an enhancement: if the FTS index is missing or the
        query can't be parsed, fall back to dense-only rather than fail."""
        try:
            return await coro
        except Exception as exc:
            log().warning("lexical search failed, using dense only: %s", exc)
            return []

    async def _file_archive_ids(self, tenant_id: str, file_id: str) -> set[str]:
        try:
            q = (TenantScopedGraphQuery(tenant_id)
                 .match("m", "File", id=file_id)
                 .match_rel("m", ["LINKED_TO", "CITES", "INVOLVES"], "d", "Archive")
                 .returns("d.id AS doc_id").limit(100).build())
            rows = await self.graph.read(q)
            return {r["doc_id"] for r in rows if r.get("doc_id")}
        except Exception as exc:
            log().warning("file graph expansion failed: %s", exc)
            return set()

    async def _status_annotations(self, doc_ids: list[str]) -> dict[str, str]:
        """For each retrieved public doc, check AMENDS/OVERTURNS/DISTINGUISHES
        edges so stale law is flagged instead of silently served."""
        notes: dict[str, str] = {}
        if not doc_ids:
            return notes
        try:
            queries = [(PublicGraphQuery()
                        .match("old", label)
                        .where_in("old", "doc_id", doc_ids)
                        .match_rel("old", ["AMENDS", "OVERTURNS", "DISTINGUISHES", "SUPERSEDED_BY"],
                                   "new", label, direction="any")
                        .returns("old.doc_id AS old_id", "new.title AS new_title", "new.doc_id AS new_id")
                        .limit(50).build())
                       for label in ("Statute", "CaseLaw")]
            for rows in await asyncio.gather(*(self.graph.read(q) for q in queries)):
                for r in rows:
                    if r.get("old_id") and r.get("new_title"):
                        notes[r["old_id"]] = f"related version/treatment: {r['new_title']} ({r.get('new_id','')})"
        except Exception as exc:
            log().warning("status annotation lookup failed: %s", exc)
        return notes

    # -- 4. answer synthesis ---------------------------------------------------
    @staticmethod
    def build_answer_prompt(query: str, chunks: list[RankedChunk], intent: str,
                            judge_context: str = "") -> tuple[str, str]:
        """Assemble the (system, prompt) pair for cited answer synthesis.

        Factored out of ``answer()`` so the exact production prompt can be
        reused verbatim by out-of-band tooling (e.g. the model A/B script)
        without going through ``answer()``'s single bound provider. The prompt
        text is unchanged from the inline version."""
        ctx_lines = []
        for i, c in enumerate(chunks, 1):
            label = c.source_type
            cite = c.citation or c.source_id
            status = f", status={c.status}" if c.status != "current" else ""
            ctx_lines.append(f"[{i}] ({label}{status}) {cite}\n{c.text}")
        judge_block = ""
        if judge_context:
            judge_block = ("\n--- FIRM-INTERNAL HISTORICAL PATTERN (NOT settled law) ---\n"
                           + judge_context + "\n--- END PATTERN ---\n")
        prompt = (
            f"Question from a Kenyan advocate: {query}\n\n"
            f"Query intent: {intent}\n\n"
            "--- CONTEXT ---\n" + "\n\n".join(ctx_lines) + "\n--- END CONTEXT ---\n"
            + judge_block +
            "\nAnswer the question for a Kenyan legal audience. Cite sources inline as [n] "
            "matching the context numbering. If a source is marked superseded/overturned, "
            "say so explicitly rather than presenting it as current law. If the context is "
            "insufficient, say what is missing."
        )
        system = (
            "You are a legal research assistant for a Kenyan law firm. "
            "You are not a substitute for an advocate's own judgment. "
            "Sharply distinguish what the LAW says (from the CONTEXT sources) from "
            "the FIRM-INTERNAL HISTORICAL PATTERN, if present: the latter is this "
            "firm's own prior experience before a judge, not settled law and not a "
            "prediction — never present it as authority. " + CONFIDENTIALITY_PREAMBLE
        )
        return system, prompt

    _NO_SOURCES = ("No relevant sources found in the corpus yet. If this deployment is fresh, "
                   "run the public-corpus ingestion (it runs automatically at startup) or "
                   "ingest firm documents first.")

    async def answer(self, query: str, chunks: list[RankedChunk], intent: str,
                     judge_context: str = "") -> str:
        if not chunks and not judge_context:
            return self._NO_SOURCES
        system, prompt = self.build_answer_prompt(query, chunks, intent, judge_context)
        return await self.llm.complete(system=system, prompt=prompt, max_tokens=2048)

    async def answer_stream(self, tenant_id: str, query: str, chunks: list[RankedChunk],
                            intent: str) -> AsyncIterator[str]:
        """``answer_with_judge`` as a token stream, so the advocate starts reading
        while the model is still writing."""
        judge_context = await self._judge_context(tenant_id, query)
        if not chunks and not judge_context:
            yield self._NO_SOURCES
            return
        system, prompt = self.build_answer_prompt(query, chunks, intent, judge_context)
        async for piece in self.llm.stream(system=system, prompt=prompt, max_tokens=2048):
            yield piece

    async def _judge_context(self, tenant_id: str, query: str,
                             judge_name: Optional[str] = None) -> str:
        """Firm-internal + public pattern summary for a judge named in the query
        (or passed explicitly). Empty string unless ENABLE_JUDGE_REASONING."""
        if not self.cfg.enable_judge_reasoning:
            return ""
        name = judge_name or JudgeReasoner.detect_judge_name(query)
        if not name:
            return ""
        try:
            return await self.judge.context_block(tenant_id, name)
        except Exception as exc:
            log().warning("judge context assembly failed: %s", exc)
            return ""

    async def answer_with_judge(self, tenant_id: str, query: str,
                                chunks: list[RankedChunk], intent: str) -> str:
        """answer(), transparently enriched with judge pattern context when a
        judge is named in the query and the feature flag is on."""
        judge_context = await self._judge_context(tenant_id, query)
        return await self.answer(query, chunks, intent, judge_context)

    async def judge_aware_retrieve(
        self, tenant_id: str, query: str, judge_name: Optional[str] = None,
        top_k: int = 12, include_superseded: bool = False,
        file_id: Optional[str] = None,
    ) -> tuple[list[RankedChunk], str, str]:
        """Hybrid retrieval + judge-aware synthesis. Returns
        (chunks, intent, answer). The judge history is tenant-scoped for the
        firm's own files and public for the shared record; the two are merged
        only in the labelled prompt, never in a cross-tenant query."""
        chunks, intent = await self.retrieve(
            tenant_id, query, top_k=top_k,
            include_superseded=include_superseded, file_id=file_id)
        judge_context = await self._judge_context(tenant_id, query, judge_name)
        answer = await self.answer(query, chunks, intent, judge_context)
        return chunks, intent, answer
