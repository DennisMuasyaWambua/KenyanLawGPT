"""Embedding providers.

``VoyageEmbedder`` (voyage-law-2, legal-domain, 1024-dim) is used when a key
is configured. ``HashingEmbedder`` is a deterministic bag-of-words feature
hashing embedder — no network, stable across processes — used for dev and the
isolation test-suite. Both write to the same pgvector columns; dimensions must
match EMBEDDING_DIM (default 1024).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

import httpx

from .config import Config

_TOKEN_RE = re.compile(r"[a-z0-9']+")


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic feature-hashing embedder (unigrams + bigrams, signed
    hashing, L2-normalized). Gives genuine cosine-similarity behavior on
    shared vocabulary, which is enough for offline demos and for asserting
    isolation properties in tests."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        grams = tokens + [a + "_" + b for a, b in zip(tokens, tokens[1:])]
        for gram in grams:
            digest = hashlib.sha256(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class VoyageEmbedder:
    """voyage-law-2 via the Voyage AI REST API (legal-domain embeddings)."""

    def __init__(self, api_key: str, model: str, dim: int) -> None:
        self.api_key = api_key
        self.model = model
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": list(texts)},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]


def make_embedder(cfg: Config) -> EmbeddingProvider:
    if cfg.embedding_provider == "voyage" or (cfg.embedding_provider == "auto" and cfg.voyage_api_key):
        return VoyageEmbedder(cfg.voyage_api_key, cfg.voyage_model, cfg.embedding_dim)
    return HashingEmbedder(cfg.embedding_dim)
