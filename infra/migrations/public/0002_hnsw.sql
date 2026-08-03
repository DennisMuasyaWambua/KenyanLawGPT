-- Replace the ivfflat index (poor recall when built on an empty table) with
-- HNSW on deployments migrated before 0001 was corrected. No-op on fresh DBs.
DROP INDEX IF EXISTS public_vectors_embedding;
CREATE INDEX IF NOT EXISTS public_vectors_embedding_hnsw ON public_vectors
    USING hnsw (embedding vector_cosine_ops);
