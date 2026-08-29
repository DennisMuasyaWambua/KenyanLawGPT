"""Cross-tenant leakage test suite (§3.2 of the spec).

Provisions two fake tenants with distinguishable private data and asserts that
tenant A's queries can never see tenant B's vectors, graph nodes, or documents
— through the data layer AND through the gRPC service path (including the
channel-metadata cross-check).

Requires live Postgres + Neo4j (docker compose):
    make test-integration       # sets WAKILI_INTEGRATION=1
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("WAKILI_INTEGRATION") != "1",
    reason="integration suite: needs Postgres+Neo4j (run via `make test-integration`)",
)

TENANT_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
MARKER_A = "MWANGI-CONFIDENTIAL-ALPHA settlement floor KES 1,400,000"
MARKER_B = "ODHIAMBO-CONFIDENTIAL-BRAVO settlement ceiling KES 9,900,000"

TENANT_MIGRATION = (
    Path(__file__).resolve().parents[3] / "infra" / "migrations" / "tenant" / "0001_init.sql"
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def env(event_loop):
    """Pool + graph + engines wired exactly like production, plus two
    provisioned fake tenants carrying distinguishable secrets."""
    from app import db as dbx
    from app.config import load
    from app.embeddings import HashingEmbedder
    from app.graph import Graph, TenantScopedGraphQuery
    from app.llm import MockProvider
    from app.retrieval import RetrievalOrchestrator
    from app.tenancy import schema_for

    async def _setup():
        cfg = load()
        pool = await dbx.init_pool(cfg.database_url)
        graph = Graph(cfg)
        await graph.ensure_indexes()
        embedder = HashingEmbedder(cfg.embedding_dim)
        retriever = RetrievalOrchestrator(pool, graph, embedder, MockProvider(), cfg)

        ddl = TENANT_MIGRATION.read_text()
        docs = {}
        for tid, marker in ((TENANT_A, MARKER_A), (TENANT_B, MARKER_B)):
            schema = schema_for(tid)
            async with pool.acquire() as conn:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                await conn.execute(f'CREATE SCHEMA "{schema}"')
                async with conn.transaction():
                    await conn.execute(f'SET LOCAL search_path = "{schema}", public')
                    await conn.execute(ddl)
            doc_id = str(uuid.uuid4())
            user_id = str(uuid.uuid4())
            async with dbx.tenant_tx(pool, tid) as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, full_name, role, status, password_hash) "
                    "VALUES ($1,$2,'t','owner','active','x')", user_id, f"o@{tid}.test")
                await conn.execute(
                    "INSERT INTO archives (id, filename, object_key, mime_type, doc_kind, uploaded_by, ingest_status) "
                    "VALUES ($1,'note.txt',$2,'text/plain','precedent_note',$3,'ingested')",
                    doc_id, f"tenants/{tid}/documents/{doc_id}/note.txt", user_id)
                text = f"Internal strategy note on unfair termination. {marker}"
                [emb] = await embedder.embed([text])
                await dbx.insert_chunks(conn, doc_id, [text], [emb])
            # Tenant graph node + link to a shared public statute node.
            await graph._run_internal(
                "MERGE (s:Statute:Public {doc_id: 'act-2007-11-employment'}) "
                "SET s.title = 'Employment Act, No. 11 of 2007', s.status = 'current'", {})
            q = (TenantScopedGraphQuery(tid)
                 .merge_node("d", "Archive", {"id": doc_id}, {"filename": "note.txt"})
                 .match_public("s", "Statute", doc_id="act-2007-11-employment")
                 .merge_rel("d", "CITES", "s")
                 .build())
            await graph.write(q)
            docs[tid] = doc_id
        return cfg, pool, graph, embedder, retriever, docs

    cfg, pool, graph, embedder, retriever, docs = event_loop.run_until_complete(_setup())
    yield {"cfg": cfg, "pool": pool, "graph": graph, "embedder": embedder,
           "retriever": retriever, "docs": docs, "loop": event_loop}
    event_loop.run_until_complete(graph.close())
    event_loop.run_until_complete(pool.close())


def run(env, coro):
    return env["loop"].run_until_complete(coro)


# --- 1. Vector isolation ------------------------------------------------------

def test_vector_search_never_crosses_tenants(env):
    from app import db as dbx

    async def search(tid):
        [qvec] = await env["embedder"].embed(["confidential settlement strategy unfair termination"])
        async with dbx.tenant_tx(env["pool"], tid) as conn:
            return await dbx.search_tenant_chunks(conn, qvec, 20)

    rows_a = run(env, search(TENANT_A))
    rows_b = run(env, search(TENANT_B))
    text_a = " ".join(r["chunk_text"] for r in rows_a)
    text_b = " ".join(r["chunk_text"] for r in rows_b)
    assert "MWANGI-CONFIDENTIAL-ALPHA" in text_a
    assert "ODHIAMBO-CONFIDENTIAL-BRAVO" not in text_a
    assert "ODHIAMBO-CONFIDENTIAL-BRAVO" in text_b
    assert "MWANGI-CONFIDENTIAL-ALPHA" not in text_b


def test_orchestrator_retrieval_is_tenant_scoped(env):
    chunks_a, _ = run(env, env["retriever"].retrieve(
        TENANT_A, "confidential settlement strategy unfair termination", top_k=20))
    private_ids = {c.source_id for c in chunks_a if c.source_type == "TENANT_PRIVATE"}
    assert env["docs"][TENANT_A] in private_ids
    assert env["docs"][TENANT_B] not in private_ids
    assert all("ODHIAMBO-CONFIDENTIAL-BRAVO" not in c.text for c in chunks_a)


# --- 2. Graph isolation --------------------------------------------------------

def test_graph_reads_are_tenant_scoped(env):
    from app.graph import TenantScopedGraphQuery

    q = (TenantScopedGraphQuery(TENANT_A)
         .match("d", "Archive").returns("d.id AS id").limit(100).build())
    rows = run(env, env["graph"].read(q))
    ids = {r["id"] for r in rows}
    assert env["docs"][TENANT_A] in ids
    assert env["docs"][TENANT_B] not in ids


def test_multihop_traversal_cannot_walk_through_shared_public_nodes(env):
    """Both tenants CITE the same public statute. A var-length traversal from
    tenant A's document must reach the statute but never continue into tenant
    B's partition on the other side."""
    from app.graph import TenantScopedGraphQuery

    q = (TenantScopedGraphQuery(TENANT_A)
         .match("d", "Archive", id=env["docs"][TENANT_A])
         .expand("d", ["CITES", "LINKED_TO", "SIMILAR_TO"], "n", max_hops=4)
         .returns("n.id AS id", "labels(n) AS labels").limit(200).build())
    rows = run(env, env["graph"].read(q))
    reached_ids = {r["id"] for r in rows if r["id"]}
    assert env["docs"][TENANT_B] not in reached_ids, (
        "LEAKAGE: multi-hop traversal escaped into another tenant's partition"
    )


