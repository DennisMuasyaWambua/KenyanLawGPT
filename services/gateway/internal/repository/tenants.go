package repository

import (
	"context"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Tenant struct {
	ID              string    `json:"id"`
	Name            string    `json:"name"`
	Slug            string    `json:"slug"`
	SchemaName      string    `json:"-"`
	Plan            string    `json:"plan"`
	DataResidencyKE bool      `json:"data_residency_ke"`
	Status          string    `json:"status"`
	RegNumber       string    `json:"reg_number"` // LSK / firm registration number
	OwnerUserID     *string   `json:"owner_user_id,omitempty"`
	CreatedAt       time.Time `json:"created_at"`
	Phone           string    `json:"phone"`
	// Nil until the owner finishes (or skips) the post-signup onboarding wizard.
	OnboardingCompletedAt *time.Time `json:"onboarding_completed_at,omitempty"`
}

func scanTenant(row pgx.Row) (*Tenant, error) {
	var t Tenant
	err := row.Scan(&t.ID, &t.Name, &t.Slug, &t.SchemaName, &t.Plan, &t.DataResidencyKE, &t.Status,
		&t.RegNumber, &t.OwnerUserID, &t.CreatedAt, &t.Phone, &t.OnboardingCompletedAt)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

const tenantCols = "id, name, slug, schema_name, plan, data_residency_ke, status, reg_number, owner_user_id, created_at, " +
	"phone, onboarding_completed_at"

func TenantBySlug(ctx context.Context, pool *pgxpool.Pool, slug string) (*Tenant, error) {
	return scanTenant(pool.QueryRow(ctx,
		"SELECT "+tenantCols+" FROM public.tenants WHERE slug = $1", strings.ToLower(slug)))
}

func TenantByID(ctx context.Context, pool *pgxpool.Pool, id string) (*Tenant, error) {
	return scanTenant(pool.QueryRow(ctx,
		"SELECT "+tenantCols+" FROM public.tenants WHERE id = $1", id))
}

func ListActiveTenants(ctx context.Context, pool *pgxpool.Pool) ([]Tenant, error) {
	rows, err := pool.Query(ctx, "SELECT "+tenantCols+" FROM public.tenants WHERE status = 'active' ORDER BY created_at")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Tenant
	for rows.Next() {
		var t Tenant
		if err := rows.Scan(&t.ID, &t.Name, &t.Slug, &t.SchemaName, &t.Plan, &t.DataResidencyKE, &t.Status,
			&t.RegNumber, &t.OwnerUserID, &t.CreatedAt, &t.Phone, &t.OnboardingCompletedAt); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

func InsertTenant(ctx context.Context, tx pgx.Tx, t *Tenant) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO public.tenants (id, name, slug, schema_name, plan, data_residency_ke, status, reg_number, phone)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		t.ID, t.Name, strings.ToLower(t.Slug), t.SchemaName, t.Plan, t.DataResidencyKE, t.Status, t.RegNumber, t.Phone)
	return err
}

// TenantSlugExists reports whether a workspace address is already taken.
func TenantSlugExists(ctx context.Context, pool *pgxpool.Pool, slug string) (bool, error) {
	var exists bool
	err := pool.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM public.tenants WHERE slug = lower($1))", slug).Scan(&exists)
	return exists, err
}

// UpdateTenantProfile edits the firm details the owner manages themselves.
func UpdateTenantProfile(ctx context.Context, pool *pgxpool.Pool, id, name, regNumber, phone string) error {
	_, err := pool.Exec(ctx, "UPDATE public.tenants SET name = $2, reg_number = $3, phone = $4 WHERE id = $1",
		id, name, regNumber, phone)
	return err
}

// CompleteTenantOnboarding records that the owner finished or skipped the wizard.
func CompleteTenantOnboarding(ctx context.Context, pool *pgxpool.Pool, id string) error {
	_, err := pool.Exec(ctx,
		"UPDATE public.tenants SET onboarding_completed_at = COALESCE(onboarding_completed_at, now()) WHERE id = $1", id)
	return err
}

// SetTenantOwner records which user owns the firm (used after the owner user is
// created during provisioning).
func SetTenantOwner(ctx context.Context, pool *pgxpool.Pool, tenantID, ownerUserID string) error {
	_, err := pool.Exec(ctx, "UPDATE public.tenants SET owner_user_id = $2 WHERE id = $1", tenantID, ownerUserID)
	return err
}

func DeleteTenant(ctx context.Context, pool *pgxpool.Pool, id string) error {
	_, err := pool.Exec(ctx, "DELETE FROM public.tenants WHERE id = $1", id)
	return err
}

// TenantNameExists reports whether a (non-deleted) firm with this name already
// exists — used to block duplicate law firms at creation time.
func TenantNameExists(ctx context.Context, pool *pgxpool.Pool, name string) (bool, error) {
	var exists bool
	err := pool.QueryRow(ctx,
		"SELECT EXISTS(SELECT 1 FROM public.tenants WHERE lower(name) = lower($1) AND status <> 'deleted')",
		strings.TrimSpace(name)).Scan(&exists)
	return exists, err
}
