package repository

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ---------------------------------------------------------------------------
// Platform (super-admin) accounts — public schema, cross-tenant control plane.
// ---------------------------------------------------------------------------

type PlatformAdmin struct {
	ID           string     `json:"id"`
	Email        string     `json:"email"`
	FullName     string     `json:"full_name"`
	PasswordHash string     `json:"-"`
	Status       string     `json:"status"`
	CreatedAt    time.Time  `json:"created_at"`
	LastLoginAt  *time.Time `json:"last_login_at,omitempty"`
}

const platformAdminCols = "id, email, full_name, COALESCE(password_hash,''), status, created_at, last_login_at"

func scanPlatformAdmin(row pgx.Row) (*PlatformAdmin, error) {
	var a PlatformAdmin
	if err := row.Scan(&a.ID, &a.Email, &a.FullName, &a.PasswordHash, &a.Status, &a.CreatedAt, &a.LastLoginAt); err != nil {
		return nil, err
	}
	return &a, nil
}

func PlatformAdminByEmail(ctx context.Context, pool *pgxpool.Pool, email string) (*PlatformAdmin, error) {
	return scanPlatformAdmin(pool.QueryRow(ctx,
		"SELECT "+platformAdminCols+" FROM public.platform_admins WHERE lower(email)=lower($1)", email))
}

func PlatformAdminByID(ctx context.Context, pool *pgxpool.Pool, id string) (*PlatformAdmin, error) {
	return scanPlatformAdmin(pool.QueryRow(ctx,
		"SELECT "+platformAdminCols+" FROM public.platform_admins WHERE id=$1", id))
}

func ListPlatformAdmins(ctx context.Context, pool *pgxpool.Pool) ([]PlatformAdmin, error) {
	rows, err := pool.Query(ctx, "SELECT "+platformAdminCols+" FROM public.platform_admins ORDER BY created_at")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []PlatformAdmin
	for rows.Next() {
		a, err := scanPlatformAdmin(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *a)
	}
	return out, rows.Err()
}

func InsertPlatformAdmin(ctx context.Context, pool *pgxpool.Pool, a *PlatformAdmin) error {
	_, err := pool.Exec(ctx,
		`INSERT INTO public.platform_admins (id, email, full_name, password_hash, status)
		 VALUES ($1, lower($2), $3, $4, 'active')`,
		a.ID, a.Email, a.FullName, a.PasswordHash)
	return err
}

func DeletePlatformAdmin(ctx context.Context, pool *pgxpool.Pool, id string) error {
	_, err := pool.Exec(ctx, "DELETE FROM public.platform_admins WHERE id=$1", id)
	return err
}

func CountPlatformAdmins(ctx context.Context, pool *pgxpool.Pool) (int, error) {
	var n int
	err := pool.QueryRow(ctx, "SELECT count(*) FROM public.platform_admins").Scan(&n)
	return n, err
}

func TouchPlatformAdminLogin(ctx context.Context, pool *pgxpool.Pool, id string) error {
	_, err := pool.Exec(ctx, "UPDATE public.platform_admins SET last_login_at=now() WHERE id=$1", id)
	return err
}

// --- admin refresh tokens (rotating, public schema) ---

func StoreAdminRefreshToken(ctx context.Context, pool *pgxpool.Pool, id, adminID, tokenHash string, expires time.Time) error {
	_, err := pool.Exec(ctx,
		"INSERT INTO public.platform_admin_refresh_tokens (id, admin_id, token_hash, expires_at) VALUES ($1,$2,$3,$4)",
		id, adminID, tokenHash, expires)
	return err
}

// ConsumeAdminRefreshToken atomically revokes a live admin refresh token and
// returns its admin id.
func ConsumeAdminRefreshToken(ctx context.Context, pool *pgxpool.Pool, tokenHash string) (string, error) {
	var adminID string
	err := pool.QueryRow(ctx,
		`UPDATE public.platform_admin_refresh_tokens SET revoked_at = now()
		 WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > now()
		 RETURNING admin_id`, tokenHash).Scan(&adminID)
	return adminID, err
}

func RevokeAdminRefreshTokens(ctx context.Context, pool *pgxpool.Pool, adminID string) error {
	_, err := pool.Exec(ctx,
		"UPDATE public.platform_admin_refresh_tokens SET revoked_at = now() WHERE admin_id = $1 AND revoked_at IS NULL", adminID)
	return err
}

// ---------------------------------------------------------------------------
// Platform audit — accountability for mutating super-admin actions.
// ---------------------------------------------------------------------------

type PlatformAuditEntry struct {
	ID             string `json:"id"`
	AdminID        string `json:"admin_id"`
	AdminEmail     string `json:"admin_email"`
	Action         string `json:"action"`
	TargetTenantID string `json:"target_tenant_id"`
	Detail         []byte `json:"-"`
	IP             string `json:"ip"`
}

