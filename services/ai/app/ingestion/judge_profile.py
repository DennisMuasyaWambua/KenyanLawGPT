"""Periodic public judge-profile computation (Task 4).

Builds, from PUBLIC case data only, the aggregate profile the judge-aware
retriever reads:

    (:Judge)-[:RULED_ON {outcome_alignment}]->(:Judgment|:CaseLaw)
    judge.rulings_count / favored_plaintiff / favored_defendant

ISOLATION: this job reads and writes the *public* graph exclusively. The
per-tenant slice of a judge's history is never mixed in here — that would put
one firm's data on a node shared with its competitors. Tenant history is
aggregated at query time inside the tenant partition (see app.judge).

Runs periodically (wired to the ingestion scheduler), never per query.
"""
from __future__ import annotations

from .. import db as dbx
from ..config import Config
from ..graph import Graph, PublicGraphQuery
from ..logging_setup import log
from .extraction import extract_entities

_ALIGN = {"won": "favored_plaintiff", "lost": "favored_defendant"}


class JudgeProfiler:
    def __init__(self, pool, graph: Graph, cfg: Config) -> None:
        self.pool = pool
        self.graph = graph
        self.cfg = cfg

    async def recompute(self) -> int:
        judges = await self.graph.read(
            PublicGraphQuery().match("j", "Judge").returns("j.name AS name").limit(1000).build())
        n = 0
        for row in judges:
            name = row.get("name")
            if name:
                try:
                    await self._profile_one(name)
                    n += 1
                except Exception:
                    log().exception("judge profile failed for %r", name)
        log().info("judge profiler: recomputed %d public judge profile(s)", n)
        return n

    async def _profile_one(self, name: str) -> None:
        cases: list[tuple[str, str, str]] = []  # (doc_id, title, label)
        for label in ("Judgment", "CaseLaw"):
            rows = await self.graph.read(
                PublicGraphQuery()
                .match("j", "Judge", name=name)
                .match_rel("j", ["AUTHORED"], "c", label, direction="out")
                .returns("c.doc_id AS doc_id", "c.title AS title")
                .limit(300).build())
            cases.extend((r["doc_id"], r.get("title") or "", label)
                         for r in rows if r.get("doc_id"))

        favored_plaintiff = favored_defendant = 0
        for doc_id, title, label in cases:
            text = await dbx.public_doc_text(self.pool, doc_id)
            entities = extract_entities(text or title, title)
            alignment = "unknown"
            if entities.outcome:
                alignment = _ALIGN.get(entities.outcome["result"], "unknown")
                if alignment == "favored_plaintiff":
                    favored_plaintiff += 1
                elif alignment == "favored_defendant":
                    favored_defendant += 1
            # RULED_ON is a PUBLIC write — internal batch path only.
            await self.graph._run_internal(
                f"""MATCH (j:Judge:Public {{name: $name}}), (c:{label}:Public {{doc_id: $doc_id}})
                    MERGE (j)-[r:RULED_ON]->(c)
                    SET r.outcome_alignment = $align""",
                {"name": name, "doc_id": doc_id, "align": alignment},
            )

        await self.graph._run_internal(
            """MATCH (j:Judge:Public {name: $name})
               SET j.rulings_count = $n, j.favored_plaintiff = $fp,
                   j.favored_defendant = $fd, j.profile_updated = timestamp()""",
            {"name": name, "n": len(cases), "fp": favored_plaintiff, "fd": favored_defendant},
        )
