package repository

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5"
)

type Recording struct {
	ID               string    `json:"id"`
	FileID           *string   `json:"file_id,omitempty"`
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
	// Speakers: the count the advocate gave (0 = estimate), the diarized
	// utterances ([{speaker, start, end, text}]) and display names by label.
	NumSpeakers        int             `json:"num_speakers"`
	TranscriptSegments json.RawMessage `json:"transcript_segments"`
	SpeakerNames       json.RawMessage `json:"speaker_names"`
	// What speech recognition produced before the Kenyan-English AI correction
	// ("" when nothing was corrected).
	TranscriptRaw string `json:"transcript_raw"`
}

// Utterance is one entry of TranscriptSegments.
type Utterance struct {
	Speaker int     `json:"speaker"`
	Start   float64 `json:"start"`
	End     float64 `json:"end"`
	Text    string  `json:"text"`
}

const recordingCols = `id, file_id, advocate_user_id, client_id, object_key, filename, mime_type,
	duration_seconds, consent_confirmed, status, transcript_text, summary_text, error, created_at, updated_at,
	num_speakers, transcript_segments, speaker_names, transcript_raw`

func scanRecording(row pgx.Row) (*Recording, error) {
	var r Recording
	if err := row.Scan(&r.ID, &r.FileID, &r.AdvocateUserID, &r.ClientID, &r.ObjectKey, &r.Filename,
		&r.MimeType, &r.DurationSeconds, &r.ConsentConfirmed, &r.Status, &r.TranscriptText,
		&r.SummaryText, &r.Error, &r.CreatedAt, &r.UpdatedAt,
		&r.NumSpeakers, &r.TranscriptSegments, &r.SpeakerNames, &r.TranscriptRaw); err != nil {
		return nil, err
	}
	return &r, nil
}

func InsertRecording(ctx context.Context, tx pgx.Tx, r *Recording) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO meeting_recordings
		 (id, file_id, advocate_user_id, client_id, object_key, filename, mime_type, consent_confirmed, status, num_speakers)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		r.ID, r.FileID, r.AdvocateUserID, r.ClientID, r.ObjectKey, r.Filename, r.MimeType,
		r.ConsentConfirmed, r.Status, r.NumSpeakers)
	return err
}

// SetSpeakerNames stores the display names for a recording's speaker labels.
func SetSpeakerNames(ctx context.Context, tx pgx.Tx, id string, names map[string]string) error {
	b, err := json.Marshal(names)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, "UPDATE meeting_recordings SET speaker_names = $2::jsonb, updated_at = now() WHERE id = $1", id, string(b))
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

// RetryRecording re-queues a failed recording for transcription. Only the
// owning advocate can retry, and only from "failed" — returns pgx.ErrNoRows
// otherwise (not found / not yours / not failed).
func RetryRecording(ctx context.Context, tx pgx.Tx, id, advocateID string) error {
	var got string
	return tx.QueryRow(ctx,
		`UPDATE meeting_recordings SET status='transcribing', error='', attempts=0, updated_at=now()
		 WHERE id=$1 AND advocate_user_id=$2 AND status='failed' RETURNING id`, id, advocateID).Scan(&got)
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

func ListRecordingsByFile(ctx context.Context, tx pgx.Tx, fileID string) ([]Recording, error) {
	return listRecordings(ctx, tx, "WHERE file_id=$1 ORDER BY created_at DESC", fileID)
}

func ListOwnRecordingsByFile(ctx context.Context, tx pgx.Tx, fileID, advocateID string) ([]Recording, error) {
	return listRecordings(ctx, tx, "WHERE file_id=$1 AND advocate_user_id=$2 ORDER BY created_at DESC", fileID, advocateID)
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
