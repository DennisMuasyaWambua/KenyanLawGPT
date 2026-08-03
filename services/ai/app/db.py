"""Postgres access: shared public corpus tables + per-tenant schema vectors.

Tenant isolation invariants:
  * every tenant-scoped statement runs inside a transaction whose
    search_path is pinned via ``tenant_tx`` from a *validated* tenant id;
  * the public corpus lives in explicit ``public.``-qualified tables.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

import asyncpg

from .tenancy import schema_for


async def init_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=2, max_size=10)


def vec_literal(vec: Sequence[float]) -> str:
    """pgvector text representation; bound as a parameter and cast ::vector."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


@asynccontextmanager
async def tenant_tx(pool: asyncpg.Pool, tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Transaction pinned to the tenant's schema (plus public for the vector
    type). SET LOCAL scopes the search_path to this transaction only, so
    pooled connections cannot leak tenant state."""
    schema = schema_for(tenant_id)  # raises on anything malformed
    async with pool.acquire() as conn:
        async with conn.transaction():
            # schema passed regex ^tenant_[0-9a-f]{32}$ — safe to interpolate.
            await conn.execute(f'SET LOCAL search_path = "{schema}", public')
            yield conn


# --- tenant-private vectors ---

async def insert_chunks(
    conn: asyncpg.Connection,
    document_id: str,
    chunks: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    metadata: Optional[dict] = None,
) -> int:
    meta = json.dumps(metadata or {})
    rows = [
        (document_id, i, chunk, vec_literal(emb), meta)
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    await conn.executemany(
        """INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding, metadata)
           VALUES ($1, $2, $3, $4::vector, $5::jsonb)""",
        rows,
    )
    return len(rows)


async def delete_chunks(conn: asyncpg.Connection, document_ids: Sequence[str]) -> int:
    if not document_ids:
        return 0
    result = await conn.execute(
        "DELETE FROM document_chunks WHERE document_id = ANY($1::uuid[])", list(document_ids)
    )
    return int(result.split()[-1])


async def search_tenant_chunks(
    conn: asyncpg.Connection, query_vec: Sequence[float], top_k: int
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """SELECT c.id::text AS chunk_id, c.document_id::text AS document_id, c.chunk_text,
                  c.metadata::text AS metadata,
                  1 - (c.embedding <=> $1::vector) AS score,
                  d.filename, d.doc_kind
           FROM document_chunks c
           JOIN documents d ON d.id = c.document_id
           WHERE c.embedding IS NOT NULL
           ORDER BY c.embedding <=> $1::vector
           LIMIT $2""",
        vec_literal(query_vec), top_k,
    )
    return [dict(r) for r in rows]


# --- shared public corpus ---

async def search_public_chunks(
    pool: asyncpg.Pool, query_vec: Sequence[float], top_k: int, include_superseded: bool
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT v.id::text AS chunk_id, v.doc_id, v.chunk_text, v.metadata::text AS metadata,
                      1 - (v.embedding <=> $1::vector) AS score,
                      d.title, d.doc_type, d.source_url, d.court, d.citation, d.year, d.status
               FROM public.public_vectors v
               JOIN public.public_documents d ON d.doc_id = v.doc_id
               WHERE ($3 OR d.status = 'current')
               ORDER BY v.embedding <=> $1::vector
               LIMIT $2""",
            vec_literal(query_vec), top_k, include_superseded,
        )
    return [dict(r) for r in rows]


async def get_public_document(pool: asyncpg.Pool, doc_id: str) -> Optional[dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM public.public_documents WHERE doc_id = $1", doc_id)
    return dict(row) if row else None


async def public_doc_text(pool: asyncpg.Pool, doc_id: str, max_chunks: int = 6) -> str:
    """Concatenate a public document's leading chunks (for judge-profile outcome
    classification). Public data only — no tenant scope involved."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT chunk_text FROM public.public_vectors
               WHERE doc_id = $1 ORDER BY id LIMIT $2""",
            doc_id, max_chunks,
        )
    return "\n".join(r["chunk_text"] for r in rows)


async def find_public_docs_by_title(pool: asyncpg.Pool, needle: str, limit: int = 3) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT doc_id, title, doc_type, citation, source_url, court, year, status
               FROM public.public_documents
               WHERE title ILIKE '%' || $1 || '%' AND status = 'current' LIMIT $2""",
            needle, limit,
        )
    return [dict(r) for r in rows]
