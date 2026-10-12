-- The AI worker proofreads the Whisper transcript for Kenyan English (names,
-- places, courts, legal terms) before writing the notes. transcript_text holds
-- the corrected version; transcript_raw keeps what speech recognition produced
-- so any correction can be checked ('' = no correction was made).
ALTER TABLE meeting_recordings ADD COLUMN IF NOT EXISTS transcript_raw text NOT NULL DEFAULT '';
