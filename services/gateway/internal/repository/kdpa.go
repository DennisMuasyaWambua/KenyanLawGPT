package repository

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5"
)

type Consent struct {
	ID          string    `json:"id"`
	SubjectType string    `json:"subject_type"` // client|user
	SubjectID   string    `json:"subject_id"`
	Purpose     string    `json:"purpose"` // e.g. "sms_reminders", "document_processing"
	Granted     bool      `json:"granted"`
	GrantedBy   string    `json:"granted_by"`
	Source      string    `json:"source"` // web|paper|verbal
	CreatedAt   time.Time `json:"created_at"`
}

func InsertConsent(ctx context.Context, tx pgx.Tx, c *Consent) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO consent_log (id, subject_type, subject_id, purpose, granted, granted_by, source)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		c.ID, c.SubjectType, c.SubjectID, c.Purpose, c.Granted, c.GrantedBy, c.Source)
	return err
}

func ListConsents(ctx context.Context, tx pgx.Tx, subjectType, subjectID string) ([]Consent, error) {
	q := "SELECT id, subject_type, subject_id, purpose, granted, granted_by, source, created_at FROM consent_log WHERE 1=1"
	args := []any{}
	if subjectType != "" {
		args = append(args, subjectType)
		q += " AND subject_type=$1"
	}
	if subjectID != "" {
		args = append(args, subjectID)
		q += " AND subject_id=$" + itoa(len(args))
	}
	q += " ORDER BY created_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Consent
	for rows.Next() {
		var c Consent
		if err := rows.Scan(&c.ID, &c.SubjectType, &c.SubjectID, &c.Purpose, &c.Granted, &c.GrantedBy, &c.Source, &c.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// ExportSubject collects every personal-data row for a data subject in the
// tenant schema (KDPA data-portability / subject-access request).
func ExportSubject(ctx context.Context, tx pgx.Tx, subjectType, subjectID string) (map[string]any, error) {
	out := map[string]any{
		"subject_type": subjectType,
		"subject_id":   subjectID,
		"exported_at":  time.Now().UTC(),
	}
	collect := func(name, query string, args ...any) error {
		rows, err := tx.Query(ctx, query, args...)
		if err != nil {
			return err
		}
		defer rows.Close()
		var items []map[string]any
		for rows.Next() {
			vals, err := rows.Values()
			if err != nil {
				return err
			}
			m := map[string]any{}
			for i, fd := range rows.FieldDescriptions() {
				m[string(fd.Name)] = normalize(vals[i])
			}
			items = append(items, m)
		}
		out[name] = items
		return rows.Err()
	}
	switch subjectType {
	case "client":
		if err := collect("client", "SELECT * FROM clients WHERE id=$1", subjectID); err != nil {
			return nil, err
		}
		if err := collect("files", "SELECT * FROM files WHERE client_id=$1", subjectID); err != nil {
			return nil, err
		}
		if err := collect("invoices", "SELECT * FROM invoices WHERE client_id=$1", subjectID); err != nil {
			return nil, err
		}
		if err := collect("messages", "SELECT * FROM messages WHERE client_id=$1", subjectID); err != nil {
			return nil, err
		}
		if err := collect("archives",
			"SELECT d.* FROM archives d JOIN files m ON m.id=d.file_id WHERE m.client_id=$1", subjectID); err != nil {
			return nil, err
		}
	case "user":
		if err := collect("user", "SELECT id, email, full_name, role, status, created_at, last_login_at FROM users WHERE id=$1", subjectID); err != nil {
			return nil, err
		}
		if err := collect("time_entries", "SELECT * FROM time_entries WHERE user_id=$1", subjectID); err != nil {
			return nil, err
		}
	}
	if err := collectConsents(ctx, tx, out, subjectType, subjectID); err != nil {
		return nil, err
	}
	return out, nil
}

func collectConsents(ctx context.Context, tx pgx.Tx, out map[string]any, subjectType, subjectID string) error {
	consents, err := ListConsents(ctx, tx, subjectType, subjectID)
	if err != nil {
		return err
	}
	out["consents"] = consents
	return nil
}

func normalize(v any) any {
	switch t := v.(type) {
	case [16]byte: // uuid
		b, _ := json.Marshal(t)
		return string(b)
	default:
		return v
	}
}

// EraseSubject removes/anonymizes the subject's rows in the tenant schema.
// Graph nodes, vectors, and object storage are handled by the caller.
func EraseSubject(ctx context.Context, tx pgx.Tx, subjectType, subjectID string) (int64, error) {
	var total int64
	run := func(q string, args ...any) error {
		tag, err := tx.Exec(ctx, q, args...)
		if err != nil {
			return err
		}
		total += tag.RowsAffected()
		return nil
	}
	switch subjectType {
	case "client":
		if err := run("DELETE FROM messages WHERE client_id=$1", subjectID); err != nil {
			return total, err
		}
		if err := run(`DELETE FROM archive_chunks WHERE archive_id IN
			(SELECT d.id FROM archives d JOIN files m ON m.id=d.file_id WHERE m.client_id=$1)`, subjectID); err != nil {
			return total, err
		}
		if err := run(`DELETE FROM archives WHERE file_id IN (SELECT id FROM files WHERE client_id=$1)`, subjectID); err != nil {
			return total, err
		}
		// Files and invoices are legal/financial records: anonymize the link
		// rather than destroying firm records (KDPA s.40 balancing).
		if err := run("UPDATE files SET client_id=NULL, description='[erased on data-subject request]' WHERE client_id=$1", subjectID); err != nil {
			return total, err
		}
		if err := run("UPDATE users SET status='disabled', email = 'erased+'||id||'@erased.invalid', full_name='[erased]' WHERE client_id=$1", subjectID); err != nil {
			return total, err
		}
		if err := run("DELETE FROM clients WHERE id=$1", subjectID); err != nil {
			return total, err
		}
	case "user":
		if err := run("UPDATE users SET status='disabled', email = 'erased+'||id||'@erased.invalid', full_name='[erased]', password_hash='' WHERE id=$1", subjectID); err != nil {
			return total, err
		}
		if err := run("UPDATE refresh_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", subjectID); err != nil {
			return total, err
		}
	}
	return total, nil
}
