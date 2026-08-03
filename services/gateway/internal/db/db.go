package db

import (
	"context"
	"fmt"
	"regexp"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Tenant schemas are always tenant_<32 hex chars> (uuid without dashes),
// created by the provisioning service. Anything else is rejected before it
// can reach a SET search_path statement.
var schemaRe = regexp.MustCompile(`^tenant_[0-9a-f]{32}$`)

type DB struct {
	Pool *pgxpool.Pool
}

func Connect(ctx context.Context, url string) (*DB, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 20
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, err
	}
	return &DB{Pool: pool}, nil
}

func ValidSchemaName(schema string) bool { return schemaRe.MatchString(schema) }

// WithTenant runs fn inside a transaction whose search_path is pinned to the
// tenant's schema (plus public, for the pgvector type and shared reference
// tables) and whose app.tenant_id GUC is set for row-level-security policies
// on schema-shared tables (e.g. public.audit_log). SET LOCAL scopes both to
// the transaction, so pooled connections never leak tenant state.
//
// tenantID and schema must come from the authenticated tenant record loaded
// by the tenant middleware — never from request input.
func (d *DB) WithTenant(ctx context.Context, tenantID, schema string, fn func(pgx.Tx) error) error {
	if !ValidSchemaName(schema) {
		return fmt.Errorf("invalid tenant schema name %q", schema)
	}
	return pgx.BeginFunc(ctx, d.Pool, func(tx pgx.Tx) error {
		quoted := pgx.Identifier{schema}.Sanitize()
		if _, err := tx.Exec(ctx, fmt.Sprintf("SET LOCAL search_path = %s, public", quoted)); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "SELECT set_config('app.tenant_id', $1, true)", tenantID); err != nil {
			return err
		}
		return fn(tx)
	})
}

// WithPublic runs fn in a transaction scoped to the public schema only, with
// app.tenant_id set when tenantID != "" (for RLS-guarded shared tables).
func (d *DB) WithPublic(ctx context.Context, tenantID string, fn func(pgx.Tx) error) error {
	return pgx.BeginFunc(ctx, d.Pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SET LOCAL search_path = public"); err != nil {
			return err
		}
		if tenantID != "" {
			if _, err := tx.Exec(ctx, "SELECT set_config('app.tenant_id', $1, true)", tenantID); err != nil {
				return err
			}
		}
		return fn(tx)
	})
}
