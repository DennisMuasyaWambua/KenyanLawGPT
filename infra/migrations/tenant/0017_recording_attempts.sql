-- Poison-pill guard for the recording worker: a file that crashes the AI process
-- (e.g. OOM on a very long recording) would otherwise be retried on every restart
-- forever. The worker bumps this before each attempt and gives up after a few.
ALTER TABLE meeting_recordings ADD COLUMN IF NOT EXISTS attempts int NOT NULL DEFAULT 0;
