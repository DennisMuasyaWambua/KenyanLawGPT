-- Lexical (full-text) index for hybrid research over firm documents.
CREATE INDEX IF NOT EXISTS archive_chunks_fts ON archive_chunks
    USING gin (to_tsvector('english', chunk_text));
