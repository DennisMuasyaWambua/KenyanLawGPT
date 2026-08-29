-- Document version history + per-document sharing (collaboration slices).
--
-- Versioning: re-uploading as a new version creates a fresh archives row that
-- points at the one it replaces (previous_id) and marks the old one superseded;
-- lists show only current (non-superseded) rows.
-- Sharing: a document can be marked restricted, visible only to its uploader,
-- explicitly-shared users and the Managing Partner.
ALTER TABLE archives ADD COLUMN IF NOT EXISTS version     int     NOT NULL DEFAULT 1;
ALTER TABLE archives ADD COLUMN IF NOT EXISTS superseded  boolean NOT NULL DEFAULT false;
ALTER TABLE archives ADD COLUMN IF NOT EXISTS previous_id uuid REFERENCES archives(id) ON DELETE SET NULL;
ALTER TABLE archives ADD COLUMN IF NOT EXISTS restricted  boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS archive_shares (
    archive_id uuid NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL,
    PRIMARY KEY (archive_id, user_id)
);
