# Advocatus

Production-grade, multi-tenant legal SaaS for Kenyan law firms: practice
management, hybrid graph+vector AI legal research over Kenyan law, streaming
document drafting, client communications, M-Pesa billing, and KDPA compliance
— one shared deployment, strict per-firm data isolation.

```
Next.js (per-tenant subdomain) ──REST/SSE──▶ Go API Gateway (Gin)
                                                 │  JWT+RBAC · tenant resolver · audit · rate limit
                                                 │  integrations: Daraja, Africa's Talking,
                                                 │  Judiciary adapter, email, object storage
                                                 └──gRPC + mTLS (sole caller)──▶ Python AI/RAG service
                                                                                   │ retrieval orchestrator
                                                                                   │ graph reasoning engine
                                                                                   │ streaming drafting engine
                                                                                   │ self-updating corpus pipeline
                     PostgreSQL 16 + pgvector ◀──┴──▶ Neo4j 5 ◀──┘   MinIO/R2 · Redis
                     (schema-per-tenant + shared      (public law graph +
                      public corpus)                   per-tenant partitions)
```

## Quickstart (one command)

Prereqs: Docker + Docker Compose, `openssl`, `make`.

```bash
cp .env.example .env      # optional — everything runs offline with no keys
make up                   # certs -> build -> up -> migrations
make seed                 # provisions the 2 demo firms + demo data
```

Published ports: frontend `3000`, gateway `8080`, AI health `8081`, gRPC
`50051`, Neo4j `7474/7687`, and — shifted to avoid clashing with locally
installed services — Postgres `55432`, Redis `56379`, MinIO `59000`
(console `59001`).

Then open **http://localhost:3000** and sign in (password `DemoPass123!` for
all demo users):

| Firm | Slug | Users |
|---|---|---|
| Mwangi & Co. Advocates | `mwangi-advocates` | `owner@…`, `partner@…`, `associate@…`, `paralegal@…`, `client@…` `.demo` |
| Odhiambo Partners LLP | `odhiambo-partners` | same pattern |

The two firms are seeded with **deliberately distinguishable confidential
data** (`MWANGI-CONFIDENTIAL-ALPHA` vs `ODHIAMBO-CONFIDENTIAL-BRAVO` inside
their private precedent notes) so you can verify isolation by hand: log into
each firm, run the same AI Research query ("confidential settlement strategy
for unfair termination"), and observe that each firm only ever retrieves its
own marker.

### Demo tour

1. **Dashboard** — live stats per firm.
2. **Matters** — Kanban + list, timeline, court dates, deadlines; "Check
   Judiciary status" uses the pluggable adapter (deterministic mock unless
   `JUDICIARY_BASE_URL` is set); upload a document and watch it go
   pending → ingesting → ingested (chunked, embedded, graph-linked).
3. **AI Research** — hybrid retrieval with citation cards tagged
   **Public law** vs **Firm confidential**; "Graph reasoning" mode shows the
   hop-by-hop trace, including amendment/overturn treatment of authorities.
4. **Drafting** — pick a matter, give instructions, watch the pleading /
   demand letter stream token-by-token (Next.js ← SSE ← Go ← gRPC stream ←
   Python ← Claude), grounded citations attached at the end.
5. **Communications** — unified SMS/email/WhatsApp/in-app timeline
   (log-only SMS/email in dev; delivery webhooks update statuses).
6. **Billing** — log time → invoice (16% VAT) → **M-Pesa STK push**
   (needs Daraja sandbox creds) with idempotent callback + reconciliation.
7. **Settings** — team & roles (5-role RBAC), KDPA consent flags,
   **Export** (subject-access JSON) and **Erase** (cascades across Postgres,
   MinIO, pgvector and Neo4j).
8. **Client portal** — sign in as `client@…` to see the scoped view.

## Tests

```bash
make test              # unit: Go (schema-name gate, JWT, RBAC, cross-tenant REST) + Python (builders, tenancy, embeddings)
make test-integration  # cross-tenant LEAKAGE suite — needs `make up` first
```

The leakage suite (`services/ai/tests/test_leakage_integration.py`) provisions
two fake tenants with distinguishable secrets and asserts, under both the data
layer and the gRPC path:

- vector search never returns the other tenant's chunks;
- graph reads and **multi-hop traversals** never cross tenants, *even through
  shared public-law nodes both tenants cite*;
- a valid tenant-A request on a channel authenticated as tenant-B is rejected
  (`PERMISSION_DENIED`);
- KDPA erasure removes one tenant's vectors/graph nodes and leaves the other
  untouched.

The REST-path equivalent lives in
`services/gateway/internal/middleware/middleware_test.go` (tenant-A JWT on
tenant-B subdomain ⇒ 403).

## Multi-tenancy design (the part that must not fail)

**Postgres — schema-per-tenant.** Each firm gets `tenant_<uuid>`; a control
table `public.tenants` maps slug → schema. Every request runs inside a
transaction that pins `SET LOCAL search_path` from the *authenticated* tenant
record (never request input); schema names must match
`^tenant_[0-9a-f]{32}$` before they touch SQL. The JWT's tenant claim is
cross-checked against the subdomain-resolved tenant on every request.
`public.audit_log` (schema-shared) adds **row-level security** on a
per-transaction `app.tenant_id` GUC; the app connects as the non-superuser
`wakili_app` role so RLS binds.

