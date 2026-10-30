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
	Role         string     `json:"role"`              // denormalized role name (display label)
	RoleID       *string    `json:"role_id,omitempty"` // firm-scoped role; NULL for portal clients
	Status       string     `json:"status"`
	ClientID     *string    `json:"client_id,omitempty"` // set for portal users
	Phone        string     `json:"phone"`               // for WhatsApp/SMS reminders
	PasswordHash string     `json:"-"`                   // "" for Google-only accounts
	GoogleSub    *string    `json:"-"`
	AuthProvider string     `json:"auth_provider"`
	CreatedAt    time.Time  `json:"created_at"`
	LastLoginAt  *time.Time `json:"last_login_at,omitempty"`
	// Set while the account still has an admin-issued temporary password.
	MustChangePassword    bool       `json:"must_change_password"`
	TempPasswordExpiresAt *time.Time `json:"temp_password_expires_at,omitempty"`
}

// password_hash is nullable (Google accounts have none); COALESCE keeps the
// scan into a plain string. An empty PasswordHash never matches CheckPassword.
const userCols = "id, email, full_name, role, role_id, status, client_id, COALESCE(password_hash,''), " +
	"google_sub, auth_provider, created_at, last_login_at, COALESCE(phone,''), " +
	"must_change_password, temp_password_expires_at"

func scanUser(row pgx.Row) (*User, error) {
	var u User
	if err := row.Scan(&u.ID, &u.Email, &u.FullName, &u.Role, &u.RoleID, &u.Status, &u.ClientID,
		&u.PasswordHash, &u.GoogleSub, &u.AuthProvider, &u.CreatedAt, &u.LastLoginAt, &u.Phone,
		&u.MustChangePassword, &u.TempPasswordExpiresAt); err != nil {
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
		`INSERT INTO users (id, email, full_name, role, role_id, status, client_id, password_hash, google_sub, auth_provider, phone,
		                    must_change_password, temp_password_expires_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''),$9,$10,$11,$12,$13)`,
		u.ID, u.Email, u.FullName, u.Role, u.RoleID, u.Status, u.ClientID, u.PasswordHash, u.GoogleSub, provider, u.Phone,
		u.MustChangePassword, u.TempPasswordExpiresAt)
	return err
}

// SetPassword stores a password the user chose and clears any temporary-password state.
func SetPassword(ctx context.Context, tx pgx.Tx, id, hash string) error {
	_, err := tx.Exec(ctx, `UPDATE users SET password_hash = $2, must_change_password = false,
		temp_password_expires_at = NULL WHERE id = $1`, id, hash)
	return err
}

// SetTemporaryPassword replaces a user's password with an admin-issued one they
// must change at next sign-in, usable until expires.
func SetTemporaryPassword(ctx context.Context, tx pgx.Tx, id, hash string, expires time.Time) error {
	_, err := tx.Exec(ctx, `UPDATE users SET password_hash = $2, must_change_password = true,
		temp_password_expires_at = $3 WHERE id = $1`, id, hash, expires)
	return err
}

// DropTemporaryPassword invalidates an unused temporary password (the user
// signed in with Google instead), leaving the account Google-only.
func DropTemporaryPassword(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, `UPDATE users SET password_hash = NULL, must_change_password = false,
		temp_password_expires_at = NULL WHERE id = $1`, id)
	return err
}

// LinkGoogleSub attaches a verified Google account to an existing user the
// first time they sign in with Google (e.g. a password user or an invitee).
func LinkGoogleSub(ctx context.Context, tx pgx.Tx, userID, sub string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET google_sub = $2 WHERE id = $1", userID, sub)
	return err
}

// UpdateUserRole reassigns a user's single role (role_id is the source of
// truth; role stores the denormalized name for display).
func UpdateUserRole(ctx context.Context, tx pgx.Tx, id, roleID, roleName string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET role_id=$2, role=$3 WHERE id=$1", id, roleID, roleName)
	return err
}

// UpdateUserStatus suspends or reactivates a user.
func UpdateUserStatus(ctx context.Context, tx pgx.Tx, id, status string) error {
	_, err := tx.Exec(ctx, "UPDATE users SET status=$2 WHERE id=$1", id, status)
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

// ConsumeRefreshToken atomically revokes a live token and returns its id and
// user id.
//
// A device whose refresh response was lost (the phone locked or dropped off the
// network mid-request) still holds the token the server just rotated away, and
// would be signed out — losing any meeting being recorded. So a recently
// rotated token is accepted once more when its replacement has never been used
// (the device evidently never got it): the unused replacement is revoked and
// the old token is rotated again. Using an old token this way revokes the live
// one, so a stolen token still signs the rightful device out at its next
// refresh. recovery <= 0 disables this.
func ConsumeRefreshToken(ctx context.Context, tx pgx.Tx, tokenHash string, recovery time.Duration) (id, userID string, err error) {
	err = tx.QueryRow(ctx,
		`UPDATE refresh_tokens SET revoked_at = now()
		 WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > now()
		 RETURNING id, user_id`, tokenHash).Scan(&id, &userID)
	if err != pgx.ErrNoRows || recovery <= 0 {
		return id, userID, err
	}
	err = tx.QueryRow(ctx,
		`UPDATE refresh_tokens succ SET revoked_at = now()
		 FROM refresh_tokens prev
		 WHERE prev.token_hash = $1 AND prev.replaced_by = succ.id
		   AND prev.revoked_at > now() - make_interval(secs => $2)
		   AND succ.revoked_at IS NULL AND succ.expires_at > now()
		 RETURNING prev.id, prev.user_id`, tokenHash, recovery.Seconds()).Scan(&id, &userID)
	return id, userID, err
}

// SetRefreshTokenSuccessor records which token replaced a rotated one.
func SetRefreshTokenSuccessor(ctx context.Context, tx pgx.Tx, id, successorID string) error {
	_, err := tx.Exec(ctx, "UPDATE refresh_tokens SET replaced_by = $2 WHERE id = $1", id, successorID)
	return err
}

func RevokeUserRefreshTokens(ctx context.Context, tx pgx.Tx, userID string) error {
	_, err := tx.Exec(ctx, "UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL", userID)
	return err
}
