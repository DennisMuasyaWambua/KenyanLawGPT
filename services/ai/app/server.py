"""WakiliAI AI/RAG service — grpc.aio server (mTLS) + internal health/metrics.

All business traffic is gRPC from the Go gateway. Every RPC re-validates the
TenantContext in the message against the ``x-tenant-id`` channel metadata the
gateway injects — a request whose message and channel identities disagree is
rejected before any data access.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

_GEN = Path(__file__).resolve().parent.parent / "gen"
if str(_GEN) not in sys.path:
    sys.path.insert(0, str(_GEN))

import grpc
from aiohttp import web
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from wakili.v1 import common_pb2, drafting_pb2, drafting_pb2_grpc, ingestion_pb2, \
    ingestion_pb2_grpc, reasoning_pb2, reasoning_pb2_grpc, retrieval_pb2, retrieval_pb2_grpc

from . import db as dbx
from .config import Config, load
from .drafting import DraftingEngine
from .embeddings import make_embedder
from .graph import Graph
from .ingestion.firm_queue import FirmIngestQueue, IngestJob
from .ingestion.pipeline import IngestionPipeline
from .ingestion.scheduler import IngestionScheduler
from .ingestion.tenant_ingest import TenantIngestor
from .llm import make_llm
from .logging_setup import init as log_init, log, trace_id_var
from .reasoning import ReasoningEngine
from .retrieval import RankedChunk, RetrievalOrchestrator
from .tenancy import TenantValidationError, validate_tenant_id

RPC_COUNTER = Counter("wakili_ai_rpcs_total", "RPCs handled", ["method", "status"])

_INTENT_TO_PROTO = {
    "statute_lookup": common_pb2.QUERY_INTENT_STATUTE_LOOKUP,
    "case_law_research": common_pb2.QUERY_INTENT_CASE_LAW_RESEARCH,
    "matter_reasoning": common_pb2.QUERY_INTENT_MATTER_REASONING,
    "drafting": common_pb2.QUERY_INTENT_DRAFTING,
}
_STATUS_TO_PROTO = {
    "current": common_pb2.DOC_STATUS_CURRENT,
    "amended": common_pb2.DOC_STATUS_AMENDED,
    "superseded": common_pb2.DOC_STATUS_SUPERSEDED,
    "overturned": common_pb2.DOC_STATUS_OVERTURNED,
    "distinguished": common_pb2.DOC_STATUS_DISTINGUISHED,
}
_DOCTYPE_TO_KEY = {
    drafting_pb2.DRAFT_DOC_TYPE_PLEADING: "pleading",
    drafting_pb2.DRAFT_DOC_TYPE_AFFIDAVIT: "affidavit",
    drafting_pb2.DRAFT_DOC_TYPE_CONTRACT: "contract",
    drafting_pb2.DRAFT_DOC_TYPE_CORRESPONDENCE: "correspondence",
    drafting_pb2.DRAFT_DOC_TYPE_DEMAND_LETTER: "demand_letter",
}
_STAGE_TO_PROTO = {
    "FETCHING": ingestion_pb2.INGEST_STAGE_FETCHING,
    "PARSING": ingestion_pb2.INGEST_STAGE_PARSING,
    "CHUNKING": ingestion_pb2.INGEST_STAGE_CHUNKING,
    "EMBEDDING": ingestion_pb2.INGEST_STAGE_EMBEDDING,
    "GRAPHING": ingestion_pb2.INGEST_STAGE_GRAPHING,
    "DONE": ingestion_pb2.INGEST_STAGE_DONE,
}


async def check_tenant(tenant_ctx: common_pb2.TenantContext, context: grpc.aio.ServicerContext) -> str:
    """Server-side tenant validation: the message's tenant_id must be a
    canonical UUID AND equal the authenticated channel metadata."""
    md = {k.lower(): v for k, v in context.invocation_metadata() or ()}
    trace_id_var.set(md.get("x-trace-id", ""))
    try:
        tid = validate_tenant_id(tenant_ctx.tenant_id)
        meta_tid = validate_tenant_id(md.get("x-tenant-id", ""))
    except TenantValidationError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"tenant validation: {exc}")
    if tid != meta_tid:
        await context.abort(
            grpc.StatusCode.PERMISSION_DENIED,
            "tenant mismatch between request message and channel metadata",
        )
    return tid


def chunk_to_proto(c: RankedChunk) -> common_pb2.ContextChunk:
    return common_pb2.ContextChunk(
        chunk_id=c.chunk_id,
        text=c.text,
        score=c.score,
        provenance=common_pb2.Provenance(
            source_type=(common_pb2.SOURCE_TYPE_PUBLIC if c.source_type == "PUBLIC"
                         else common_pb2.SOURCE_TYPE_TENANT_PRIVATE),
            source_id=c.source_id,
            citation=c.citation,
            source_url=c.source_url,
            status=_STATUS_TO_PROTO.get(c.status, common_pb2.DOC_STATUS_CURRENT),
            court=c.court,
            year=c.year,
        ),
        metadata={k: str(v) for k, v in c.metadata.items()},
    )


class RetrievalService(retrieval_pb2_grpc.RetrievalServiceServicer):
    def __init__(self, orchestrator: RetrievalOrchestrator) -> None:
        self.orchestrator = orchestrator

    async def Retrieve(self, request, context):
        tid = await check_tenant(request.tenant, context)
        try:
            chunks, intent = await self.orchestrator.retrieve(
                tid, request.query,
                top_k=request.top_k or 12,
                include_superseded=request.include_superseded,
                matter_id=request.matter_id or None,
            )
            answer = await self.orchestrator.answer(request.query, chunks, intent)
            RPC_COUNTER.labels("Retrieve", "ok").inc()
            return retrieval_pb2.RankedContext(
                chunks=[chunk_to_proto(c) for c in chunks],
                classified_intent=_INTENT_TO_PROTO.get(intent, common_pb2.QUERY_INTENT_UNSPECIFIED),
                answer=answer,
                trace_id=request.trace_id,
            )
        except Exception:
            RPC_COUNTER.labels("Retrieve", "error").inc()
            log().exception("Retrieve failed")
            await context.abort(grpc.StatusCode.INTERNAL, "retrieval failed")


class ReasoningService(reasoning_pb2_grpc.ReasoningServiceServicer):
    def __init__(self, engine: ReasoningEngine) -> None:
        self.engine = engine

    async def Reason(self, request, context):
        tid = await check_tenant(request.tenant, context)
        try:
            steps, evidence, answer = await self.engine.reason(
                tid, request.query,
                max_hops=request.max_hops or 3,
                matter_id=request.matter_id or None,
                include_superseded=request.include_superseded,
            )
            RPC_COUNTER.labels("Reason", "ok").inc()
            return reasoning_pb2.ReasoningTrace(
                steps=[reasoning_pb2.ReasoningStep(
                    hop=s.hop, description=s.description,
                    node_ids=s.node_ids, edge_types=s.edge_types,
                ) for s in steps],
                context=[chunk_to_proto(c) for c in evidence],
                answer=answer,
                trace_id=request.trace_id,
            )
        except Exception:
            RPC_COUNTER.labels("Reason", "error").inc()
            log().exception("Reason failed")
            await context.abort(grpc.StatusCode.INTERNAL, "reasoning failed")


class DraftingService(drafting_pb2_grpc.DraftingServiceServicer):
    def __init__(self, engine: DraftingEngine) -> None:
        self.engine = engine

    async def DraftDocument(self, request, context):
        tid = await check_tenant(request.tenant, context)
        doc_type = _DOCTYPE_TO_KEY.get(request.doc_type, "correspondence")
        try:
            stream, citations = await self.engine.draft(
                tid, doc_type, request.instructions,
                matter_id=request.matter_id or None,
                template_id=request.template_id or None,
                context_query=request.context_query or None,
            )
            async for token in stream:
                yield drafting_pb2.DraftChunk(text=token, is_final=False)
            final = drafting_pb2.DraftChunk(is_final=True, draft_id=str(uuid.uuid4()))
            for c in citations:
                final.citations.append(chunk_to_proto(c).provenance)
            RPC_COUNTER.labels("DraftDocument", "ok").inc()
            yield final
        except Exception:
            RPC_COUNTER.labels("DraftDocument", "error").inc()
            log().exception("DraftDocument failed")
            await context.abort(grpc.StatusCode.INTERNAL, "drafting failed")


class IngestionService(ingestion_pb2_grpc.IngestionServiceServicer):
    def __init__(self, ingestor: TenantIngestor, firm_queue: FirmIngestQueue, cfg: Config) -> None:
        self.ingestor = ingestor
        self.firm_queue = firm_queue
        self.cfg = cfg

    async def IngestDocument(self, request, context):
        tid = await check_tenant(request.tenant, context)
        # Queue-based path (async, decoupled from the upload): enqueue then tail
        # the job's status so the caller *may* watch progress but the actual
        # parsing/embedding runs in a background worker and survives disconnect.
        if self.cfg.enable_firm_ingestion:
            try:
                async for status in self._ingest_async(tid, request):
                    yield status
                RPC_COUNTER.labels("IngestDocument", "ok").inc()
            except Exception as exc:
                RPC_COUNTER.labels("IngestDocument", "error").inc()
                log().exception("IngestDocument (async) failed")
                yield ingestion_pb2.IngestStatus(
                    stage=ingestion_pb2.INGEST_STAGE_FAILED,
                    message="ingestion failed", error=str(exc), done=True,
                )
            return

        # Legacy inline path (flag off): run synchronously in the RPC.
        try:
            async for stage, message, pct in self.ingestor.ingest(
                tid, request.document_id, request.object_key,
                request.filename, request.mime_type, request.matter_id or None,
            ):
                yield ingestion_pb2.IngestStatus(
                    stage=_STAGE_TO_PROTO.get(stage, ingestion_pb2.INGEST_STAGE_UNSPECIFIED),
                    message=message, progress_pct=pct, done=(stage == "DONE"),
                )
            RPC_COUNTER.labels("IngestDocument", "ok").inc()
        except Exception as exc:
            RPC_COUNTER.labels("IngestDocument", "error").inc()
            log().exception("IngestDocument failed")
            yield ingestion_pb2.IngestStatus(
                stage=ingestion_pb2.INGEST_STAGE_FAILED,
                message="ingestion failed", error=str(exc), done=True,
            )

    async def _ingest_async(self, tid, request):
        await self.firm_queue.enqueue(IngestJob(
            tenant_id=tid, document_id=request.document_id,
            object_key=request.object_key, filename=request.filename,
            mime_type=request.mime_type, matter_id=request.matter_id or None,
            trace_id=request.trace_id or "",
        ))
        yield ingestion_pb2.IngestStatus(
            stage=ingestion_pb2.INGEST_STAGE_FETCHING,
            message="queued for async ingestion", progress_pct=0, done=False,
        )
        last = None
        for _ in range(600):  # tail up to ~5min; the worker continues regardless
            await asyncio.sleep(0.5)
            status = await self.firm_queue.get_status(request.document_id)
            if not status or status == last:
                continue
            last = status
            failed = status["stage"] == "FAILED"
            yield ingestion_pb2.IngestStatus(
                stage=(ingestion_pb2.INGEST_STAGE_FAILED if failed
                       else _STAGE_TO_PROTO.get(status["stage"], ingestion_pb2.INGEST_STAGE_UNSPECIFIED)),
                message=status["message"], progress_pct=status["progress_pct"],
                done=status["done"], error=status.get("error", ""),
            )
            if status["done"]:
                return

    async def EraseSubject(self, request, context):
        tid = await check_tenant(request.tenant, context)
        try:
            nodes, vectors = await self.ingestor.erase_subject(
                tid, request.subject_type, request.subject_id, list(request.document_ids),
            )
            RPC_COUNTER.labels("EraseSubject", "ok").inc()
            return ingestion_pb2.EraseSubjectReport(
                graph_nodes_deleted=nodes, vector_rows_deleted=vectors,
            )
        except Exception:
            RPC_COUNTER.labels("EraseSubject", "error").inc()
            log().exception("EraseSubject failed")
            await context.abort(grpc.StatusCode.INTERNAL, "erasure cascade failed")


# --- assembly -----------------------------------------------------------------

class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.pool = None
        self.graph = None
        self.scheduler = None
        self.firm_queue = None
        self.server = None

    async def build_server(self) -> grpc.aio.Server:
        self.pool = await dbx.init_pool(self.cfg.database_url)
        self.graph = Graph(self.cfg)
        await self.graph.ensure_indexes()

        embedder = make_embedder(self.cfg)
        llm = make_llm(self.cfg)
        retriever = RetrievalOrchestrator(self.pool, self.graph, embedder, llm, self.cfg)
        reasoner = ReasoningEngine(self.pool, self.graph, retriever, llm, self.cfg)
        drafter = DraftingEngine(self.pool, retriever, llm, self.cfg)
        ingestor = TenantIngestor(self.pool, self.graph, embedder, self.cfg)

        pipeline = IngestionPipeline(self.pool, self.graph, embedder, self.cfg)
        self.scheduler = IngestionScheduler(pipeline, self.cfg)
        self.firm_queue = FirmIngestQueue(ingestor, self.cfg)

        server = grpc.aio.server()
        retrieval_pb2_grpc.add_RetrievalServiceServicer_to_server(RetrievalService(retriever), server)
        reasoning_pb2_grpc.add_ReasoningServiceServicer_to_server(ReasoningService(reasoner), server)
        drafting_pb2_grpc.add_DraftingServiceServicer_to_server(DraftingService(drafter), server)
        ingestion_pb2_grpc.add_IngestionServiceServicer_to_server(
            IngestionService(ingestor, self.firm_queue, self.cfg), server)

        addr = f"[::]:{self.cfg.grpc_port}"
        if self.cfg.mtls_disabled:
            log().warning("MTLS_DISABLED=true — serving plaintext gRPC (tests/dev only)")
            server.add_insecure_port(addr)
        else:
            ca = Path(self.cfg.mtls_ca_cert).read_bytes()
            cert = Path(self.cfg.mtls_server_cert).read_bytes()
            key = Path(self.cfg.mtls_server_key).read_bytes()
            creds = grpc.ssl_server_credentials(
                [(key, cert)], root_certificates=ca, require_client_auth=True,
            )
            server.add_secure_port(addr, creds)
        self.server = server
        return server

    async def health_app(self) -> web.Application:
        async def healthz(_request):
            try:
                async with self.pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                return web.json_response({"status": "ok"})
            except Exception as exc:
                return web.json_response({"status": "degraded", "error": str(exc)}, status=503)

        async def metrics(_request):
            return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST.split(";")[0])

        app = web.Application()
        app.router.add_get("/healthz", healthz)
        app.router.add_get("/metrics", metrics)
        return app


async def serve() -> None:
    cfg = load()
    log_init(cfg.env)
    app = App(cfg)
    server = await app.build_server()
    await server.start()
    log().info("AI service listening on :%d (mTLS %s)", cfg.grpc_port,
               "disabled" if cfg.mtls_disabled else "enabled")

    runner = web.AppRunner(await app.health_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", cfg.health_port)
    await site.start()

    await app.scheduler.start()
    if cfg.enable_firm_ingestion:
        await app.firm_queue.start()
    else:
        log().info("ENABLE_FIRM_INGESTION=false — firm ingestion queue not started")
    try:
        await server.wait_for_termination()
    finally:
        if cfg.enable_firm_ingestion:
            await app.firm_queue.stop()
        await app.scheduler.stop()
        await app.graph.close()
        await app.pool.close()


if __name__ == "__main__":
    asyncio.run(serve())
