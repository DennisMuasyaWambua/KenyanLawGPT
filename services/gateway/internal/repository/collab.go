package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type CollabDocument struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	FileID    *string   `json:"file_id,omitempty"`
	OwnerID   string    `json:"owner_id"`
	OwnerName string    `json:"owner_name"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

func scanCollab(row pgx.Row) (*CollabDocument, error) {
	var d CollabDocument
	if err := row.Scan(&d.ID, &d.Title, &d.FileID, &d.OwnerID, &d.OwnerName, &d.CreatedAt, &d.UpdatedAt); err != nil {
		return nil, err
	}
	return &d, nil
}

const collabCols = `d.id, d.title, d.file_id, d.owner_id, COALESCE(u.full_name, u.email, ''), d.created_at, d.updated_at`

// ListCollabDocuments returns documents the caller may open: their own, shared
// with them, or all when senior (Managing Partner).
func ListCollabDocuments(ctx context.Context, tx pgx.Tx, userID string, senior bool) ([]CollabDocument, error) {
	rows, err := tx.Query(ctx,
		"SELECT "+collabCols+` FROM collab_documents d LEFT JOIN users u ON u.id = d.owner_id
		 WHERE d.owner_id = $1 OR $2
		       OR EXISTS (SELECT 1 FROM collab_document_shares s WHERE s.document_id = d.id AND s.user_id = $1)
		 ORDER BY d.updated_at DESC LIMIT 200`, userID, senior)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []CollabDocument
	for rows.Next() {
		d, err := scanCollab(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *d)
	}
	return out, rows.Err()
}

func GetCollabDocument(ctx context.Context, tx pgx.Tx, id string) (*CollabDocument, error) {
	return scanCollab(tx.QueryRow(ctx,
		"SELECT "+collabCols+" FROM collab_documents d LEFT JOIN users u ON u.id = d.owner_id WHERE d.id = $1", id))
}

func InsertCollabDocument(ctx context.Context, tx pgx.Tx, id, title, ownerID string, fileID *string) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO collab_documents (id, title, file_id, owner_id) VALUES ($1,$2,$3,$4)",
		id, title, fileID, ownerID)
	return err
}

func RenameCollabDocument(ctx context.Context, tx pgx.Tx, id, title string) error {
	_, err := tx.Exec(ctx, "UPDATE collab_documents SET title=$2, updated_at=now() WHERE id=$1", id, title)
	return err
}

func CanAccessCollab(ctx context.Context, tx pgx.Tx, docID, userID string, senior bool) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx,
		`SELECT (d.owner_id = $2 OR $3
		         OR EXISTS (SELECT 1 FROM collab_document_shares s WHERE s.document_id = d.id AND s.user_id = $2))
		 FROM collab_documents d WHERE d.id = $1`, docID, userID, senior).Scan(&ok)
	return ok, err
}

func CollabShareUserIDs(ctx context.Context, tx pgx.Tx, docID string) ([]string, error) {
	rows, err := tx.Query(ctx, "SELECT user_id FROM collab_document_shares WHERE document_id = $1", docID)
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

func ReplaceCollabShares(ctx context.Context, tx pgx.Tx, docID string, userIDs []string) error {
	if _, err := tx.Exec(ctx, "DELETE FROM collab_document_shares WHERE document_id = $1", docID); err != nil {
		return err
	}
	for _, uid := range userIDs {
		if _, err := tx.Exec(ctx,
			"INSERT INTO collab_document_shares (document_id, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", docID, uid); err != nil {
			return err
		}
	}
	return nil
}
