"""Hybrid research: lexical+dense fusion, per-document cap, whole-word intent."""
import pytest

from app.fusion import cap_per_source, rrf_fuse
from app.retrieval import RankedChunk, RetrievalOrchestrator
from tests.test_research_streaming import _LLM, _orchestrator


def _row(cid, score=0.5):
    return {"chunk_id": cid, "doc_id": "d" + cid, "chunk_text": cid, "score": score}


def test_exact_term_hit_missed_by_dense_is_kept_and_boosted():
    dense = [_row("a"), _row("b"), _row("c")]
    lexical = [_row("z"), _row("c")]  # z is lexical-only; c is found by both
    out = rrf_fuse(dense, lexical)
    ids = [r["chunk_id"] for r in out]
    assert "z" in ids                       # exact-term hit is no longer lost
    assert ids.index("c") < ids.index("b")  # agreement between retrievers wins


def test_top_in_both_lists_scores_one_and_scale_is_bounded():
    out = rrf_fuse([_row("a"), _row("b")], [_row("a")])
    assert out[0]["chunk_id"] == "a" and out[0]["score"] == pytest.approx(1.0)
    assert all(0 < r["score"] <= 1 for r in out)


def test_dense_only_still_works_when_lexical_is_empty():
    out = rrf_fuse([_row("a"), _row("b")], [])
    assert [r["chunk_id"] for r in out] == ["a", "b"]


def _chunk(cid, src, score):
    return RankedChunk(chunk_id=cid, text="t", score=score, source_type="PUBLIC", source_id=src)


def test_cap_per_source_diversifies_then_backfills():
    chunks = [_chunk(f"x{i}", "long", 1 - i * 0.01) for i in range(5)] + [_chunk("y", "other", 0.2)]
    top = cap_per_source(chunks, limit=2, top_k=3)
    assert {c.source_id for c in top} == {"long", "other"} and len(top) == 3
    # only one source exists: backfill so we still return top_k
    only = cap_per_source([_chunk(f"x{i}", "s", 1 - i * 0.1) for i in range(5)], limit=2, top_k=4)
    assert len(only) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("is this contract enforceable in fact", None),   # "act" inside words must not trigger statute
    ("wages withheld by employer", None),             # "held" inside "withheld"
    ("what does section 41 say", "statute_lookup"),
    ("what was held in the Supreme Court", "case_law_research"),
    ("draft a demand letter", "drafting"),
])
async def test_intent_uses_whole_words(query, expected):
    r = _orchestrator(_LLM(label="case_law_research"))
    got = await r.classify_intent(query)
    assert got == (expected or "case_law_research")  # None => falls through to the LLM/default
