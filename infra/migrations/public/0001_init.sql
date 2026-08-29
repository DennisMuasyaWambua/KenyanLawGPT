-- Public (shared) schema: tenant control table, subscription plans, the
-- KDPA audit trail (RLS-guarded), and the shared public legal corpus.
-- Applied by cmd/migrate with the admin role.

CREATE TABLE IF NOT EXISTS plans (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    price_kes   numeric NOT NULL DEFAULT 0,
    limits      jsonb NOT NULL DEFAULT '{}'
);

INSERT INTO plans (code, name, price_kes, limits) VALUES
    ('starter',        'Starter',        4500,  '{"users": 3,  "files": 50}'),
    ('chambers',       'Chambers',       14500, '{"users": 15, "files": 1000}'),
    ('senior-counsel', 'Senior Counsel', 39500, '{"users": 100,"files": -1}')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS tenants (
    id                uuid PRIMARY KEY,
    name              text NOT NULL,
    slug              text NOT NULL UNIQUE,
    schema_name       text NOT NULL UNIQUE,
    plan              text NOT NULL DEFAULT 'starter' REFERENCES plans(code),
    data_residency_ke boolean NOT NULL DEFAULT true,
    status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- Audit log is schema-shared (cross-tenant ops need it), so it gets
-- row-level security keyed on the per-transaction app.tenant_id GUC as
-- defense-in-depth on top of schema isolation.
CREATE TABLE IF NOT EXISTS audit_log (
    id         uuid PRIMARY KEY,
    tenant_id  uuid NOT NULL,
    user_id    uuid,
    action     text NOT NULL,
    resource   text NOT NULL DEFAULT '',
    status     int  NOT NULL DEFAULT 0,
    ip         text NOT NULL DEFAULT '',
    trace_id   text NOT NULL DEFAULT '',
    detail     jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_tenant_time ON audit_log (tenant_id, created_at DESC);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_tenant_isolation ON audit_log;
CREATE POLICY audit_tenant_isolation ON audit_log
    USING (tenant_id::text = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));

-- Shared public legal corpus (Kenyan statutes, case law, gazette, LSK…).
-- Amended/overturned law is never overwritten: prior versions are archived
-- under doc_id || '@v' || version with an explicit status.
CREATE TABLE IF NOT EXISTS public_documents (
    doc_id       text PRIMARY KEY,
    title        text NOT NULL,
    doc_type     text NOT NULL,
    source_url   text NOT NULL DEFAULT '',
    court        text NOT NULL DEFAULT '',
    citation     text NOT NULL DEFAULT '',
    year         int  NOT NULL DEFAULT 0,
    status       text NOT NULL DEFAULT 'current'
                 CHECK (status IN ('current','amended','superseded','overturned','distinguished')),
    version      int  NOT NULL DEFAULT 1,
    content_hash text NOT NULL,
    authored_by  jsonb NOT NULL DEFAULT '[]',
    metadata     jsonb NOT NULL DEFAULT '{}',
    full_text    text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS public_documents_status ON public_documents (status, doc_type);

CREATE TABLE IF NOT EXISTS public_vectors (
    id          bigserial PRIMARY KEY,
    doc_id      text NOT NULL REFERENCES public_documents(doc_id)
                ON UPDATE CASCADE ON DELETE CASCADE,
    chunk_index int  NOT NULL,
    chunk_text  text NOT NULL,
    embedding   vector(1024),
    metadata    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS public_vectors_doc ON public_vectors (doc_id);
-- HNSW (not ivfflat): builds incrementally with full recall from row one —
-- ivfflat trained on an empty table probes mostly-empty lists and drops rows.
CREATE INDEX IF NOT EXISTS public_vectors_embedding_hnsw ON public_vectors
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id              bigserial PRIMARY KEY,
    source_type     text NOT NULL,
    new_docs        int NOT NULL DEFAULT 0,
    amended_docs    int NOT NULL DEFAULT 0,
    superseded_docs int NOT NULL DEFAULT 0,
    unchanged_docs  int NOT NULL DEFAULT 0,
    errors          jsonb NOT NULL DEFAULT '[]',
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);

-- App role privileges (RLS still binds on audit_log because wakili_app is
-- neither owner nor superuser).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO wakili_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO wakili_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO wakili_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO wakili_app;
