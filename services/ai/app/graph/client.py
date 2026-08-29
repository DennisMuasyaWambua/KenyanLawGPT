"""Neo4j driver wrapper that only executes builder-produced queries."""
from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase

from ..config import Config
from .builders import GraphQuery, GraphQueryError, is_builder_query


class Graph:
    def __init__(self, cfg: Config) -> None:
        self._driver = AsyncGraphDatabase.driver(
            cfg.neo4j_uri, auth=(cfg.neo4j_user, cfg.neo4j_password)
        )

    async def close(self) -> None:
        await self._driver.close()

    async def ensure_indexes(self) -> None:
        stmts = [
            "CREATE INDEX tenant_file IF NOT EXISTS FOR (n:File) ON (n.tenant_id, n.id)",
            "CREATE INDEX tenant_archive IF NOT EXISTS FOR (n:Archive) ON (n.tenant_id, n.id)",
            "CREATE INDEX tenant_party IF NOT EXISTS FOR (n:Party) ON (n.tenant_id, n.id)",
            "CREATE INDEX tenant_submission IF NOT EXISTS FOR (n:Submission) ON (n.tenant_id, n.id)",
            "CREATE INDEX tenant_outcome IF NOT EXISTS FOR (n:Outcome) ON (n.tenant_id, n.id)",
            "CREATE INDEX tenant_advocate IF NOT EXISTS FOR (n:Advocate) ON (n.tenant_id, n.id)",
            "CREATE INDEX public_doc IF NOT EXISTS FOR (n:Public) ON (n.doc_id)",
            # Judge lookup by name for judge-aware retrieval (public graph).
            "CREATE INDEX public_judge_name IF NOT EXISTS FOR (n:Judge) ON (n.name)",
        ]
        async with self._driver.session() as session:
            for stmt in stmts:
                await session.run(stmt)

    async def read(self, q: GraphQuery) -> list[dict[str, Any]]:
        if not is_builder_query(q):
            raise GraphQueryError("only builder-produced queries may execute")
        if q.write:
            raise GraphQueryError("write query passed to read()")

        async def work(tx):
            result = await tx.run(q.cypher, q.params)
            return [dict(record) async for record in result]

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def write(self, q: GraphQuery) -> dict[str, int]:
        if not is_builder_query(q):
            raise GraphQueryError("only builder-produced queries may execute")
        if not q.write:
            raise GraphQueryError("read query passed to write()")
        if not q.tenant_scoped:
            raise GraphQueryError("request-path writes must be tenant-scoped")

        async def work(tx):
            result = await tx.run(q.cypher, q.params)
            summary = await result.consume()
            return {
                "nodes_created": summary.counters.nodes_created,
                "nodes_deleted": summary.counters.nodes_deleted,
                "relationships_created": summary.counters.relationships_created,
            }

        async with self._driver.session() as session:
            return await session.execute_write(work)

    # Escape hatch used ONLY by app.ingestion.pipeline.PublicCorpusWriter for
    # batch public-corpus writes; never imported by request-path modules.
    async def _run_internal(self, cypher: str, params: dict) -> None:
        async with self._driver.session() as session:
            await session.run(cypher, params)
