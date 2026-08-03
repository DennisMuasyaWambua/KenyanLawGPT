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
                    "INSERT INTO documents (id, filename, object_key, mime_type, doc_kind, uploaded_by, ingest_status) "
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
                 .merge_node("d", "Document", {"id": doc_id}, {"filename": "note.txt"})
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
         .match("d", "Document").returns("d.id AS id").limit(100).build())
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
         .match("d", "Document", id=env["docs"][TENANT_A])
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
    q = (TenantScopedGraphQuery(TENANT_A).match("d", "Document")
         .returns("d.id AS id").limit(10).build())
    assert env["docs"][TENANT_A] not in {r["id"] for r in run(env, env["graph"].read(q))}
    # …and B's is untouched.
    q = (TenantScopedGraphQuery(TENANT_B).match("d", "Document")
         .returns("d.id AS id").limit(10).build())
    assert env["docs"][TENANT_B] in {r["id"] for r in run(env, env["graph"].read(q))}

    async def b_still_searchable():
        [qvec] = await env["embedder"].embed(["confidential settlement"])
        async with dbx.tenant_tx(env["pool"], TENANT_B) as conn:
            return await dbx.search_tenant_chunks(conn, qvec, 5)

    assert run(env, b_still_searchable())
