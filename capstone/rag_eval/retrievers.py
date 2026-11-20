"""Retrieval systems under comparison. Every retriever is built over the same
chunk list and returns a *doc-level* ranking (best chunk score per document), so
chunk size can be ablated without changing the metric definition."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Protocol, Sequence

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOP = frozenset("a an and are as at be by for from has have in is it its of on or that the to was were with this".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


class Retriever(Protocol):
    name: str

    def scores(self, query: str) -> np.ndarray: ...  # one score per chunk


def to_doc_ranking(chunk_scores: np.ndarray, owners: Sequence[str], k: int) -> list[str]:
    best: dict[str, float] = {}
    for s, d in zip(chunk_scores, owners):
        if d not in best or s > best[d]:
            best[d] = float(s)
    return [d for d, _ in sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:k]]


class BM25:
    name = "bm25"

    def __init__(self, chunks: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(c)) for c in chunks]
        self.len = np.array([sum(t.values()) for t in self.tf], dtype=float)
        self.avg = self.len.mean() if len(self.len) else 1.0
        df: Counter = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(chunks)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.tf))
        for w in set(tokenize(query)):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i, t in enumerate(self.tf):
                f = t.get(w)
                if f:
                    out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return out


class HashingDense:
    """Offline baseline: signed feature hashing of unigrams+bigrams (same algorithm
    as services/ai HashingEmbedder). Lexical in nature — a *floor*, not a stand-in
    for a learned embedding."""
    name = "dense_hashing"

    def __init__(self, chunks: Sequence[str], dim: int = 1024) -> None:
        self.dim = dim
        self.mat = np.vstack([self._vec(c) for c in chunks]) if chunks else np.zeros((0, dim))

    def _vec(self, text: str) -> np.ndarray:
        toks = _TOKEN_RE.findall(text.lower())
        v = np.zeros(self.dim)
        for g in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
            h = hashlib.sha256(g.encode()).digest()
            v[int.from_bytes(h[:4], "big") % self.dim] += 1.0 if h[4] % 2 == 0 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def scores(self, query: str) -> np.ndarray:
        return self.mat @ self._vec(query)


class SentenceTransformerDense:
    """Learned dense embeddings via sentence-transformers (optional dependency),
    e.g. 'BAAI/bge-small-en-v1.5' or 'sentence-transformers/all-MiniLM-L6-v2'."""

    def __init__(self, chunks: Sequence[str], model: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("pip install sentence-transformers to use --dense st:<model>") from exc
        self.name = f"dense_{model.split('/')[-1]}"
        self.model = SentenceTransformer(model)
        self.mat = self.model.encode(list(chunks), normalize_embeddings=True, show_progress_bar=False)

    def scores(self, query: str) -> np.ndarray:
        return self.mat @ self.model.encode([query], normalize_embeddings=True)[0]


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion over doc rankings."""
    fused: dict[str, float] = defaultdict(float)
    for r in rankings:
        for i, d in enumerate(r, 1):
            fused[d] += 1.0 / (k + i)
    return dict(fused)


def graph_expand(fused: dict[str, float], cites: dict[str, list[str]], top_n: int = 5,
                 decay: float = 0.5) -> dict[str, float]:
    """Citation-graph expansion: documents cited by (or citing) the top-n hits inherit
    a decayed share of the hit's score. Mirrors the Advocatus graph boost, but over
    precedent citations, which is what 'identify all relevant precedents' needs."""
    reverse: dict[str, list[str]] = defaultdict(list)
    for src, targets in cites.items():
        for t in targets:
            reverse[t].append(src)
    out = dict(fused)
    for d, s in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_n]:
        for nb in set(cites.get(d, [])) | set(reverse.get(d, [])):
            out[nb] = max(out.get(nb, 0.0), 0.0) + decay * s
    return out


class System:
    """A named end-to-end retrieval configuration: query -> doc ranking."""

    def __init__(self, name: str, fn) -> None:
        self.name, self.fn = name, fn

    def rank(self, query: str, k: int) -> list[str]:
        return self.fn(query, k)


def build_systems(chunks: Sequence[str], owners: Sequence[str], cites: dict[str, list[str]],
                  dense_spec: str = "hashing", pool: int = 50) -> list[System]:
    bm25 = BM25(chunks)
    if dense_spec.startswith("st:"):
        dense = SentenceTransformerDense(chunks, dense_spec[3:])
    else:
        dense = HashingDense(chunks)

    def r_bm25(q, k): return to_doc_ranking(bm25.scores(q), owners, k)
    def r_dense(q, k): return to_doc_ranking(dense.scores(q), owners, k)

    def fuse(q):
        return rrf([to_doc_ranking(bm25.scores(q), owners, pool), to_doc_ranking(dense.scores(q), owners, pool)])

    def r_hybrid(q, k):
        f = fuse(q)
        return [d for d, _ in sorted(f.items(), key=lambda kv: kv[1], reverse=True)[:k]]

    def r_graph(q, k):
        f = graph_expand(fuse(q), cites)
        return [d for d, _ in sorted(f.items(), key=lambda kv: kv[1], reverse=True)[:k]]

    return [System("bm25", r_bm25), System(dense.name, r_dense),
            System("hybrid_rrf", r_hybrid), System("hybrid_rrf+graph", r_graph)]
