import asyncio
import math

from app.embeddings import HashingEmbedder


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized


def test_hashing_embedder_deterministic_and_normalized():
    emb = HashingEmbedder(dim=1024)
    v1, v2 = asyncio.run(emb.embed(["unfair termination employment act", "unfair termination employment act"]))
    assert v1 == v2
    assert len(v1) == 1024
    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-6


def test_hashing_embedder_similarity_ordering():
    emb = HashingEmbedder(dim=1024)
    q, similar, unrelated = asyncio.run(emb.embed([
        "unfair termination under the employment act",
        "termination of employment was unfair under section 45 employment act",
        "registration of a certificate of lease for land in nairobi",
    ]))
    assert _cos(q, similar) > _cos(q, unrelated)
