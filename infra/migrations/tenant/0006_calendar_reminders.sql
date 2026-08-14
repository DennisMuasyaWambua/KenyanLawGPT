-- Calendar reminders upgrade: an event can now carry MULTIPLE reminders, each
-- with its own channel, replacing the single remind_at/reminded pair. The old
-- columns are kept (backfilled below, then ignored by the app) and dropped in a
-- later cleanup migration. Also adds updated_at to track edits.

ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS event_reminders (
    id         uuid PRIMARY KEY,
    event_id   uuid NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    remind_at  timestamptz NOT NULL,
    -- 'sms' is permitted now so wiring SMS later is a code change, not a migration.
    channel    text NOT NULL DEFAULT 'email' CHECK (channel IN ('email','sms')),
    sent_at    timestamptz,                 -- NULL = not yet fired
    created_at timestamptz NOT NULL DEFAULT now()
);
-- The delivery job scans this partial index (mirrors calendar_events_remind).
CREATE INDEX IF NOT EXISTS event_reminders_due ON event_reminders (remind_at) WHERE sent_at IS NULL;
CREATE INDEX IF NOT EXISTS event_reminders_event ON event_reminders (event_id);

-- Backfill: migrate each existing single reminder into the new table.
INSERT INTO event_reminders (id, event_id, remind_at, channel, sent_at)
SELECT gen_random_uuid(), id, remind_at, 'email',
       CASE WHEN reminded THEN now() ELSE NULL END
FROM calendar_events
WHERE remind_at IS NOT NULL;
