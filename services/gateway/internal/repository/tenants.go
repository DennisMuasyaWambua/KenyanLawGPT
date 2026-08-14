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
}

func scanTenant(row pgx.Row) (*Tenant, error) {
	var t Tenant
	err := row.Scan(&t.ID, &t.Name, &t.Slug, &t.SchemaName, &t.Plan, &t.DataResidencyKE, &t.Status,
		&t.RegNumber, &t.OwnerUserID, &t.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

const tenantCols = "id, name, slug, schema_name, plan, data_residency_ke, status, reg_number, owner_user_id, created_at"

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
			&t.RegNumber, &t.OwnerUserID, &t.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

func InsertTenant(ctx context.Context, tx pgx.Tx, t *Tenant) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO public.tenants (id, name, slug, schema_name, plan, data_residency_ke, status, reg_number)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		t.ID, t.Name, strings.ToLower(t.Slug), t.SchemaName, t.Plan, t.DataResidencyKE, t.Status, t.RegNumber)
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
