"""Judge-aware reasoning: detection, pattern assembly, and tenant isolation
of the firm-internal history (Task 4)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.judge import JUDICIAL_ANALYTICS_DISCLAIMER, JudgeReasoner

TENANT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


class FakeGraph:
    """Returns canned rows and asserts every tenant read is tenant-scoped and
    every public read is not — so a leak in query construction fails the test."""
    def __init__(self):
        self.tenant_reads = 0
        self.public_reads = 0

    async def read(self, q):
        cy = q.cypher
        if "Matter" in cy and "RESULTED_IN" in cy:
            assert q.tenant_scoped and q.params.get("tenant_id") == TENANT
            self.tenant_reads += 1
            return [{"matter_id": "m1", "result": "won"},
                    {"matter_id": "m2", "result": "lost"},
                    {"matter_id": "m3", "result": "won"}]
        if "FILED_IN" in cy and "Statute" in cy:
            assert q.tenant_scoped and q.params.get("tenant_id") == TENANT
            self.tenant_reads += 1
            return [{"title": "Land Registration Act"}, {"title": "Land Registration Act"}]
        if "FILED_IN" in cy and "CaseLaw" in cy:
            assert q.tenant_scoped and q.params.get("tenant_id") == TENANT
            self.tenant_reads += 1
            return [{"title": "Kamau v Njoroge [2015] eKLR"}]
        if "Judge" in cy and "rulings_count" in cy:
            assert not q.tenant_scoped  # public read: no tenant filter
            self.public_reads += 1
            return [{"rulings_count": 10, "favored_plaintiff": 6, "favored_defendant": 4}]
        return []


def _reasoner(graph):
    return JudgeReasoner(pool=None, graph=graph, cfg=SimpleNamespace(enable_judge_reasoning=True))


@pytest.mark.parametrize("query,expected", [
    ("What has worked before Justice Mwangi?", "Mwangi"),
    ("cases before Judge Peter Omondi", "Peter Omondi"),
    ("submissions before Hon. Lady Justice Aoko", "Aoko"),
    ("Judge Mwangi J history", "Mwangi"),
    ("What does the Land Act say?", None),
])
def test_detect_judge_name(query, expected):
    assert JudgeReasoner.detect_judge_name(query) == expected


@pytest.mark.asyncio
async def test_context_block_merges_tenant_and_public_and_is_scoped():
    graph = FakeGraph()
    block = await _reasoner(graph).context_block(TENANT, "Jane Mwangi")
    # firm-internal + public signals both present
    assert JUDICIAL_ANALYTICS_DISCLAIMER.split(" —")[0] in block
    assert "3 prior matter(s)" in block
    assert "2 had a favourable outcome" in block          # two 'won'
    assert "Land Registration Act (x2)" in block          # top winning authority
    assert "10 ruling(s)" in block                        # public profile
    assert graph.tenant_reads >= 2 and graph.public_reads == 1


@pytest.mark.asyncio
async def test_no_signal_returns_empty():
    class Empty:
        async def read(self, q):
            return []
    assert await _reasoner(Empty()).context_block(TENANT, "Nobody") == ""
