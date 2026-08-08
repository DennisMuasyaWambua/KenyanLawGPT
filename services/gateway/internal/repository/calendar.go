package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type CalendarEvent struct {
	ID          string     `json:"id"`
	Scope       string     `json:"scope"` // "personal" | "firm"
	Title       string     `json:"title"`
	Description string     `json:"description"`
	Location    string     `json:"location"`
	MatterID    *string    `json:"matter_id,omitempty"`
	OwnerID     string     `json:"owner_id"`
	StartAt     time.Time  `json:"start_at"`
	EndAt       *time.Time `json:"end_at,omitempty"`
	AllDay      bool       `json:"all_day"`
	RemindAt    *time.Time `json:"remind_at,omitempty"`
	CreatedBy   string     `json:"created_by"`
	CreatedAt   time.Time  `json:"created_at"`
}

const calendarCols = "id, scope, title, description, location, matter_id, owner_id, " +
	"start_at, end_at, all_day, remind_at, created_by, created_at"

func scanEvent(row pgx.Row) (*CalendarEvent, error) {
	var e CalendarEvent
	if err := row.Scan(&e.ID, &e.Scope, &e.Title, &e.Description, &e.Location, &e.MatterID,
		&e.OwnerID, &e.StartAt, &e.EndAt, &e.AllDay, &e.RemindAt, &e.CreatedBy, &e.CreatedAt); err != nil {
		return nil, err
	}
	return &e, nil
}

// ListEvents returns events in [from, to) visible to userID: all firm events
// plus the user's own personal events.
func ListEvents(ctx context.Context, tx pgx.Tx, userID string, from, to time.Time) ([]CalendarEvent, error) {
	rows, err := tx.Query(ctx,
		"SELECT "+calendarCols+" FROM calendar_events "+
			"WHERE start_at >= $1 AND start_at < $2 AND (scope = 'firm' OR owner_id = $3) "+
			"ORDER BY start_at", from, to, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []CalendarEvent
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *e)
	}
	return out, rows.Err()
}

func CreateEvent(ctx context.Context, tx pgx.Tx, e *CalendarEvent) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO calendar_events
		 (id, scope, title, description, location, matter_id, owner_id, start_at, end_at, all_day, remind_at, created_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
		e.ID, e.Scope, e.Title, e.Description, e.Location, e.MatterID, e.OwnerID,
		e.StartAt, e.EndAt, e.AllDay, e.RemindAt, e.CreatedBy)
	return err
}

// UpdateEvent edits an event the caller may modify: their own, or any firm
// event (the shared calendar). Resets the reminder if remind_at changed.
// Returns pgx.ErrNoRows when nothing was updatable by this user.
func UpdateEvent(ctx context.Context, tx pgx.Tx, id, userID string, e *CalendarEvent) error {
	var got string
	return tx.QueryRow(ctx,
		`UPDATE calendar_events SET
		   title=$3, description=$4, location=$5, matter_id=$6, start_at=$7, end_at=$8,
		   all_day=$9, remind_at=$10, reminded = (reminded AND remind_at IS NOT DISTINCT FROM $10)
		 WHERE id=$1 AND (owner_id=$2 OR scope='firm')
		 RETURNING id`,
		id, userID, e.Title, e.Description, e.Location, e.MatterID, e.StartAt, e.EndAt,
		e.AllDay, e.RemindAt).Scan(&got)
}

func DeleteEvent(ctx context.Context, tx pgx.Tx, id, userID string) error {
	var got string
	return tx.QueryRow(ctx,
		"DELETE FROM calendar_events WHERE id=$1 AND (owner_id=$2 OR scope='firm') RETURNING id",
		id, userID).Scan(&got)
}

// DueCalendarReminders returns events whose remind_at has passed and that have
// not yet been reminded.
func DueCalendarReminders(ctx context.Context, tx pgx.Tx) ([]CalendarEvent, error) {
	rows, err := tx.Query(ctx,
		"SELECT "+calendarCols+" FROM calendar_events "+
			"WHERE remind_at IS NOT NULL AND reminded = false AND remind_at <= now() ORDER BY remind_at")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []CalendarEvent
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *e)
	}
	return out, rows.Err()
}

func MarkCalendarReminded(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE calendar_events SET reminded = true WHERE id = $1", id)
	return err
}
