-- Event attendees: staff invited to a calendar event. Calendar-event reminders
-- fan out to every attendee (plus the owner), so "notify the concerned
-- individuals" reaches the whole group rather than only the event creator.
CREATE TABLE IF NOT EXISTS event_attendees (
    event_id   uuid NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, user_id)
);
CREATE INDEX IF NOT EXISTS event_attendees_event ON event_attendees (event_id);
