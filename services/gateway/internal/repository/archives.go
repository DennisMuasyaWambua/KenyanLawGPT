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
}

const docCols = "id, file_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status, created_at"

func InsertArchive(ctx context.Context, tx pgx.Tx, d *Archive) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO archives (id, file_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		d.ID, d.FileID, d.Filename, d.ObjectKey, d.MimeType, d.SizeBytes, d.DocKind, d.UploadedBy, d.IngestStatus)
	return err
}

func ArchiveByID(ctx context.Context, tx pgx.Tx, id string) (*Archive, error) {
	var d Archive
	err := tx.QueryRow(ctx, "SELECT "+docCols+" FROM archives WHERE id=$1", id).
		Scan(&d.ID, &d.FileID, &d.Filename, &d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.DocKind, &d.UploadedBy, &d.IngestStatus, &d.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &d, nil
}

func ListArchives(ctx context.Context, tx pgx.Tx, fileID string) ([]Archive, error) {
	q := "SELECT " + docCols + " FROM archives"
	args := []any{}
	if fileID != "" {
		q += " WHERE file_id = $1"
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
		var d Archive
		if err := rows.Scan(&d.ID, &d.FileID, &d.Filename, &d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.DocKind, &d.UploadedBy, &d.IngestStatus, &d.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
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
