package db

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"
)

// Minimal, dependency-free SQL migration runner. Public migrations live in
// <dir>/public, tenant-schema migrations in <dir>/tenant; both are applied in
// filename order and tracked in a schema_migrations table per schema.

func readMigrations(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".sql") {
			files = append(files, e.Name())
		}
	}
	sort.Strings(files)
	return files, nil
}

func applyDir(ctx context.Context, tx pgx.Tx, dir string, applied map[string]bool) (int, error) {
	files, err := readMigrations(dir)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, f := range files {
		if applied[f] {
			continue
		}
		body, err := os.ReadFile(filepath.Join(dir, f))
		if err != nil {
			return n, err
		}
		if _, err := tx.Exec(ctx, string(body)); err != nil {
			return n, fmt.Errorf("migration %s: %w", f, err)
		}
		if _, err := tx.Exec(ctx, "INSERT INTO schema_migrations(version) VALUES ($1)", f); err != nil {
			return n, err
		}
		n++
	}
	return n, nil
}

func loadApplied(ctx context.Context, tx pgx.Tx) (map[string]bool, error) {
	if _, err := tx.Exec(ctx,
		"CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"); err != nil {
		return nil, err
	}
	rows, err := tx.Query(ctx, "SELECT version FROM schema_migrations")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	applied := map[string]bool{}
	for rows.Next() {
		var v string
		if err := rows.Scan(&v); err != nil {
			return nil, err
		}
		applied[v] = true
	}
	return applied, rows.Err()
}

// ApplyPublic applies <migrationsDir>/public against the public schema.
func (d *DB) ApplyPublic(ctx context.Context, migrationsDir string) (int, error) {
	n := 0
	err := pgx.BeginFunc(ctx, d.Pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SET LOCAL search_path = public"); err != nil {
			return err
		}
		applied, err := loadApplied(ctx, tx)
		if err != nil {
			return err
		}
		n, err = applyDir(ctx, tx, filepath.Join(migrationsDir, "public"), applied)
		return err
	})
	return n, err
}

// ApplyTenant creates the tenant schema if needed and applies
// <migrationsDir>/tenant inside it. Called at provisioning time and again on
// deploy for every existing tenant (idempotent).
func (d *DB) ApplyTenant(ctx context.Context, migrationsDir, schema string) (int, error) {
	if !ValidSchemaName(schema) {
		return 0, fmt.Errorf("invalid tenant schema name %q", schema)
	}
	n := 0
	err := pgx.BeginFunc(ctx, d.Pool, func(tx pgx.Tx) error {
		quoted := pgx.Identifier{schema}.Sanitize()
		if _, err := tx.Exec(ctx, "CREATE SCHEMA IF NOT EXISTS "+quoted); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, fmt.Sprintf("SET LOCAL search_path = %s, public", quoted)); err != nil {
			return err
		}
		applied, err := loadApplied(ctx, tx)
		if err != nil {
			return err
		}
		n, err = applyDir(ctx, tx, filepath.Join(migrationsDir, "tenant"), applied)
		return err
	})
	return n, err
}
