package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Archive struct {
	ID           string    `json:"id"`
	FileID     *string   `json:"file_id"`
	Filename     string    `json:"filename"`
	ObjectKey    string    `json:"object_key"`
	MimeType     string    `json:"mime_type"`
	SizeBytes    int64     `json:"size_bytes"`
	DocKind      string    `json:"doc_kind"` // contract|pleading|correspondence|evidence|precedent_note|other
	UploadedBy   string    `json:"uploaded_by"`
	IngestStatus string    `json:"ingest_status"` // pending|ingesting|ingested|failed
	CreatedAt    time.Time `json:"created_at"`
	Version      int       `json:"version"`
	Superseded   bool      `json:"superseded"`
	PreviousID   *string   `json:"previous_id,omitempty"`
	Restricted   bool      `json:"restricted"`
}

const docCols = "id, file_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status, created_at, version, superseded, previous_id, restricted"

func scanArchive(row pgx.Row) (*Archive, error) {
	var d Archive
	if err := row.Scan(&d.ID, &d.FileID, &d.Filename, &d.ObjectKey, &d.MimeType, &d.SizeBytes,
		&d.DocKind, &d.UploadedBy, &d.IngestStatus, &d.CreatedAt, &d.Version, &d.Superseded, &d.PreviousID, &d.Restricted); err != nil {
		return nil, err
	}
	return &d, nil
}

// archiveColsP returns docCols prefixed (for the version-chain CTE join).
func archiveColsP(p string) string {
	return p + "id, " + p + "file_id, " + p + "filename, " + p + "object_key, " + p + "mime_type, " +
		p + "size_bytes, " + p + "doc_kind, " + p + "uploaded_by, " + p + "ingest_status, " + p + "created_at, " +
		p + "version, " + p + "superseded, " + p + "previous_id, " + p + "restricted"
}

