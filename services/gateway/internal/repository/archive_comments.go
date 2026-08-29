package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// ArchiveComment is one collaboration comment on an archived document.
type ArchiveComment struct {
	ID         string    `json:"id"`
	ArchiveID  string    `json:"archive_id"`
	UserID     string    `json:"user_id"`
	AuthorName string    `json:"author_name"`
	Body       string    `json:"body"`
	CreatedAt  time.Time `json:"created_at"`
}

func ListArchiveComments(ctx context.Context, tx pgx.Tx, archiveID string) ([]ArchiveComment, error) {
	rows, err := tx.Query(ctx,
		`SELECT c.id, c.archive_id, c.user_id, COALESCE(u.full_name, u.email, ''), c.body, c.created_at
		 FROM archive_comments c LEFT JOIN users u ON u.id = c.user_id
		 WHERE c.archive_id = $1 ORDER BY c.created_at`, archiveID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ArchiveComment
	for rows.Next() {
		var c ArchiveComment
		if err := rows.Scan(&c.ID, &c.ArchiveID, &c.UserID, &c.AuthorName, &c.Body, &c.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func InsertArchiveComment(ctx context.Context, tx pgx.Tx, c *ArchiveComment) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO archive_comments (id, archive_id, user_id, body) VALUES ($1,$2,$3,$4)",
		c.ID, c.ArchiveID, c.UserID, c.Body)
	return err
}