**Neo4j — two logical partitions in one database.**
`:Public`-labeled nodes form the shared read-only law graph; tenant nodes all
carry `tenant_id`. Application code cannot hand-write Cypher: tenant queries
must be composed through **`TenantScopedGraphQuery`** (injects
`{tenant_id: $tenant_id}` into every pattern and an
`all(x IN nodes(path) WHERE x:Public OR x.tenant_id = $tenant_id)` guard on
every variable-length hop), and public reads go through the write-less
**`PublicGraphQuery`**. The Neo4j client executes *only* builder-produced
queries (capability token), and public-graph writes exist solely inside the
batch ingestion pipeline. On Enterprise/Aura, sessions can additionally pin a
per-tenant database; the property filter stays on as defense-in-depth.

**Object storage** — single bucket, enforced `tenants/<tenant_id>/` prefix;
only the gateway signs URLs; the AI service refuses to read outside the
caller's prefix.

**gRPC** — the gateway attaches `x-tenant-id` metadata from the authenticated
tenant; the Python service re-validates that the message's `TenantContext`
matches the channel metadata before any data access.

## Public corpus pipeline (self-updating)

Registry of per-source crawlers (constitution, legislation, case law with
**per-judge opinions/dissents as separate nodes**, gazette, LSK guidance,
cause lists — add a source type by writing one `@register` class). Daily
bucket (gazette, cause lists) and weekly bucket run on a standing scheduler;
change detection is by content hash. On change, the prior version is archived
as `<doc_id>@v<n>` with status `superseded` and linked via `SUPERSEDED_BY`;
explicit `AMENDS` / `OVERTURNS` / `DISTINGUISHES` edges update the target's
status, and retrieval **prefers current law by default**, surfacing
superseded authority only on request (UI toggle) — with "[NOTE: related
version/treatment …]" annotations when a retrieved source has treatment
edges. Every run writes an auditable `ingestion_runs` report row.

Dev default is `INGEST_OFFLINE_SAMPLES=true`: a built-in sample corpus of
real Kenyan law (Constitution arts. 41/47/50/159, Employment Act ss.
35/41/45/49 + a 2022 amendment exercising the AMENDS chain, Walter Ogal
Anuro, Kenfreight (SC) including Njoki SCJ's dissent, a gazette notice, LSK
guidance, an ELRC cause list) so the demo works offline. Set it `false` to
crawl kenyalaw.org live.

## Key decisions & assumptions (per the "decide and document" instruction)

| Decision | Choice | Notes |
|---|---|---|
| LLM | **Claude Opus 4.8** (`claude-opus-4-8`) via the official Anthropic SDK, adaptive thinking; Haiku 4.5 for intent classification | Swappable `LLMProvider`; with no API key the deterministic **mock provider** keeps every flow demoable offline |
| Embeddings | **voyage-law-2** (legal-domain, 1024-dim) when `VOYAGE_API_KEY` set; deterministic hashing embedder otherwise | Same pgvector columns either way (`EMBEDDING_DIM=1024`) |
| Graph tenancy | Property-based partitions + builder enforcement on Neo4j Community | Multi-database isolation slot-in for Enterprise/Aura documented in `app/graph/builders.py` |
| Migrations | Small dependency-free SQL runner (`cmd/migrate`) instead of golang-migrate | Public via admin role, tenant schemas via app role; per-schema `schema_migrations` tracking |
| Postgres access | `pgx/v5` directly (no sqlc) | One idiom everywhere; `SET LOCAL` keeps pooled connections tenant-clean |
| Streaming to browser | SSE over `fetch` (POST) rather than WebSocket | Matches gRPC server-streaming 1:1; no socket state to shard |
| Judiciary | `Adapter` interface; portal scraper impl w/ Redis last-known-status fallback; deterministic mock when unconfigured | No stable public API exists — mock is clearly watermarked |
| WhatsApp | Stored in the unified hub, not delivered | Delivery is a provider swap (same interface as SMS) |
| Email | SMTP provider behind an interface; log-only in dev | |
| Auth cookies vs headers | Tokens returned in JSON and used as Bearer headers by the SPA (dev runs on two ports); httpOnly cookies also set for same-site deployments | |

## Repo layout

```
proto/wakili/v1/          versioned gRPC contracts (5 files)
services/gateway/         Go: cmd/{gateway,migrate,seed}, internal/{handlers,services,
                          repository,middleware,grpcclient,db,auth,rbac,integrations,…}, gen/ stubs
services/ai/              Python: app/{server,retrieval,reasoning,drafting,graph,
                          ingestion,embeddings,llm,db,tenancy}, gen/ stubs, tests/
frontend/                 Next.js App Router + Tailwind + TanStack Query
infra/                    migrations (public + tenant template), certs script,
                          postgres init, docker-compose glue
docs/architecture.md      deep dive
```

## Operations

- `make proto` — regenerate Go+Python stubs after editing `/proto`.
- `make logs` — tail gateway + AI logs (JSON, `trace_id`-correlated end to end).
- Metrics: `:8080/metrics` (gateway) and `:8081/metrics` (AI, Prometheus).
- Secrets: env-only (`.env` is gitignored); mTLS certs generated locally by
  `make certs`, never committed. Production: real PKI, rotate leaf certs
  against the CA and restart; JWT_SECRET + DB/MinIO credentials from a
  secrets manager; run Postgres with the non-superuser app role as shipped.
- KDPA: consent log + audit trail per firm; export & erasure endpoints under
  `/api/v1/kdpa/*` (partner+); erasure cascades DB → storage → graph → vectors.