func InsertArchive(ctx context.Context, tx pgx.Tx, d *Archive) error {
	if d.Version == 0 {
		d.Version = 1
	}
	_, err := tx.Exec(ctx,
		`INSERT INTO archives (id, file_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status, version, previous_id)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		d.ID, d.FileID, d.Filename, d.ObjectKey, d.MimeType, d.SizeBytes, d.DocKind, d.UploadedBy, d.IngestStatus, d.Version, d.PreviousID)
	return err
}

func ArchiveByID(ctx context.Context, tx pgx.Tx, id string) (*Archive, error) {
	return scanArchive(tx.QueryRow(ctx, "SELECT "+docCols+" FROM archives WHERE id=$1", id))
}

// ListArchives returns current (non-superseded) documents the caller may see:
// unrestricted, their own uploads, docs shared with them, or all when senior
// (Managing Partner).
func ListArchives(ctx context.Context, tx pgx.Tx, fileID, userID string, senior bool) ([]Archive, error) {
	q := "SELECT " + docCols + ` FROM archives WHERE superseded = false
		AND (restricted = false OR uploaded_by = $1 OR $2
		     OR EXISTS (SELECT 1 FROM archive_shares s WHERE s.archive_id = archives.id AND s.user_id = $1))`
	args := []any{userID, senior}
	if fileID != "" {
		q += " AND file_id = $3"
		args = append(args, fileID)
	}
	q += " ORDER BY created_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Archive
	for rows.Next() {
		d, err := scanArchive(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *d)
	}
	return out, rows.Err()
}

// ListArchiveVersions returns the version chain of a document (current + older),
// newest first, by walking previous_id backward.
func ListArchiveVersions(ctx context.Context, tx pgx.Tx, id string) ([]Archive, error) {
	q := `WITH RECURSIVE chain AS (
		SELECT ` + docCols + ` FROM archives WHERE id = $1
		UNION ALL
		SELECT ` + archiveColsP("a.") + ` FROM archives a JOIN chain c ON a.id = c.previous_id
	) SELECT ` + docCols + ` FROM chain ORDER BY version DESC`
	rows, err := tx.Query(ctx, q, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Archive
	for rows.Next() {
		d, err := scanArchive(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *d)
	}
	return out, rows.Err()
}

// MarkSuperseded flags an old version as replaced (hidden from current lists).
func MarkSuperseded(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE archives SET superseded = true WHERE id = $1", id)
	return err
}

// CanAccessArchive reports whether the caller may view/download the document.
func CanAccessArchive(ctx context.Context, tx pgx.Tx, archiveID, userID string, senior bool) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx,
		`SELECT (a.restricted = false OR a.uploaded_by = $2 OR $3
		         OR EXISTS (SELECT 1 FROM archive_shares s WHERE s.archive_id = a.id AND s.user_id = $2))
		 FROM archives a WHERE a.id = $1`, archiveID, userID, senior).Scan(&ok)
	return ok, err
}

// --- sharing ---

func SetArchiveRestricted(ctx context.Context, tx pgx.Tx, id string, restricted bool) error {
	_, err := tx.Exec(ctx, "UPDATE archives SET restricted = $2 WHERE id = $1", id, restricted)
	return err
}

func ListArchiveShareUserIDs(ctx context.Context, tx pgx.Tx, archiveID string) ([]string, error) {
	rows, err := tx.Query(ctx, "SELECT user_id FROM archive_shares WHERE archive_id = $1", archiveID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// ReplaceArchiveShares sets the exact share list for a document.
func ReplaceArchiveShares(ctx context.Context, tx pgx.Tx, archiveID string, userIDs []string) error {
	if _, err := tx.Exec(ctx, "DELETE FROM archive_shares WHERE archive_id = $1", archiveID); err != nil {
		return err
	}
	for _, uid := range userIDs {
		if _, err := tx.Exec(ctx,
			"INSERT INTO archive_shares (archive_id, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", archiveID, uid); err != nil {
			return err
		}
	}
	return nil
}

func SetIngestStatus(ctx context.Context, tx pgx.Tx, id, status string) error {
	_, err := tx.Exec(ctx, "UPDATE archives SET ingest_status=$2 WHERE id=$1", id, status)
	return err
}

func ArchiveIDsForSubject(ctx context.Context, tx pgx.Tx, subjectType, subjectID string) ([]string, []string, error) {
	// Archives linked (via files) to a client subject; used by KDPA erasure.
	var q string
	switch subjectType {
	case "client":
		q = `SELECT d.id, d.object_key FROM archives d JOIN files m ON m.id = d.file_id WHERE m.client_id = $1`
	case "user":
		q = `SELECT d.id, d.object_key FROM archives d WHERE d.uploaded_by = $1`
	default:
		return nil, nil, pgx.ErrNoRows
	}
	rows, err := tx.Query(ctx, q, subjectID)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	var ids, keys []string
	for rows.Next() {
		var id, key string
		if err := rows.Scan(&id, &key); err != nil {
			return nil, nil, err
		}
		ids = append(ids, id)
		keys = append(keys, key)
	}
	return ids, keys, rows.Err()
}

type Draft struct {
	ID        string    `json:"id"`
	FileID  *string   `json:"file_id"`
	DocType   string    `json:"doc_type"`
	Title     string    `json:"title"`
	Content   string    `json:"content"`
	Citations []byte    `json:"citations"` // JSON array of provenance objects
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

func InsertDraft(ctx context.Context, tx pgx.Tx, d *Draft) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO drafts (id, file_id, doc_type, title, content, citations, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7)",
		d.ID, d.FileID, d.DocType, d.Title, d.Content, d.Citations, d.CreatedBy)
	return err
}

func ListDrafts(ctx context.Context, tx pgx.Tx, fileID string) ([]Draft, error) {
	q := "SELECT id, file_id, doc_type, title, content, citations, created_by, created_at FROM drafts"
	args := []any{}
	if fileID != "" {
		q += " WHERE file_id=$1"
		args = append(args, fileID)
	}
	q += " ORDER BY created_at DESC LIMIT 100"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Draft
	for rows.Next() {
		var d Draft
		if err := rows.Scan(&d.ID, &d.FileID, &d.DocType, &d.Title, &d.Content, &d.Citations, &d.CreatedBy, &d.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}
