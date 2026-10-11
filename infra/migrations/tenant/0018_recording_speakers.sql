-- Speaker-labelled transcripts. The AI worker diarizes the audio on-box and
-- stores who-said-what alongside the plain transcript:
--   num_speakers        how many people the advocate said were in the meeting
--                       (0 = estimate; a known count is far more accurate)
--   transcript_segments [{speaker, start, end, text}] utterances, speaker 1..N
--   speaker_names       {"1": "Adv. Wanjiru", "2": "Client"} display names set by
--                       the user; two labels given the same name read as one person
ALTER TABLE meeting_recordings ADD COLUMN IF NOT EXISTS num_speakers int NOT NULL DEFAULT 0
    CHECK (num_speakers BETWEEN 0 AND 10);
ALTER TABLE meeting_recordings ADD COLUMN IF NOT EXISTS transcript_segments jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE meeting_recordings ADD COLUMN IF NOT EXISTS speaker_names jsonb NOT NULL DEFAULT '{}'::jsonb;
