-- Personal + shared-firm calendars: meetings, reminders and scheduled events.
--
-- scope='personal' events are visible only to their owner; scope='firm' events
-- are the shared firm calendar, visible to all staff. An event may optionally
-- link to a file (a case meeting/hearing prep) and carry a remind_at that the
-- reminder loop fires once (mirroring court_dates/deadlines).
CREATE TABLE IF NOT EXISTS calendar_events (
    id          uuid PRIMARY KEY,
    scope       text NOT NULL CHECK (scope IN ('personal', 'firm')),
    title       text NOT NULL,
    description text NOT NULL DEFAULT '',
    location    text NOT NULL DEFAULT '',
    file_id   uuid REFERENCES files(id) ON DELETE SET NULL,
    owner_id    uuid NOT NULL,
    start_at    timestamptz NOT NULL,
    end_at      timestamptz,
    all_day     boolean NOT NULL DEFAULT false,
    remind_at   timestamptz,
    reminded    boolean NOT NULL DEFAULT false,
    created_by  uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS calendar_events_scope_start ON calendar_events (scope, start_at);
CREATE INDEX IF NOT EXISTS calendar_events_owner_start ON calendar_events (owner_id, start_at);
CREATE INDEX IF NOT EXISTS calendar_events_remind ON calendar_events (remind_at)
    WHERE remind_at IS NOT NULL AND reminded = false;
