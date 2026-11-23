"""Rank fusion for hybrid retrieval (dense + lexical), kept free of I/O so it is unit-testable."""
from __future__ import annotations

from typing import Any, Sequence

RRF_K = 60


def rrf_fuse(dense: Sequence[dict[str, Any]], lexical: Sequence[dict[str, Any]], *,
             key: str = "chunk_id", k: int = RRF_K,
             w_dense: float = 1.0, w_lex: float = 1.0) -> list[dict[str, Any]]:
    """Weighted Reciprocal Rank Fusion of two ranked row lists.

    Each row scores ``w / (k + rank)`` per list it appears in. The result is
    normalised so a chunk ranked first by both retrievers scores 1.0, keeping
    ``score`` on the same 0..1 scale as the old cosine score so downstream
    boosts and UI are unaffected. Row data comes from whichever list had the
    chunk (dense preferred); lexical-only hits are kept."""
    fused: dict[Any, dict[str, Any]] = {}
    raw: dict[Any, float] = {}
    for weight, rows in ((w_dense, dense), (w_lex, lexical)):
        for rank, row in enumerate(rows, 1):
            kid = row[key]
            fused.setdefault(kid, dict(row))
            raw[kid] = raw.get(kid, 0.0) + weight / (k + rank)
    best = (w_dense + w_lex) / (k + 1)
    out = []
    for kid, row in fused.items():
        row["score"] = raw[kid] / best
        out.append(row)
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def cap_per_source(chunks: list, limit: int, top_k: int) -> list:
    """Keep the best ``limit`` chunks per source document so one long judgment
    cannot fill the whole result list; backfill if that leaves fewer than top_k."""
    kept, spill, seen = [], [], {}
    for c in chunks:
        n = seen.get(c.source_id, 0)
        if n < limit:
            seen[c.source_id] = n + 1
            kept.append(c)
        else:
            spill.append(c)
    kept = kept[:top_k]
    if len(kept) < top_k:
        kept.extend(spill[: top_k - len(kept)])
        kept.sort(key=lambda c: c.score, reverse=True)
    return kept
