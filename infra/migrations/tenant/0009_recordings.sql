-- Meeting recordings: consent-gated audio, transcribed (local Whisper) and
-- summarized (local LLM) by a background worker in the AI service. Audio is
-- privileged/KDPA-sensitive, so real transcripts never reach a cloud LLM
-- (enforced by the AI service's synthetic-data gate + a hard local pin).

CREATE TABLE IF NOT EXISTS meeting_recordings (
    id                uuid PRIMARY KEY,
    file_id           uuid REFERENCES files(id) ON DELETE SET NULL,
    advocate_user_id  uuid NOT NULL,
    client_id         uuid REFERENCES clients(id) ON DELETE SET NULL,
    object_key        text NOT NULL DEFAULT '',   -- R2 key (tenant-prefixed, like archives)
    filename          text NOT NULL DEFAULT '',
    mime_type         text NOT NULL DEFAULT '',
    duration_seconds  int  NOT NULL DEFAULT 0,
    consent_confirmed boolean NOT NULL DEFAULT false,  -- MUST be true before a row exists
    status            text NOT NULL DEFAULT 'recording'
                      CHECK (status IN ('recording','uploading','transcribing','summarizing','complete','failed')),
    transcript_text   text NOT NULL DEFAULT '',
    summary_text      text NOT NULL DEFAULT '',
    error             text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
-- The AI worker scans this partial index for recordings needing processing.
CREATE INDEX IF NOT EXISTS meeting_recordings_pending ON meeting_recordings (status)
    WHERE status IN ('transcribing', 'summarizing');
CREATE INDEX IF NOT EXISTS meeting_recordings_advocate ON meeting_recordings (advocate_user_id, created_at DESC);

-- Grants: full oversight to Owner + managers (matters.view_all); create + own
-- visibility to any advocate who works their own files.
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r
CROSS JOIN (VALUES ('recordings.create'), ('recordings.view_own'), ('recordings.view_all')) AS p(perm)
WHERE r.is_protected = true
   OR EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission = 'matters.view_all')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r
CROSS JOIN (VALUES ('recordings.create'), ('recordings.view_own')) AS p(perm)
WHERE EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission = 'matters.view_own')
ON CONFLICT DO NOTHING;
