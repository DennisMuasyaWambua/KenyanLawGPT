-- Replace the ivfflat index with HNSW (see public/0002_hnsw.sql).
DROP INDEX IF EXISTS document_chunks_embedding;
CREATE INDEX IF NOT EXISTS document_chunks_embedding_hnsw ON document_chunks
    USING hnsw (embedding vector_cosine_ops);
