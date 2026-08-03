package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Document struct {
	ID           string    `json:"id"`
	MatterID     *string   `json:"matter_id"`
	Filename     string    `json:"filename"`
	ObjectKey    string    `json:"object_key"`
	MimeType     string    `json:"mime_type"`
	SizeBytes    int64     `json:"size_bytes"`
	DocKind      string    `json:"doc_kind"` // contract|pleading|correspondence|evidence|precedent_note|other
	UploadedBy   string    `json:"uploaded_by"`
	IngestStatus string    `json:"ingest_status"` // pending|ingesting|ingested|failed
	CreatedAt    time.Time `json:"created_at"`
}

const docCols = "id, matter_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status, created_at"

func InsertDocument(ctx context.Context, tx pgx.Tx, d *Document) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO documents (id, matter_id, filename, object_key, mime_type, size_bytes, doc_kind, uploaded_by, ingest_status)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		d.ID, d.MatterID, d.Filename, d.ObjectKey, d.MimeType, d.SizeBytes, d.DocKind, d.UploadedBy, d.IngestStatus)
	return err
}

func DocumentByID(ctx context.Context, tx pgx.Tx, id string) (*Document, error) {
	var d Document
	err := tx.QueryRow(ctx, "SELECT "+docCols+" FROM documents WHERE id=$1", id).
		Scan(&d.ID, &d.MatterID, &d.Filename, &d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.DocKind, &d.UploadedBy, &d.IngestStatus, &d.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &d, nil
}

func ListDocuments(ctx context.Context, tx pgx.Tx, matterID string) ([]Document, error) {
	q := "SELECT " + docCols + " FROM documents"
	args := []any{}
	if matterID != "" {
		q += " WHERE matter_id = $1"
		args = append(args, matterID)
	}
	q += " ORDER BY created_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Document
	for rows.Next() {
		var d Document
		if err := rows.Scan(&d.ID, &d.MatterID, &d.Filename, &d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.DocKind, &d.UploadedBy, &d.IngestStatus, &d.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func SetIngestStatus(ctx context.Context, tx pgx.Tx, id, status string) error {
	_, err := tx.Exec(ctx, "UPDATE documents SET ingest_status=$2 WHERE id=$1", id, status)
	return err
}

func DocumentIDsForSubject(ctx context.Context, tx pgx.Tx, subjectType, subjectID string) ([]string, []string, error) {
	// Documents linked (via matters) to a client subject; used by KDPA erasure.
	var q string
	switch subjectType {
	case "client":
		q = `SELECT d.id, d.object_key FROM documents d JOIN matters m ON m.id = d.matter_id WHERE m.client_id = $1`
	case "user":
		q = `SELECT d.id, d.object_key FROM documents d WHERE d.uploaded_by = $1`
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
	MatterID  *string   `json:"matter_id"`
	DocType   string    `json:"doc_type"`
	Title     string    `json:"title"`
	Content   string    `json:"content"`
	Citations []byte    `json:"citations"` // JSON array of provenance objects
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

func InsertDraft(ctx context.Context, tx pgx.Tx, d *Draft) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO drafts (id, matter_id, doc_type, title, content, citations, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7)",
		d.ID, d.MatterID, d.DocType, d.Title, d.Content, d.Citations, d.CreatedBy)
	return err
}

func ListDrafts(ctx context.Context, tx pgx.Tx, matterID string) ([]Draft, error) {
	q := "SELECT id, matter_id, doc_type, title, content, citations, created_by, created_at FROM drafts"
	args := []any{}
	if matterID != "" {
		q += " WHERE matter_id=$1"
		args = append(args, matterID)
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
		if err := rows.Scan(&d.ID, &d.MatterID, &d.DocType, &d.Title, &d.Content, &d.Citations, &d.CreatedBy, &d.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}
