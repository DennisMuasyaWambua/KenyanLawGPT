-- Real-time collaborative documents (Google-Docs-style co-editing in Drafting).
-- The Yjs CRDT state lives in `ydoc`, loaded/persisted by the collab sync
-- service (Hocuspocus). Access mirrors archive sharing: owner + shared users +
-- Managing Partner.
CREATE TABLE IF NOT EXISTS collab_documents (
    id         uuid PRIMARY KEY,
    title      text NOT NULL DEFAULT 'Untitled document',
    file_id    uuid REFERENCES files(id) ON DELETE SET NULL,
    owner_id   uuid NOT NULL,
    ydoc       bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS collab_documents_updated ON collab_documents (updated_at DESC);

CREATE TABLE IF NOT EXISTS collab_document_shares (
    document_id uuid NOT NULL REFERENCES collab_documents(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL,
    PRIMARY KEY (document_id, user_id)
);
