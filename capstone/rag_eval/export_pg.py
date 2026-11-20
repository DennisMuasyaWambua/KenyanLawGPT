"""Export the PUBLIC legal corpus from Postgres (+ optional Neo4j citation edges)
to the harness's JSONL format.

    export DATABASE_URL=postgresql://wakili_app:...@localhost:55432/wakili
    python -m rag_eval.export_pg --out data/corpus.jsonl --doc-types case_law,judgment \
        --neo4j-uri bolt://localhost:7687 --mine-text-citations

Scope / privacy: reads ONLY the shared ``public`` schema (public_documents,
public_vectors). It never touches tenant schemas, so no firm-confidential data can
leak into the capstone repo. Neo4j access is read-only and limited to :Public nodes.

Citation edges (``cites``) come from, in order: Neo4j CITES/INTERPRETS edges
between public docs, then (optionally) exact citation-string matches in the text.
Requires: pip install asyncpg   (and `neo4j` if --neo4j-uri is used)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DOC_SQL = """
SELECT doc_id, title, doc_type, court, citation, year, status, source_url, full_text
FROM public.public_documents
WHERE doc_type = ANY($1::text[])
  AND ($2::text[] IS NULL OR status = ANY($2::text[]))
  AND ($3::int IS NULL OR year >= $3)
  AND ($4::int IS NULL OR year <= $4)
