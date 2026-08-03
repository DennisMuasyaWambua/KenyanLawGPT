package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// AuditEntry rows live in public.audit_log — a schema-shared table guarded by
// row-level security on app.tenant_id (defense-in-depth on top of the
// schema-per-tenant isolation). Required for KDPA accountability.
type AuditEntry struct {
	ID        string    `json:"id"`
	TenantID  string    `json:"tenant_id"`
	UserID    *string   `json:"user_id"`
	Action    string    `json:"action"` // METHOD /path
	Resource  string    `json:"resource"`
	Status    int       `json:"status"`
	IP        string    `json:"ip"`
	TraceID   string    `json:"trace_id"`
	Detail    []byte    `json:"detail,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

func InsertAudit(ctx context.Context, tx pgx.Tx, a *AuditEntry) error {
	if len(a.Detail) == 0 {
		a.Detail = []byte("{}")
	}
	_, err := tx.Exec(ctx,
		`INSERT INTO public.audit_log (id, tenant_id, user_id, action, resource, status, ip, trace_id, detail)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		a.ID, a.TenantID, a.UserID, a.Action, a.Resource, a.Status, a.IP, a.TraceID, a.Detail)
	return err
}

func ListAudit(ctx context.Context, tx pgx.Tx, tenantID string, limit int) ([]AuditEntry, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	rows, err := tx.Query(ctx,
		`SELECT id, tenant_id, user_id, action, resource, status, ip, trace_id, detail, created_at
		 FROM public.audit_log WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2`, tenantID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AuditEntry
	for rows.Next() {
		var a AuditEntry
		if err := rows.Scan(&a.ID, &a.TenantID, &a.UserID, &a.Action, &a.Resource, &a.Status, &a.IP, &a.TraceID, &a.Detail, &a.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
