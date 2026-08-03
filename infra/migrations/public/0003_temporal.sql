-- Task 5: temporal versioning of public law + auto-update watermark.
-- Superseded/repealed provisions are never deleted — they are date-stamped so
-- "what did the law say on <date>" (and the judge-reasoning feature) stays
-- historically accurate.

ALTER TABLE public_documents ADD COLUMN IF NOT EXISTS effective_date date;
ALTER TABLE public_documents ADD COLUMN IF NOT EXISTS repealed_date  date;

-- Allow a 'repealed' lifecycle state alongside the existing ones.
ALTER TABLE public_documents DROP CONSTRAINT IF EXISTS public_documents_status_check;
ALTER TABLE public_documents ADD CONSTRAINT public_documents_status_check
    CHECK (status IN ('current','amended','superseded','overturned','distinguished','repealed'));

CREATE INDEX IF NOT EXISTS public_documents_effective ON public_documents (effective_date);
CREATE INDEX IF NOT EXISTS public_documents_repealed  ON public_documents (repealed_date);

-- Per-source high-water mark so the auto-update watcher only fetches
-- instruments published/changed since its last successful run.
CREATE TABLE IF NOT EXISTS ingestion_watermark (
    source_type      text PRIMARY KEY,
    last_ingested_at timestamptz NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion_watermark TO wakili_app;