func InsertPlatformAudit(ctx context.Context, pool *pgxpool.Pool, e *PlatformAuditEntry) error {
	var target *string
	if e.TargetTenantID != "" {
		target = &e.TargetTenantID
	}
	detail := e.Detail
	if len(detail) == 0 {
		detail = []byte("{}")
	}
	_, err := pool.Exec(ctx,
		`INSERT INTO public.platform_audit (id, admin_id, admin_email, action, target_tenant_id, detail, ip)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		e.ID, e.AdminID, e.AdminEmail, e.Action, target, detail, e.IP)
	return err
}

// ---------------------------------------------------------------------------
// Cross-tenant tenant queries + metrics (used only by the admin control plane).
// ---------------------------------------------------------------------------

// AllTenants lists every firm, including suspended/deleted ones.
func AllTenants(ctx context.Context, pool *pgxpool.Pool) ([]Tenant, error) {
	rows, err := pool.Query(ctx, "SELECT "+tenantCols+" FROM public.tenants ORDER BY created_at DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Tenant
	for rows.Next() {
		t, err := scanTenant(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *t)
	}
	return out, rows.Err()
}

func UpdateTenantStatus(ctx context.Context, pool *pgxpool.Pool, id, status string) error {
	_, err := pool.Exec(ctx, "UPDATE public.tenants SET status=$2 WHERE id=$1", id, status)
	return err
}

func UpdateTenantPlan(ctx context.Context, pool *pgxpool.Pool, id, plan string) error {
	_, err := pool.Exec(ctx, "UPDATE public.tenants SET plan=$2 WHERE id=$1", id, plan)
	return err
}

// TenantMetrics is a lightweight per-firm usage summary for the control panel.
type TenantMetrics struct {
	Users        int   `json:"users"`
	Files        int   `json:"files"`
	Archives     int   `json:"archives"`
	StorageBytes int64 `json:"storage_bytes"`
}

// TenantCounts runs inside a tenant-schema transaction (search_path pinned) and
// returns that firm's row counts. Call via db.WithTenant.
func TenantCounts(ctx context.Context, tx pgx.Tx) (*TenantMetrics, error) {
	var m TenantMetrics
	err := tx.QueryRow(ctx, `SELECT
		(SELECT count(*) FROM users),
		(SELECT count(*) FROM files),
		(SELECT count(*) FROM archives),
		COALESCE((SELECT sum(size_bytes) FROM archives), 0)`).
		Scan(&m.Users, &m.Files, &m.Archives, &m.StorageBytes)
	if err != nil {
		return nil, err
	}
	return &m, nil
}

// --- Plans catalog (public) ---

type Plan struct {
	Code     string          `json:"code"`
	Name     string          `json:"name"`
	PriceKES int64           `json:"price_kes"`
	Limits   json.RawMessage `json:"limits"`
}

func ListPlans(ctx context.Context, pool *pgxpool.Pool) ([]Plan, error) {
	rows, err := pool.Query(ctx, "SELECT code, name, price_kes::bigint, limits FROM public.plans ORDER BY price_kes")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Plan
	for rows.Next() {
		var p Plan
		if err := rows.Scan(&p.Code, &p.Name, &p.PriceKES, &p.Limits); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func PlanExists(ctx context.Context, pool *pgxpool.Pool, code string) (bool, error) {
	var exists bool
	err := pool.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM public.plans WHERE code=$1)", code).Scan(&exists)
	return exists, err
}

// ---------------------------------------------------------------------------
// Cross-tenant audit_log read (requires db.WithPlatformAdmin to pass RLS).
// ---------------------------------------------------------------------------

type AuditRow struct {
	CreatedAt time.Time `json:"created_at"`
	TenantID  string    `json:"tenant_id"`
	FirmName  string    `json:"firm_name"`
	UserID    *string   `json:"user_id,omitempty"`
	Action    string    `json:"action"`
	Resource  string    `json:"resource"`
	Status    int       `json:"status"`
	IP        string    `json:"ip"`
}

// ListAuditLog reads the platform-wide audit trail. tx must come from
// db.WithPlatformAdmin so the RLS bypass policy applies. tenantID filters to a
// single firm when non-empty.
func ListAuditLog(ctx context.Context, tx pgx.Tx, tenantID string, limit int) ([]AuditRow, error) {
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	q := `SELECT a.created_at, a.tenant_id, COALESCE(t.name,''), a.user_id, a.action, a.resource, a.status, a.ip
	      FROM audit_log a LEFT JOIN tenants t ON t.id = a.tenant_id`
	args := []any{}
	if tenantID != "" {
		q += " WHERE a.tenant_id = $1 ORDER BY a.created_at DESC LIMIT $2"
		args = append(args, tenantID, limit)
	} else {
		q += " ORDER BY a.created_at DESC LIMIT $1"
		args = append(args, limit)
	}
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AuditRow
	for rows.Next() {
		var r AuditRow
		if err := rows.Scan(&r.CreatedAt, &r.TenantID, &r.FirmName, &r.UserID, &r.Action, &r.Resource, &r.Status, &r.IP); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
