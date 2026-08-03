"""Multi-hop graph reasoning across the public law graph and one tenant's
private partition, producing an explainable trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import asyncpg

from . import db as dbx
from .config import Config
from .graph import Graph, PublicGraphQuery, TenantScopedGraphQuery
from .llm import CONFIDENTIALITY_PREAMBLE, LLMProvider
from .logging_setup import log
from .retrieval import RankedChunk, RetrievalOrchestrator


@dataclass
class Step:
    hop: int
    description: str
    node_ids: list[str] = field(default_factory=list)
    edge_types: list[str] = field(default_factory=list)


class ReasoningEngine:
    def __init__(self, pool: asyncpg.Pool, graph: Graph, retriever: RetrievalOrchestrator,
                 llm: LLMProvider, cfg: Config) -> None:
        self.pool = pool
        self.graph = graph
        self.retriever = retriever
        self.llm = llm
        self.cfg = cfg

    async def reason(
        self,
        tenant_id: str,
        query: str,
        max_hops: int = 3,
        matter_id: Optional[str] = None,
        include_superseded: bool = False,
    ) -> tuple[list[Step], list[RankedChunk], str]:
        max_hops = max(1, min(max_hops or 3, 5))
        steps: list[Step] = []

        # Hop 0 — anchor selection: the matter node if given, else the
        # top vector hits become graph anchors.
        chunks, intent = await self.retriever.retrieve(
            tenant_id, query, top_k=8, include_superseded=include_superseded, matter_id=matter_id
        )
        public_anchor_ids = [c.source_id for c in chunks if c.source_type == "PUBLIC"][:4]
        steps.append(Step(
            hop=0,
            description=f"Anchored on intent '{intent}': "
                        + (f"matter {matter_id} and " if matter_id else "")
                        + f"{len(public_anchor_ids)} public source(s) from hybrid retrieval",
            node_ids=([matter_id] if matter_id else []) + public_anchor_ids,
            edge_types=[],
        ))

        # Hop 1 — tenant subgraph around the matter (private partition only,
        # composed through TenantScopedGraphQuery).
        touched_private_docs: list[str] = []
        if matter_id:
            try:
                q = (TenantScopedGraphQuery(tenant_id)
                     .match("m", "Matter", id=matter_id)
                     .expand("m", ["LINKED_TO", "CITES", "INVOLVES", "SIMILAR_TO"], "n", max_hops=2)
                     .returns("n.id AS id", "labels(n) AS labels")
                     .limit(50).build())
                rows = await self.graph.read(q)
                ids = [r["id"] for r in rows if r.get("id")]
                touched_private_docs = ids
                steps.append(Step(
                    hop=1,
                    description=f"Traversed the firm's private graph around the matter: "
                                f"{len(ids)} connected node(s) (documents, parties, precedent notes)",
                    node_ids=ids[:20],
                    edge_types=["LINKED_TO", "CITES", "INVOLVES", "SIMILAR_TO"],
                ))
            except Exception as exc:
                log().warning("tenant traversal failed: %s", exc)

        # Hop 2..n — public-graph expansion from the anchors: citations,
        # interpretations, and the versioning/treatment edges that tell us
        # whether the law is still good.
        frontier = list(public_anchor_ids)
        seen = set(frontier)
        hop_no = 2 if matter_id else 1
        while frontier and hop_no <= max_hops:
            next_frontier: list[str] = []
            found: list[tuple[str, str, str]] = []
            try:
                for label in ("Statute", "CaseLaw", "Judgment"):
                    q = (PublicGraphQuery()
                         .match("a", label)
                         .where_in("a", "doc_id", frontier)
                         .expand("a", ["CITES", "INTERPRETS", "AMENDS", "OVERTURNS",
                                       "DISTINGUISHES", "HAS_OPINION", "AUTHORED", "PART_OF"],
                                 "b", max_hops=1)
                         .returns("a.doc_id AS src", "b.doc_id AS dst", "b.title AS title")
                         .limit(60).build())
                    for r in await self.graph.read(q):
                        dst = r.get("dst")
                        if dst and dst not in seen:
                            seen.add(dst)
                            next_frontier.append(dst)
                            found.append((r.get("src", ""), dst, r.get("title") or ""))
            except Exception as exc:
                log().warning("public traversal failed: %s", exc)
                break
            if not found:
                break
            steps.append(Step(
                hop=hop_no,
                description=f"Expanded the public law graph: reached {len(found)} related "
                            f"authorities (citations, interpretations, amendment/overturn treatment)",
                node_ids=[dst for _, dst, _ in found][:20],
                edge_types=["CITES", "INTERPRETS", "AMENDS", "OVERTURNS", "DISTINGUISHES"],
            ))
            frontier = next_frontier[:8]
            hop_no += 1

        # Pull text for newly discovered public authorities so the answer can
        # cite them (provenance-tagged like everything else).
        extra = await self._chunks_for_docs(list(seen - set(public_anchor_ids)))
        # Cap the synthesis context: on CPU-only Ollama deployments a large
        # prompt + long generation blows past the gateway/proxy timeout. 8 chunks
        # keeps the doctrinal chain intact while staying inside the latency budget.
        evidence = (chunks + extra)[:8]

        answer = await self._synthesize(query, steps, evidence)
        return steps, evidence, answer

    async def _chunks_for_docs(self, doc_ids: list[str]) -> list[RankedChunk]:
        out: list[RankedChunk] = []
        if not doc_ids:
            return out
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT ON (v.doc_id) v.id::text AS chunk_id, v.doc_id, v.chunk_text,
                          d.title, d.citation, d.source_url, d.court, d.year, d.status
                   FROM public.public_vectors v
                   JOIN public.public_documents d ON d.doc_id = v.doc_id
                   WHERE v.doc_id = ANY($1::text[])
                   ORDER BY v.doc_id, v.chunk_index
                   LIMIT 6""",
                doc_ids[:6],
            )
        for r in rows:
            out.append(RankedChunk(
                chunk_id=r["chunk_id"], text=r["chunk_text"], score=0.5,
                source_type="PUBLIC", source_id=r["doc_id"],
                citation=r["citation"] or r["title"] or "", source_url=r["source_url"] or "",
                status=r["status"] or "current", court=r["court"] or "", year=int(r["year"] or 0),
                metadata={"title": r["title"] or "", "via": "graph_traversal"},
            ))
        return out

    async def _synthesize(self, query: str, steps: list[Step], evidence: list[RankedChunk]) -> str:
        trace_lines = [f"hop {s.hop}: {s.description}" for s in steps]
        ctx_lines = [
            f"[{i}] ({c.source_type}, status={c.status}) {c.citation or c.source_id}\n{c.text}"
            for i, c in enumerate(evidence, 1)
        ]
        prompt = (
            f"Legal reasoning request: {query}\n\n"
            "Graph reasoning trace (how the evidence was found):\n"
            + "\n".join(trace_lines)
            + "\n\n--- CONTEXT ---\n" + "\n\n".join(ctx_lines) + "\n--- END CONTEXT ---\n\n"
            "Reason step by step across these authorities. Make the chain of authority "
            "explicit (what cites, interprets, amends or overturns what). Flag any "
            "authority that is no longer good law. Cite sources as [n]."
        )
        system = (
            "You are WakiliAI's reasoning engine for Kenyan law. Be precise about "
            "the doctrinal chain and about current vs superseded authority. "
            + CONFIDENTIALITY_PREAMBLE
        )
        # 1024 is enough for a cited reasoning answer; larger budgets time out on
        # CPU-only local models (see evidence cap above).
        return await self.llm.complete(system=system, prompt=prompt, max_tokens=1024)
