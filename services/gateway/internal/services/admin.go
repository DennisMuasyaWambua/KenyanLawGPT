package services

import (
	"context"
	"strings"

	"github.com/google/uuid"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/repository"
)

// EnsurePlatformAdmin idempotently creates the bootstrap super-admin from
// PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD on startup. If an admin with
// that email already exists it is left untouched (password changes go through
// the control panel, not env).
func EnsurePlatformAdmin(ctx context.Context, database *db.DB, email, password string) error {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" || password == "" {
		return nil
	}
	if _, err := repository.PlatformAdminByEmail(ctx, database.Pool, email); err == nil {
		return nil // already exists
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return err
	}
	admin := &repository.PlatformAdmin{
		ID:           uuid.NewString(),
		Email:        email,
		FullName:     "Platform Owner",
		PasswordHash: hash,
	}
	if err := repository.InsertPlatformAdmin(ctx, database.Pool, admin); err != nil {
		return err
	}
	logging.L(ctx).Info("bootstrap platform admin ensured", "email", email)
	return nil
}
