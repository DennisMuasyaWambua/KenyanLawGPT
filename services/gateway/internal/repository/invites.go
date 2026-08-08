package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type StaffInvite struct {
	ID         string     `json:"id"`
	Email      string     `json:"email"`
	FullName   string     `json:"full_name"`
	Role       string     `json:"role"`
	Status     string     `json:"status"`
	InvitedBy  *string    `json:"invited_by,omitempty"`
	ExpiresAt  time.Time  `json:"expires_at"`
	CreatedAt  time.Time  `json:"created_at"`
	AcceptedAt *time.Time `json:"accepted_at,omitempty"`
}

const inviteCols = "id, email, full_name, role, status, invited_by, expires_at, created_at, accepted_at"

func scanInvite(row pgx.Row) (*StaffInvite, error) {
	var inv StaffInvite
	if err := row.Scan(&inv.ID, &inv.Email, &inv.FullName, &inv.Role, &inv.Status,
		&inv.InvitedBy, &inv.ExpiresAt, &inv.CreatedAt, &inv.AcceptedAt); err != nil {
		return nil, err
	}
	return &inv, nil
}

func CreateInvite(ctx context.Context, tx pgx.Tx, inv *StaffInvite, tokenHash string) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO staff_invites (id, email, full_name, role, token_hash, invited_by, expires_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		inv.ID, inv.Email, inv.FullName, inv.Role, tokenHash, inv.InvitedBy, inv.ExpiresAt)
	return err
}

// InviteByTokenHash returns a pending, unexpired invite for the given token hash.
func InviteByTokenHash(ctx context.Context, tx pgx.Tx, tokenHash string) (*StaffInvite, error) {
	return scanInvite(tx.QueryRow(ctx,
		"SELECT "+inviteCols+" FROM staff_invites WHERE token_hash = $1 "+
			"AND status = 'pending' AND expires_at > now()", tokenHash))
}

// MarkInviteAccepted flips a pending invite to accepted; the WHERE guard makes
// double-accept a no-op returning ErrNoRows.
func MarkInviteAccepted(ctx context.Context, tx pgx.Tx, tokenHash string) error {
	var id string
	return tx.QueryRow(ctx,
		`UPDATE staff_invites SET status = 'accepted', accepted_at = now()
		 WHERE token_hash = $1 AND status = 'pending' AND expires_at > now()
		 RETURNING id`, tokenHash).Scan(&id)
}