ORDER BY doc_id
"""
CHUNK_SQL = """
SELECT doc_id, chunk_text FROM public.public_vectors
WHERE doc_id = ANY($1::text[]) ORDER BY doc_id, chunk_index
"""
EDGE_CYPHER = """
MATCH (a:Public)-[r:CITES|INTERPRETS]->(b:Public)
WHERE a.doc_id IN $ids AND b.doc_id IN $ids AND a.doc_id <> b.doc_id
RETURN DISTINCT a.doc_id AS src, b.doc_id AS dst
"""


# ---- pure helpers (unit-tested; no I/O) ------------------------------------------
def doc_text(full_text: str, chunks: Sequence[str]) -> str:
    """Prefer the stored full text. Otherwise rebuild from chunks (these overlap by
    design, so the rebuilt text can repeat ~150 chars at each seam; harmless for
    retrieval evaluation but noted in the manifest)."""
    return full_text if full_text and full_text.strip() else "\n\n".join(chunks)


def build_record(row: Mapping[str, Any], chunks: Sequence[str]) -> dict[str, Any] | None:
    text = doc_text(row.get("full_text") or "", chunks).strip()
    if not text:
        return None
    return {"doc_id": row["doc_id"], "title": row.get("title") or "", "court": row.get("court") or "",
            "year": int(row.get("year") or 0), "citation": row.get("citation") or "",
            "doc_type": row.get("doc_type") or "", "source_url": row.get("source_url") or "",
            "text": text, "cites": []}


def mine_text_citations(records: list[dict[str, Any]], min_len: int = 8) -> int:
    """Add cites edges where doc A's text contains doc B's exact citation string
    (e.g. '[2019] eKLR'-style or 'Civil Appeal No. 12 of 2016'). Returns edges added."""
    index = {re.sub(r"\s+", " ", r["citation"]).strip().lower(): r["doc_id"]
             for r in records if len(r.get("citation", "")) >= min_len}
    added = 0
    for r in records:
        hay = re.sub(r"\s+", " ", r["text"]).lower()
        for cite, dst in index.items():
            if dst != r["doc_id"] and cite in hay and dst not in r["cites"]:
                r["cites"].append(dst)
                added += 1
    return added


def merge_edges(records: list[dict[str, Any]], edges: Iterable[tuple[str, str]]) -> int:
    by_id = {r["doc_id"]: r for r in records}
    added = 0
    for src, dst in edges:
        if src in by_id and dst in by_id and src != dst and dst not in by_id[src]["cites"]:
            by_id[src]["cites"].append(dst)
            added += 1
    return added


def select(records: list[dict[str, Any]], min_chars: int, limit: int | None, seed: int) -> list[dict[str, Any]]:
    kept = [r for r in records if len(r["text"]) >= min_chars]
    if limit and len(kept) > limit:
        kept = random.Random(seed).sample(kept, limit)  # reproducible subsample
    return sorted(kept, key=lambda r: r["doc_id"])


# ---- I/O ----------------------------------------------------------------------------
async def fetch_records(dsn: str, a: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    import asyncpg  # lazy: keeps the rest of the harness numpy-only
    conn = await asyncpg.connect(dsn)
    try:
        types = [t.strip() for t in a.doc_types.split(",") if t.strip()]
        statuses = [s.strip() for s in a.status.split(",")] if a.status else None
        rows = await conn.fetch(DOC_SQL, types, statuses, a.year_from, a.year_to)
        chunks: dict[str, list[str]] = {}
        need = [r["doc_id"] for r in rows if not (r["full_text"] or "").strip()]
        if need:
            for c in await conn.fetch(CHUNK_SQL, need):
                chunks.setdefault(c["doc_id"], []).append(c["chunk_text"])
        recs = [rec for r in rows if (rec := build_record(dict(r), chunks.get(r["doc_id"], [])))]
        return recs, len(need)
    finally:
        await conn.close()


async def fetch_edges(a: argparse.Namespace, ids: list[str]) -> list[tuple[str, str]]:
    try:
        from neo4j import AsyncGraphDatabase, READ_ACCESS
    except ImportError:
        raise SystemExit("pip install neo4j to use --neo4j-uri")
    driver = AsyncGraphDatabase.driver(a.neo4j_uri, auth=(a.neo4j_user, a.neo4j_password))
    try:
        async with driver.session(default_access_mode=READ_ACCESS) as s:
            res = await s.run(EDGE_CYPHER, ids=ids)
            return [(r["src"], r["dst"]) async for r in res]
    finally:
        await driver.close()


async def amain(a: argparse.Namespace) -> None:
    dsn = a.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("set DATABASE_URL or pass --dsn")
    recs, rebuilt = await fetch_records(dsn, a)
    recs = select(recs, a.min_chars, a.limit, a.seed)
    graph_edges = text_edges = 0
    if a.neo4j_uri:
        graph_edges = merge_edges(recs, await fetch_edges(a, [r["doc_id"] for r in recs]))
    if a.mine_text_citations:
        text_edges = mine_text_citations(recs)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {"exported_at": datetime.now(timezone.utc).isoformat(), "docs": len(recs),
                "doc_types": a.doc_types, "status": a.status, "year_from": a.year_from,
                "year_to": a.year_to, "min_chars": a.min_chars, "limit": a.limit, "seed": a.seed,
                "text_rebuilt_from_chunks": rebuilt, "edges_from_neo4j": graph_edges,
                "edges_from_text_mining": text_edges,
                "docs_with_cites": sum(1 for r in recs if r["cites"]),
                "source": "public schema only (no tenant data)"}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    if not recs:
        print("WARNING: 0 documents exported; check --doc-types against SELECT DISTINCT doc_type "
              "FROM public.public_documents.", file=sys.stderr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/corpus.jsonl")
    ap.add_argument("--dsn", help="defaults to $DATABASE_URL")
    ap.add_argument("--doc-types", default="case_law,judgment")
    ap.add_argument("--status", default="", help="comma list, e.g. current,amended; empty = all")
    ap.add_argument("--year-from", type=int); ap.add_argument("--year-to", type=int)
    ap.add_argument("--min-chars", type=int, default=500, help="drop stubs shorter than this")
    ap.add_argument("--limit", type=int, help="reproducible random subsample size")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--neo4j-uri"); ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", ""))
    ap.add_argument("--mine-text-citations", action="store_true")
    asyncio.run(amain(ap.parse_args(argv)))


if __name__ == "__main__":
    main()
