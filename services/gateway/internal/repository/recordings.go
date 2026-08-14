package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Recording struct {
	ID               string    `json:"id"`
	MatterID         *string   `json:"matter_id,omitempty"`
	AdvocateUserID   string    `json:"advocate_user_id"`
	ClientID         *string   `json:"client_id,omitempty"`
	ObjectKey        string    `json:"-"` // internal; never returned to the browser
	Filename         string    `json:"filename"`
	MimeType         string    `json:"mime_type"`
	DurationSeconds  int       `json:"duration_seconds"`
	ConsentConfirmed bool      `json:"consent_confirmed"`
	Status           string    `json:"status"`
	TranscriptText   string    `json:"transcript_text"`
	SummaryText      string    `json:"summary_text"`
	Error            string    `json:"error,omitempty"`
	CreatedAt        time.Time `json:"created_at"`
	UpdatedAt        time.Time `json:"updated_at"`
}

const recordingCols = `id, matter_id, advocate_user_id, client_id, object_key, filename, mime_type,
	duration_seconds, consent_confirmed, status, transcript_text, summary_text, error, created_at, updated_at`

func scanRecording(row pgx.Row) (*Recording, error) {
	var r Recording
	if err := row.Scan(&r.ID, &r.MatterID, &r.AdvocateUserID, &r.ClientID, &r.ObjectKey, &r.Filename,
		&r.MimeType, &r.DurationSeconds, &r.ConsentConfirmed, &r.Status, &r.TranscriptText,
		&r.SummaryText, &r.Error, &r.CreatedAt, &r.UpdatedAt); err != nil {
		return nil, err
	}
	return &r, nil
}

func InsertRecording(ctx context.Context, tx pgx.Tx, r *Recording) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO meeting_recordings
		 (id, matter_id, advocate_user_id, client_id, object_key, filename, mime_type, consent_confirmed, status)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		r.ID, r.MatterID, r.AdvocateUserID, r.ClientID, r.ObjectKey, r.Filename, r.MimeType,
		r.ConsentConfirmed, r.Status)
	return err
}

// MarkUploaded transitions a recording to transcribing once its audio has
// landed in R2. Bound to the advocate who owns it.
func MarkUploaded(ctx context.Context, tx pgx.Tx, id, advocateID string, duration int) error {
	var got string
	return tx.QueryRow(ctx,
		`UPDATE meeting_recordings SET status='transcribing', duration_seconds=$3, updated_at=now()
		 WHERE id=$1 AND advocate_user_id=$2 RETURNING id`, id, advocateID, duration).Scan(&got)
}

func GetRecording(ctx context.Context, tx pgx.Tx, id string) (*Recording, error) {
	return scanRecording(tx.QueryRow(ctx, "SELECT "+recordingCols+" FROM meeting_recordings WHERE id=$1", id))
}

func ListOwnRecordings(ctx context.Context, tx pgx.Tx, advocateID string) ([]Recording, error) {
	return listRecordings(ctx, tx, "WHERE advocate_user_id=$1 ORDER BY created_at DESC", advocateID)
}

func ListAllRecordings(ctx context.Context, tx pgx.Tx) ([]Recording, error) {
	return listRecordings(ctx, tx, "ORDER BY created_at DESC")
}

func ListRecordingsByMatter(ctx context.Context, tx pgx.Tx, matterID string) ([]Recording, error) {
	return listRecordings(ctx, tx, "WHERE matter_id=$1 ORDER BY created_at DESC", matterID)
}

func listRecordings(ctx context.Context, tx pgx.Tx, where string, args ...any) ([]Recording, error) {
	rows, err := tx.Query(ctx, "SELECT "+recordingCols+" FROM meeting_recordings "+where, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Recording{}
	for rows.Next() {
		r, err := scanRecording(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *r)
	}
	return out, rows.Err()
}
