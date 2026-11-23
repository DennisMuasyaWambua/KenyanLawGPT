-- Lexical (full-text) index so research can match exact terms (section numbers,
-- party names) alongside dense vectors.
CREATE INDEX IF NOT EXISTS public_vectors_fts ON public_vectors
    USING gin (to_tsvector('english', chunk_text));
