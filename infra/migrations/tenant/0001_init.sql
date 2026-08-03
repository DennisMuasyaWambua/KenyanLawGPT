-- Tenant-schema template. Applied inside "tenant_<uuid>" with
-- search_path = <tenant_schema>, public — every unqualified name below lands
-- in the tenant schema; only the vector type resolves from public.

CREATE TABLE clients (
    id           uuid PRIMARY KEY,
    name         text NOT NULL,
    email        text NOT NULL DEFAULT '',
    phone        text NOT NULL DEFAULT '',
    id_number    text NOT NULL DEFAULT '',
    kdpa_consent boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            uuid PRIMARY KEY,
    email         text NOT NULL,
    full_name     text NOT NULL DEFAULT '',
    role          text NOT NULL CHECK (role IN ('owner','partner','associate','paralegal','client')),
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    client_id     uuid REFERENCES clients(id) ON DELETE SET NULL,
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);
CREATE UNIQUE INDEX users_email_unique ON users (lower(email));

CREATE TABLE refresh_tokens (
    id         uuid PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE matters (
    id                uuid PRIMARY KEY,
    reference         text NOT NULL UNIQUE,
    title             text NOT NULL,
    description       text NOT NULL DEFAULT '',
    client_id         uuid REFERENCES clients(id) ON DELETE SET NULL,
    status            text NOT NULL DEFAULT 'intake'
                      CHECK (status IN ('intake','active','awaiting_court','appeal','closed')),
    practice_area     text NOT NULL DEFAULT '',
    court             text NOT NULL DEFAULT '',
    court_case_number text NOT NULL DEFAULT '',
    assigned_to       uuid REFERENCES users(id) ON DELETE SET NULL,
    opened_at         timestamptz NOT NULL DEFAULT now(),
    closed_at         timestamptz,
    created_by        uuid NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX matters_status ON matters (status, updated_at DESC);

CREATE TABLE matter_events (
    id         uuid PRIMARY KEY,
    matter_id  uuid NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    note       text NOT NULL DEFAULT '',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE court_dates (
    id        uuid PRIMARY KEY,
    matter_id uuid NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    date      timestamptz NOT NULL,
    courtroom text NOT NULL DEFAULT '',
    judge     text NOT NULL DEFAULT '',
    purpose   text NOT NULL DEFAULT '',
    reminded  boolean NOT NULL DEFAULT false
);

CREATE TABLE deadlines (
    id         uuid PRIMARY KEY,
    matter_id  uuid NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    title      text NOT NULL,
    due_at     timestamptz NOT NULL,
    remind_at  timestamptz NOT NULL,
    reminded   boolean NOT NULL DEFAULT false,
    created_by uuid NOT NULL
);

CREATE TABLE documents (
    id            uuid PRIMARY KEY,
    matter_id     uuid REFERENCES matters(id) ON DELETE SET NULL,
    filename      text NOT NULL,
    object_key    text NOT NULL,
    mime_type     text NOT NULL DEFAULT '',
    size_bytes    bigint NOT NULL DEFAULT 0,
    doc_kind      text NOT NULL DEFAULT 'other',
    uploaded_by   uuid NOT NULL,
    ingest_status text NOT NULL DEFAULT 'pending'
                  CHECK (ingest_status IN ('pending','ingesting','ingested','failed')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Per-tenant private vector store (co-located with the tenant's schema).
CREATE TABLE document_chunks (
    id          bigserial PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index int NOT NULL,
    chunk_text  text NOT NULL,
    embedding   vector(1024),
    metadata    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX document_chunks_doc ON document_chunks (document_id);
-- HNSW (see public/0001): correct recall on small/growing tables.
CREATE INDEX document_chunks_embedding_hnsw ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE clause_library (
    id         uuid PRIMARY KEY,
    title      text NOT NULL,
    category   text NOT NULL DEFAULT '',
    body       text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE drafts (
    id         uuid PRIMARY KEY,
    matter_id  uuid REFERENCES matters(id) ON DELETE SET NULL,
    doc_type   text NOT NULL,
    title      text NOT NULL,
    content    text NOT NULL,
    citations  jsonb NOT NULL DEFAULT '[]',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id           uuid PRIMARY KEY,
    matter_id    uuid REFERENCES matters(id) ON DELETE SET NULL,
    client_id    uuid REFERENCES clients(id) ON DELETE SET NULL,
    channel      text NOT NULL CHECK (channel IN ('sms','email','whatsapp','inapp')),
    direction    text NOT NULL CHECK (direction IN ('outbound','inbound')),
    to_addr      text NOT NULL DEFAULT '',
    from_addr    text NOT NULL DEFAULT '',
    body         text NOT NULL,
    status       text NOT NULL DEFAULT 'queued',
    provider_ref text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_client ON messages (client_id, created_at DESC);

CREATE TABLE time_entries (
    id          uuid PRIMARY KEY,
    matter_id   uuid NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL,
    description text NOT NULL,
    minutes     int NOT NULL,
    rate_kes    double precision NOT NULL,
    entry_date  timestamptz NOT NULL DEFAULT now(),
    billed      boolean NOT NULL DEFAULT false
);

CREATE SEQUENCE invoice_seq START 1;

CREATE TABLE invoices (
    id           uuid PRIMARY KEY,
    number       text NOT NULL UNIQUE,
    matter_id    uuid REFERENCES matters(id) ON DELETE SET NULL,
    client_id    uuid NOT NULL REFERENCES clients(id),
    status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','void')),
    subtotal_kes double precision NOT NULL DEFAULT 0,
    vat_kes      double precision NOT NULL DEFAULT 0,
    total_kes    double precision NOT NULL DEFAULT 0,
    issued_at    timestamptz NOT NULL DEFAULT now(),
    due_at       timestamptz,
    paid_at      timestamptz
);

CREATE TABLE invoice_items (
    id            uuid PRIMARY KEY,
    invoice_id    uuid NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description   text NOT NULL,
    quantity      double precision NOT NULL DEFAULT 1,
    unit_kes      double precision NOT NULL DEFAULT 0,
    amount_kes    double precision NOT NULL DEFAULT 0,
    time_entry_id uuid
);

CREATE TABLE payments (
    id                  uuid PRIMARY KEY,
    invoice_id          uuid NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    method              text NOT NULL DEFAULT 'mpesa_stk',
    checkout_request_id text NOT NULL UNIQUE,
    merchant_request_id text NOT NULL DEFAULT '',
    mpesa_receipt       text,
    phone               text NOT NULL DEFAULT '',
    amount_kes          double precision NOT NULL DEFAULT 0,
    status              text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','success','failed')),
    raw                 jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- KDPA consent log (per tenant).
CREATE TABLE consent_log (
    id           uuid PRIMARY KEY,
    subject_type text NOT NULL CHECK (subject_type IN ('client','user')),
    subject_id   text NOT NULL,
    purpose      text NOT NULL,
    granted      boolean NOT NULL,
    granted_by   uuid NOT NULL,
    source       text NOT NULL DEFAULT 'web',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX consent_subject ON consent_log (subject_type, subject_id, created_at DESC);

CREATE TABLE notifications (
    id         uuid PRIMARY KEY,
    user_id    uuid NOT NULL,
    kind       text NOT NULL,
    body       text NOT NULL,
    read       boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
