package db

import (
	"context"

	"github.com/jackc/pgx/v5"
)

// WithPlatformAdmin runs fn in a public-schema transaction with the
// app.platform_admin GUC set, which unlocks the cross-tenant read policy on
// public.audit_log (see migration 0005). Used only by the authenticated
// super-admin control plane; SET LOCAL scopes the GUC to this transaction so
// pooled connections never leak the elevated state.
func (d *DB) WithPlatformAdmin(ctx context.Context, fn func(pgx.Tx) error) error {
	return pgx.BeginFunc(ctx, d.Pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SET LOCAL search_path = public"); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "SELECT set_config('app.platform_admin', 'true', true)"); err != nil {
			return err
		}
		return fn(tx)
	})
}