# --- 3. gRPC path (message/metadata cross-check + scoped results) --------------

def test_grpc_rejects_metadata_mismatch_and_scopes_results(env):
    import grpc

    from wakili.v1 import common_pb2, retrieval_pb2, retrieval_pb2_grpc
    from app.server import RetrievalService

    async def scenario():
        server = grpc.aio.server()
        retrieval_pb2_grpc.add_RetrievalServiceServicer_to_server(
            RetrievalService(env["retriever"]), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = retrieval_pb2_grpc.RetrievalServiceStub(channel)
                request = retrieval_pb2.TenantScopedQuery(
                    tenant=common_pb2.TenantContext(tenant_id=TENANT_A),
                    query="confidential settlement strategy", top_k=20,
                )
                # (a) tenant A message on a channel authenticated as tenant B -> denied
                try:
                    await stub.Retrieve(request, metadata=(("x-tenant-id", TENANT_B),))
                    mismatch_code = None
                except grpc.aio.AioRpcError as exc:
                    mismatch_code = exc.code()
                # (b) missing metadata -> denied
                try:
                    await stub.Retrieve(request)
                    missing_code = None
                except grpc.aio.AioRpcError as exc:
                    missing_code = exc.code()
                # (c) consistent identity -> only tenant A's private data
                resp = await stub.Retrieve(request, metadata=(("x-tenant-id", TENANT_A),))
                return mismatch_code, missing_code, resp
        finally:
            await server.stop(None)

    mismatch_code, missing_code, resp = run(env, scenario())
    assert mismatch_code == grpc.StatusCode.PERMISSION_DENIED
    assert missing_code in (grpc.StatusCode.INVALID_ARGUMENT, grpc.StatusCode.PERMISSION_DENIED)
    texts = " ".join(c.text for c in resp.chunks)
    assert "ODHIAMBO-CONFIDENTIAL-BRAVO" not in texts
    private = [c for c in resp.chunks
               if c.provenance.source_type == common_pb2.SOURCE_TYPE_TENANT_PRIVATE]
    assert all(c.provenance.source_id != env["docs"][TENANT_B] for c in private)


# --- 4. Erasure cascade ---------------------------------------------------------

def test_erasure_removes_vectors_and_graph_nodes_for_one_tenant_only(env):
    from app import db as dbx
    from app.config import load
    from app.graph import TenantScopedGraphQuery
    from app.ingestion.tenant_ingest import TenantIngestor

    ingestor = TenantIngestor(env["pool"], env["graph"], env["embedder"], env["cfg"])
    nodes, vectors = run(env, ingestor.erase_subject(
        TENANT_A, "client", str(uuid.uuid4()), [env["docs"][TENANT_A]]))
    assert vectors >= 1
    assert nodes >= 1

    # A's data is gone…
    q = (TenantScopedGraphQuery(TENANT_A).match("d", "Archive")
         .returns("d.id AS id").limit(10).build())
    assert env["docs"][TENANT_A] not in {r["id"] for r in run(env, env["graph"].read(q))}
    # …and B's is untouched.
    q = (TenantScopedGraphQuery(TENANT_B).match("d", "Archive")
         .returns("d.id AS id").limit(10).build())
    assert env["docs"][TENANT_B] in {r["id"] for r in run(env, env["graph"].read(q))}

    async def b_still_searchable():
        [qvec] = await env["embedder"].embed(["confidential settlement"])
        async with dbx.tenant_tx(env["pool"], TENANT_B) as conn:
            return await dbx.search_tenant_chunks(conn, qvec, 5)

    assert run(env, b_still_searchable())


# --- 5. Judge-aware retrieval: firm history is tenant-scoped -------------------

async def _seed_judge_history(env, tid, file_id, result, judge="Jane Mwangi"):
    from app.graph import TenantScopedGraphQuery

    graph = env["graph"]
    sub_id = file_id + "-sub"
    await graph.write(
        TenantScopedGraphQuery(tid)
        .merge_node("m", "File", {"id": file_id}, {"judge_name": judge, "case_ref": file_id})
        .merge_node("s", "Submission", {"id": sub_id}, {"filename": "subs.pdf"})
        .merge_rel("s", "FILED_IN", "m").build())
    await graph.write(
        TenantScopedGraphQuery(tid)
        .merge_node("m", "File", {"id": file_id})
        .merge_node("o", "Outcome", {"id": file_id + ":outcome"}, {"result": result, "judge_name": judge})
        .merge_rel("m", "RESULTED_IN", "o").build())
    if result == "won":
        await graph.write(
            TenantScopedGraphQuery(tid)
            .merge_node("s", "Submission", {"id": sub_id})
            .match_public("st", "Statute", doc_id="act-2007-11-employment")
            .merge_rel("s", "CITES", "st").build())


def test_judge_aware_history_is_tenant_scoped(env):
    from app.judge import JudgeReasoner

    reasoner = JudgeReasoner(env["pool"], env["graph"], env["cfg"])
    # Tenant A: a WON file before Jane Mwangi citing the Employment Act.
    run(env, _seed_judge_history(env, TENANT_A, "A-ELC-1-2019", "won"))
    # Tenant B: a LOST file before the same judge, no such authority.
    run(env, _seed_judge_history(env, TENANT_B, "B-ELC-9-2020", "lost"))

    pa = run(env, reasoner.build(TENANT_A, "Jane Mwangi"))
    pb = run(env, reasoner.build(TENANT_B, "Jane Mwangi"))

    # A sees only its own history…
    assert pa.tenant_cases == 1 and pa.tenant_favorable == 1
    assert any("Employment Act" in title for title, _ in pa.winning_authorities)
    # …and B sees only its own — never A's win or A's cited authority.
    assert pb.tenant_cases == 1 and pb.tenant_favorable == 0
    assert pb.winning_authorities == []

    block_b = run(env, reasoner.context_block(TENANT_B, "Jane Mwangi"))
    assert "A-ELC-1-2019" not in block_b
    assert "Employment Act" not in block_b  # LEAKAGE guard


# --- 6. Temporal correctness: law as it stood on a past date ------------------

def test_temporal_versioning_returns_law_in_force_then(env):
    from app import db as dbx
    from app.ingestion.models import LegalDocument, RunReport
    from app.ingestion.pipeline import IngestionPipeline

    pipe = IngestionPipeline(env["pool"], env["graph"], env["embedder"], env["cfg"])
    did = "act-temporal-" + uuid.uuid4().hex[:8]
    run(env, pipe._ingest_doc(LegalDocument(
        doc_id=did, title="Test Levy Act", doc_type="statute", source_url="",
        full_text="Version ONE of the Test Levy Act: the levy is five percent.",
        effective_date="2019-01-01"), RunReport(source_type="statute")))
    run(env, pipe._ingest_doc(LegalDocument(
        doc_id=did, title="Test Levy Act", doc_type="statute", source_url="",
        full_text="Version TWO of the Test Levy Act: the levy is twelve percent.",
        effective_date="2021-06-01"), RunReport(source_type="statute")))

    in_2020 = {d["doc_id"] for d in run(env, dbx.docs_in_force_as_of(env["pool"], "2020-06-01"))}
    in_2022 = {d["doc_id"] for d in run(env, dbx.docs_in_force_as_of(env["pool"], "2022-06-01"))}
    assert f"{did}@v1" in in_2020 and did not in in_2020   # old version in force in 2020
    assert did in in_2022 and f"{did}@v1" not in in_2022    # new version in force in 2022

    async def as_of_text(as_of):
        [qv] = await env["embedder"].embed(["test levy act percent"])
        rows = await dbx.search_public_chunks(env["pool"], qv, 25, False, as_of=as_of)
        return " ".join(r["chunk_text"] for r in rows if did in r["doc_id"])

    assert "Version ONE" in run(env, as_of_text("2020-06-01"))
    assert "Version TWO" in run(env, as_of_text("2022-06-01"))


# --- 7. Auto-update watcher: new law ingested + watermark advanced -------------

def test_auto_update_ingests_new_instrument_and_advances_watermark(env):
    from app import db as dbx
    from app.ingestion.auto_update import AutoUpdateWatcher
    from app.ingestion.models import LegalDocument
    from app.ingestion.pipeline import IngestionPipeline
    from app.ingestion.registry import all_crawlers

    fake = LegalDocument(
        doc_id="gazette-" + uuid.uuid4().hex[:8], title="Legal Notice 42 of 2026",
        doc_type="gazette", source_url="", full_text="A newly gazetted notice under test.",
        effective_date="2026-01-15")
    a_real_source = next(iter(all_crawlers()))

    class OneDocWatcher(AutoUpdateWatcher):
        def _watched_sources(self):
            return [a_real_source]

        async def _fetch(self, crawler, http):
            return [fake]

    pipe = IngestionPipeline(env["pool"], env["graph"], env["embedder"], env["cfg"])
    watcher = OneDocWatcher(env["pool"], pipe, env["cfg"])

    summary = run(env, watcher.run_once())
    assert fake.doc_id in summary["new"]

    row = run(env, dbx.get_public_document(env["pool"], fake.doc_id))
    assert row and row["status"] == "current"

    async def vec_count():
        async with env["pool"].acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM public.public_vectors WHERE doc_id = $1", fake.doc_id)

    assert run(env, vec_count()) >= 1  # embeddings refreshed in the same job
    assert run(env, dbx.get_watermark(env["pool"], AutoUpdateWatcher.SOURCE)) is not None
