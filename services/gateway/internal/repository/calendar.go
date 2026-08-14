package repository

import (
	"context"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

type CalendarEvent struct {
	ID          string     `json:"id"`
	Scope       string     `json:"scope"` // "personal" | "firm" (firm == shared)
	Title       string     `json:"title"`
	Description string     `json:"description"`
	Location    string     `json:"location"`
	MatterID    *string    `json:"matter_id,omitempty"`
	OwnerID     string     `json:"owner_id"`
	StartAt     time.Time  `json:"start_at"`
	EndAt       *time.Time `json:"end_at,omitempty"`
	AllDay      bool       `json:"all_day"`
	CreatedBy   string     `json:"created_by"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

const calendarCols = "id, scope, title, description, location, matter_id, owner_id, " +
	"start_at, end_at, all_day, created_by, created_at, updated_at"

func scanEvent(row pgx.Row) (*CalendarEvent, error) {
	var e CalendarEvent
	if err := row.Scan(&e.ID, &e.Scope, &e.Title, &e.Description, &e.Location, &e.MatterID,
		&e.OwnerID, &e.StartAt, &e.EndAt, &e.AllDay, &e.CreatedBy, &e.CreatedAt, &e.UpdatedAt); err != nil {
		return nil, err
	}
	return &e, nil
}

// ListEvents returns events in [from, to). Personal events are always scoped to
// the caller; shared (firm) events are included only when includeShared is set
// (the caller has calendar.view_shared). The two visibilities remain distinct
// rows — this is just a merged read for the "my calendar" display.
func ListEvents(ctx context.Context, tx pgx.Tx, userID string, from, to time.Time, includePersonal, includeShared bool) ([]CalendarEvent, error) {
	var conds []string
	if includePersonal {
		conds = append(conds, "(owner_id = $3 AND scope = 'personal')")
	}
	if includeShared {
		conds = append(conds, "scope = 'firm'")
	}
	if len(conds) == 0 {
		return []CalendarEvent{}, nil
	}
	q := "SELECT " + calendarCols + " FROM calendar_events " +
		"WHERE start_at >= $1 AND start_at < $2 AND (" + strings.Join(conds, " OR ") + ") ORDER BY start_at"
	rows, err := tx.Query(ctx, q, from, to, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []CalendarEvent{}
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *e)
	}
	return out, rows.Err()
}

// GetEvent loads one event by id (used to authorize edits/deletes: the caller
// must own a personal event, or hold calendar.edit_shared/delete_shared for a
// shared one).
func GetEvent(ctx context.Context, tx pgx.Tx, id string) (*CalendarEvent, error) {
	return scanEvent(tx.QueryRow(ctx, "SELECT "+calendarCols+" FROM calendar_events WHERE id = $1", id))
}

func CreateEvent(ctx context.Context, tx pgx.Tx, e *CalendarEvent) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO calendar_events
		 (id, scope, title, description, location, matter_id, owner_id, start_at, end_at, all_day, created_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		e.ID, e.Scope, e.Title, e.Description, e.Location, e.MatterID, e.OwnerID,
		e.StartAt, e.EndAt, e.AllDay, e.CreatedBy)
	return err
}

// UpdateEventFields updates a caller-authorized event's mutable fields. Scope
// and owner are immutable; the guard keeps the update bound to the scope the
// caller was authorized against, closing any read-then-write race.
func UpdateEventFields(ctx context.Context, tx pgx.Tx, id, scope string, e *CalendarEvent) error {
	var got string
	return tx.QueryRow(ctx,
		`UPDATE calendar_events SET
		   title=$3, description=$4, location=$5, matter_id=$6, start_at=$7, end_at=$8,
		   all_day=$9, updated_at=now()
		 WHERE id=$1 AND scope=$2
		 RETURNING id`,
		id, scope, e.Title, e.Description, e.Location, e.MatterID, e.StartAt, e.EndAt, e.AllDay).Scan(&got)
}

func DeleteEventByID(ctx context.Context, tx pgx.Tx, id string) error {
	var got string
	return tx.QueryRow(ctx, "DELETE FROM calendar_events WHERE id=$1 RETURNING id", id).Scan(&got)
}

// --- Event reminders (multiple per event) -----------------------------------

type EventReminder struct {
	ID        string     `json:"id"`
	EventID   string     `json:"event_id"`
	RemindAt  time.Time  `json:"remind_at"`
	Channel   string     `json:"channel"`
	SentAt    *time.Time `json:"sent_at,omitempty"`
	CreatedAt time.Time  `json:"created_at"`
}

func CreateReminder(ctx context.Context, tx pgx.Tx, r *EventReminder) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO event_reminders (id, event_id, remind_at, channel) VALUES ($1,$2,$3,$4)",
		r.ID, r.EventID, r.RemindAt, r.Channel)
	return err
}

// RemindersForEvent returns an event's reminders (for GET responses).
func RemindersForEvent(ctx context.Context, tx pgx.Tx, eventID string) ([]EventReminder, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, event_id, remind_at, channel, sent_at, created_at FROM event_reminders WHERE event_id=$1 ORDER BY remind_at",
		eventID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []EventReminder{}
	for rows.Next() {
		var r EventReminder
		if err := rows.Scan(&r.ID, &r.EventID, &r.RemindAt, &r.Channel, &r.SentAt, &r.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// DeleteFutureUnsentReminders clears an event's not-yet-fired future reminders
// so they can be regenerated on update; already-sent ones are preserved.
func DeleteFutureUnsentReminders(ctx context.Context, tx pgx.Tx, eventID string) error {
	_, err := tx.Exec(ctx,
		"DELETE FROM event_reminders WHERE event_id=$1 AND sent_at IS NULL", eventID)
	return err
}

// DueReminder is a due reminder joined with the fields its delivery needs.
type DueReminder struct {
	ReminderID string
	Channel    string
	OwnerID    string
	Title      string
	Location   string
	StartAt    time.Time
}

// DueReminders returns unsent reminders whose time has passed, joined to their
// event. The delivery loop sends each and marks it sent.
func DueReminders(ctx context.Context, tx pgx.Tx) ([]DueReminder, error) {
	rows, err := tx.Query(ctx,
		`SELECT r.id, r.channel, e.owner_id, e.title, e.location, e.start_at
		   FROM event_reminders r JOIN calendar_events e ON e.id = r.event_id
		  WHERE r.sent_at IS NULL AND r.remind_at <= now()
		  ORDER BY r.remind_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []DueReminder
	for rows.Next() {
		var d DueReminder
		if err := rows.Scan(&d.ReminderID, &d.Channel, &d.OwnerID, &d.Title, &d.Location, &d.StartAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func MarkReminderSent(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE event_reminders SET sent_at = now() WHERE id = $1", id)
	return err
}
