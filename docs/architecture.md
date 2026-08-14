# Advocatus — Architecture Notes

Companion to the README; this covers the decisions that matter for extending
the system safely.

## Request path

```
Browser ── REST/SSE (JWT bearer, X-Tenant-Slug, X-Request-ID) ──▶ Gin gateway
  middleware chain: RequestID → CORS → metrics → Tenant → RateLimit → Auth → RBAC → Audit
  handlers → repository (pgx, SET LOCAL search_path) ──▶ Postgres
           → grpcclient (mTLS, x-tenant-id/x-trace-id metadata) ──▶ Python AI
Python AI: check_tenant (message⇄metadata cross-check) → orchestrators
           → asyncpg (tenant_tx) / Neo4j (builder-only Cypher) / LLMProvider
```

The trace id minted (or forwarded) by the gateway flows into every log line
of both services and back to the browser via `X-Request-ID`.

## Isolation layers (defense in depth)

1. **Identity**: JWT carries `tid`; the tenant middleware resolves the
   subdomain slug to a tenant row; mismatch ⇒ 403 (unit-tested).
2. **SQL**: `db.WithTenant` / `tenant_tx` validate `^tenant_[0-9a-f]{32}$`
   then `SET LOCAL search_path`. No repository function accepts a schema name.
3. **RLS**: `public.audit_log` policies on `app.tenant_id` GUC; the app role
   is non-superuser and non-owner so policies bind.
4. **Graph**: only `TenantScopedGraphQuery`-built Cypher can touch tenant
   nodes; every pattern carries `{tenant_id: $tenant_id}`, every var-length
   path carries the `all(...)` guard; `Graph.read/write` refuse queries that
   don't carry the module-private builder token; request-path public access
   is read-only by construction.
5. **Objects**: tenant prefix enforced at signing (gateway) and at read (AI).
6. **gRPC**: channel metadata must equal message TenantContext, revalidated
   server-side in Python.

Escalation path for Neo4j Enterprise/Aura: give `Graph` a
`session(database=f"tenant_{...}")` per tenant and keep the property filters
— both layers then have to fail simultaneously for a leak.

## Graph model

Public partition (`:Public`, no tenant_id):

```
(Statute)-[:SUPERSEDED_BY]->(Statute)          versioning chain (@v archives)
(Statute)<-[:AMENDS|INTERPRETS|CITES]-(CaseLaw)
(CaseLaw)-[:OVERTURNS|DISTINGUISHES]->(CaseLaw)
(Judge)-[:AUTHORED]->(Opinion)-[:PART_OF]->(CaseLaw|Judgment)   dissents are first-class
```

Tenant partition (every node/edge stamped `tenant_id`):

```
(Matter)-[:LINKED_TO]->(Document)
(Matter)-[:INVOLVES]->(Party)
(Document)-[:CITES]->(Statute:Public)          cross-partition edge (allowed direction)
(PrecedentNote)-[:SIMILAR_TO]->(CaseLaw:Public)
```

Cross-partition edges always point tenant → public; traversals from tenant
scope may *visit* public nodes but the `all(...)` guard prevents continuing
into another tenant's stamped nodes on the far side.

## Retrieval scoring

`score = cosine × status × intent-boost × matter-boost`, where
status = 1.0 for `current`, 0.45 for superseded unless the caller asked for
historical context; intent boosts favor statutes for statute-lookup and
case law for research; matter-boost (×1.25) applies to documents the tenant
graph links to the anchor matter. Treatment notes from AMENDS/OVERTURNS
neighbors are appended to chunk text so the synthesizer must confront them.

## Payments (Daraja) correctness

`payments.checkout_request_id` is UNIQUE; the callback settles via a single
`UPDATE … WHERE status='pending' RETURNING`, so replays are no-ops
(idempotent webhook). The reconcile loop queries `stkpushquery` for payments
stuck pending >5 min (missed callbacks) and settles through the same CAS.
The callback URL carries `?tenant=<slug>`; a full-scan fallback covers
misrouted callbacks since checkout ids are globally unique.

## Adding a public corpus source

```python
@register
class TribunalCrawler(BaseCrawler):
    source_type = "tribunal"
    schedule = "weekly"
    async def fetch(self, http): ...   # yield LegalDocument(...)
    def samples(self): ...             # offline fixtures
```

Nothing else changes — the scheduler and pipeline discover it via the
registry, and its docs flow through hashing/versioning/embedding/graphing
identically.

## Known dev-mode simplifications

- Hashing embedder (no key): real cosine behavior on shared vocabulary, not
  semantic embeddings — good enough for isolation tests and demos.
- Mock LLM (no key): deterministic, watermarked output.
- SMS/email log-only without provider creds; WhatsApp stored-only.
- Judiciary mock adapter unless `JUDICIARY_BASE_URL` is set.
- `mc`/curl-based healthchecks and single-node infra are compose-dev only.
