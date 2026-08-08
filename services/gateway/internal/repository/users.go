package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type User struct {
	ID           string     `json:"id"`
	Email        string     `json:"email"`
	FullName     string     `json:"full_name"`
	Role         string     `json:"role"`
	Status       string     `json:"status"`
	ClientID     *string    `json:"client_id,omitempty"` // set for portal users
	PasswordHash string     `json:"-"`                   // "" for Google-only accounts
	GoogleSub    *string    `json:"-"`
	AuthProvider string     `json:"auth_provider"`
	CreatedAt    time.Time  `json:"created_at"`
	LastLoginAt  *time.Time `json:"last_login_at,omitempty"`
}

// password_hash is nullable (Google accounts have none); COALESCE keeps the
// scan into a plain string. An empty PasswordHash never matches CheckPassword.
const userCols = "id, email, full_name, role, status, client_id, COALESCE(password_hash,''), " +
	"google_sub, auth_provider, created_at, last_login_at"

func scanUser(row pgx.Row) (*User, error) {
	var u User
	if err := row.Scan(&u.ID, &u.Email, &u.FullName, &u.Role, &u.Status, &u.ClientID,
		&u.PasswordHash, &u.GoogleSub, &u.AuthProvider, &u.CreatedAt, &u.LastLoginAt); err != nil {
		return nil, err
	}
	return &u, nil
}

func UserByEmail(ctx context.Context, tx pgx.Tx, email string) (*User, error) {
	return scanUser(tx.QueryRow(ctx, "SELECT "+userCols+" FROM users WHERE lower(email) = lower($1)", email))
}

func UserByID(ctx context.Context, tx pgx.Tx, id string) (*User, error) {
	return scanUser(tx.QueryRow(ctx, "SELECT "+userCols+" FROM users WHERE id = $1", id))
}

func UserByGoogleSub(ctx context.Context, tx pgx.Tx, sub string) (*User, error) {
	return scanUser(tx.QueryRow(ctx, "SELECT "+userCols+" FROM users WHERE google_sub = $1", sub))
}

func ListUsers(ctx context.Context, tx pgx.Tx) ([]User, error) {
	rows, err := tx.Query(ctx, "SELECT "+userCols+" FROM users ORDER BY created_at")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []User
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *u)
	}
	return out, rows.Err()
}

func InsertUser(ctx context.Context, tx pgx.Tx, u *User) error {
	provider := u.AuthProvider
	if provider == "" {
		provider = "password"
	}
	_, err := tx.Exec(ctx,
		`INSERT INTO users (id, email, full_name, role, status, client_id, password_hash, google_sub, auth_provider)
		 VALUES ($1,$2,$3,$4,$5,$6,NULLIF($7,''),$8,$9)`,
		u.ID, u.Email, u.FullName, u.Role, u.Status, u.ClientID, u.PasswordHash, u.GoogleSub, provider)
	return err
}

// LinkGoogleSub attaches a verified Google account to an existing user the
// first time they sign in with Google (e.g. a password user or an invitee).
func LinkGoogleSub(ctx context.Context, tx pgx.Tx, userID, sub string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET google_sub = $2 WHERE id = $1", userID, sub)
	return err
}

func UpdateUser(ctx context.Context, tx pgx.Tx, id, role, status string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET role=$2, status=$3 WHERE id=$1", id, role, status)
	return err
}

func TouchLastLogin(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET last_login_at = now() WHERE id = $1", id)
	return err
}

// --- refresh tokens (rotating) ---

func StoreRefreshToken(ctx context.Context, tx pgx.Tx, id, userID, tokenHash string, expires time.Time) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at) VALUES ($1,$2,$3,$4)",
		id, userID, tokenHash, expires)
	return err
}

// ConsumeRefreshToken atomically revokes a live token and returns its user id.
func ConsumeRefreshToken(ctx context.Context, tx pgx.Tx, tokenHash string) (string, error) {
	var userID string
	err := tx.QueryRow(ctx,
		`UPDATE refresh_tokens SET revoked_at = now()
		 WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > now()
		 RETURNING user_id`, tokenHash).Scan(&userID)
	return userID, err
}

func RevokeUserRefreshTokens(ctx context.Context, tx pgx.Tx, userID string) error {
	_, err := tx.Exec(ctx, "UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL", userID)
	return err
}
