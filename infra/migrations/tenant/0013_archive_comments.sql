-- Document collaboration: threaded comments on an archived document.
CREATE TABLE IF NOT EXISTS archive_comments (
    id         uuid PRIMARY KEY,
    archive_id uuid NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL,
    body       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS archive_comments_doc ON archive_comments (archive_id, created_at);
