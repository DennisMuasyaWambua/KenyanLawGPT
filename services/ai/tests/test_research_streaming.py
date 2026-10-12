"""Research latency paths: intent classification overlaps the searches, and
answers stream token by token. Exercised with fakes (no DB / graph / LLM)."""
import asyncio
import contextlib
import time

import pytest

from app import db as dbx
from app.config import Config
from app.reasoning import ReasoningEngine
from app.retrieval import RankedChunk, RetrievalOrchestrator

DELAY = 0.2


class _Graph:
    def __init__(self, rows=None):
        self.rows, self.inflight, self.peak = rows or [], 0, 0

    async def read(self, q):
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        await asyncio.sleep(0.05)
        self.inflight -= 1
        return list(self.rows)


class _Embedder:
    dim = 4

    async def embed(self, texts):
        return [[0.0] * 4 for _ in texts]


class _LLM:
    def __init__(self, label="statute_lookup", tokens=("The ", "answer [1].")):
        self.label, self.tokens, self.prompts = label, tokens, []

    async def complete(self, system, prompt, max_tokens=2048, fast=False):
        if fast:
            await asyncio.sleep(DELAY)  # a slow classification call
            return self.label
        return "".join(self.tokens)

    async def stream(self, system, prompt, max_tokens=8192):
        self.prompts.append(prompt)
        for t in self.tokens:
            yield t


def _public_row(doc_id="d1"):
    return {"chunk_id": "c1", "doc_id": doc_id, "chunk_text": "Section 3 says…", "score": 0.9,
            "status": "current", "doc_type": "statute", "citation": "Act s.3", "title": "Act",
            "source_url": "", "court": "", "year": 2020}


@pytest.fixture
def slow_db(monkeypatch):
    async def public(pool, qvec, n, include_superseded, as_of=None):
        await asyncio.sleep(DELAY)
        return [_public_row()]

    async def tenant(conn, qvec, n):
        await asyncio.sleep(DELAY)
        return []

    @contextlib.asynccontextmanager
    async def tx(pool, tenant_id):
        yield None

    monkeypatch.setattr(dbx, "search_public_chunks", public)
    monkeypatch.setattr(dbx, "search_tenant_chunks", tenant)
    monkeypatch.setattr(dbx, "tenant_tx", tx)


def _orchestrator(llm, graph=None):
    return RetrievalOrchestrator(pool=None, graph=graph or _Graph(), embedder=_Embedder(), llm=llm, cfg=Config())


@pytest.mark.asyncio
async def test_llm_intent_classification_overlaps_the_searches(slow_db):
    r = _orchestrator(_LLM(label="statute_lookup"))
    t = time.perf_counter()
    # No heuristic keyword, so classification goes to the (slow) LLM.
    chunks, intent = await r.retrieve("00000000-0000-0000-0000-000000000001", "what about my land?")
    elapsed = time.perf_counter() - t
    assert intent == "statute_lookup" and chunks[0].source_id == "d1"
    # Sequential would be ~2 * DELAY (classify, then the searches).
    assert elapsed < 1.6 * DELAY


@pytest.mark.asyncio
async def test_status_lookups_run_concurrently(slow_db):
    graph = _Graph()
    await _orchestrator(_LLM(), graph).retrieve("00000000-0000-0000-0000-000000000001", "section 3 of the act")
    assert graph.peak >= 2


@pytest.mark.asyncio
async def test_answer_stream_yields_model_tokens():
    r = _orchestrator(_LLM(tokens=("A", "B", "C")))
    chunk = RankedChunk(chunk_id="c", text="t", score=1, source_type="PUBLIC", source_id="d")
    assert [p async for p in r.answer_stream("t", "q", [chunk], "statute_lookup")] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_answer_stream_without_sources_explains_instead_of_calling_the_model():
    llm = _LLM()
    out = [p async for p in _orchestrator(llm).answer_stream("t", "q", [], "statute_lookup")]
    assert len(out) == 1 and "No relevant sources" in out[0] and llm.prompts == []


@pytest.mark.asyncio
async def test_reasoning_gathers_then_streams_and_reason_still_answers(slow_db):
    llm = _LLM(tokens=("Chain ", "[1]."))
    graph = _Graph()
    retriever = _orchestrator(llm, graph)
    engine = ReasoningEngine(pool=None, graph=graph, retriever=retriever, llm=llm, cfg=Config())
    steps, evidence = await engine.gather("00000000-0000-0000-0000-000000000001", "section 3 of the act")
    assert steps[0].hop == 0 and evidence and evidence[0].source_id == "d1"
    assert [p async for p in engine.synthesis_stream("q", steps, evidence)] == ["Chain ", "[1]."]
    assert "--- CONTEXT ---" in llm.prompts[-1]
    _, _, answer = await engine.reason("00000000-0000-0000-0000-000000000001", "section 3 of the act")
    assert answer == "Chain [1]."
