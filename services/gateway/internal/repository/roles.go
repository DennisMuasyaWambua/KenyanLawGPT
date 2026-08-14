package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// Role is a firm-scoped role (lives in the tenant schema). Permissions and
// MemberCount are populated by the list/get helpers for the management UI.
type Role struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	IsProtected bool      `json:"is_protected"`
	CreatedAt   time.Time `json:"created_at"`
	Permissions []string  `json:"permissions"`
	MemberCount int       `json:"member_count"`
}

func scanRole(row pgx.Row) (*Role, error) {
	var r Role
	if err := row.Scan(&r.ID, &r.Name, &r.Description, &r.IsProtected, &r.CreatedAt); err != nil {
		return nil, err
	}
	return &r, nil
}

const roleCols = "id, name, description, is_protected, created_at"

// ListRoles returns every firm role with its permissions and member count.
func ListRoles(ctx context.Context, tx pgx.Tx) ([]Role, error) {
	rows, err := tx.Query(ctx, "SELECT "+roleCols+" FROM roles ORDER BY is_protected DESC, lower(name)")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var roles []Role
	idx := map[string]int{}
	for rows.Next() {
		r, err := scanRole(rows)
		if err != nil {
			return nil, err
		}
		r.Permissions = []string{}
		idx[r.ID] = len(roles)
		roles = append(roles, *r)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Permissions per role.
	prows, err := tx.Query(ctx, "SELECT role_id, permission FROM role_permissions ORDER BY permission")
	if err != nil {
		return nil, err
	}
	defer prows.Close()
	for prows.Next() {
		var roleID, perm string
		if err := prows.Scan(&roleID, &perm); err != nil {
			return nil, err
		}
		if i, ok := idx[roleID]; ok {
			roles[i].Permissions = append(roles[i].Permissions, perm)
		}
	}
	if err := prows.Err(); err != nil {
		return nil, err
	}

	// Member counts.
	crows, err := tx.Query(ctx, "SELECT role_id, count(*) FROM users WHERE role_id IS NOT NULL GROUP BY role_id")
	if err != nil {
		return nil, err
	}
	defer crows.Close()
	for crows.Next() {
		var roleID string
		var n int
		if err := crows.Scan(&roleID, &n); err != nil {
			return nil, err
		}
		if i, ok := idx[roleID]; ok {
			roles[i].MemberCount = n
		}
	}
	return roles, crows.Err()
}

// GetRole returns one role with its permissions (no member count).
func GetRole(ctx context.Context, tx pgx.Tx, id string) (*Role, error) {
	r, err := scanRole(tx.QueryRow(ctx, "SELECT "+roleCols+" FROM roles WHERE id = $1", id))
	if err != nil {
		return nil, err
	}
	perms, err := RolePermissions(ctx, tx, id)
	if err != nil {
		return nil, err
	}
	r.Permissions = perms
	return r, nil
}

// RoleByName looks a role up by case-insensitive name (unique within the firm).
func RoleByName(ctx context.Context, tx pgx.Tx, name string) (*Role, error) {
	return scanRole(tx.QueryRow(ctx, "SELECT "+roleCols+" FROM roles WHERE lower(name) = lower($1)", name))
}

// RolePermissions returns the permission keys granted to a role.
func RolePermissions(ctx context.Context, tx pgx.Tx, roleID string) ([]string, error) {
	rows, err := tx.Query(ctx, "SELECT permission FROM role_permissions WHERE role_id = $1 ORDER BY permission", roleID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var p string
		if err := rows.Scan(&p); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// RoleMemberCount counts users currently assigned to a role.
func RoleMemberCount(ctx context.Context, tx pgx.Tx, roleID string) (int, error) {
	var n int
	err := tx.QueryRow(ctx, "SELECT count(*) FROM users WHERE role_id = $1", roleID).Scan(&n)
	return n, err
}

// CreateRole inserts a role and its permission grants.
func CreateRole(ctx context.Context, tx pgx.Tx, r *Role, perms []string) error {
	if _, err := tx.Exec(ctx,
		"INSERT INTO roles (id, name, description, is_protected) VALUES ($1,$2,$3,$4)",
		r.ID, r.Name, r.Description, r.IsProtected); err != nil {
		return err
	}
	return insertRolePermissions(ctx, tx, r.ID, perms)
}

// UpdateRoleMeta updates a role's name/description (permissions handled
// separately via SetRolePermissions).
func UpdateRoleMeta(ctx context.Context, tx pgx.Tx, id, name, description string) error {
	_, err := tx.Exec(ctx, "UPDATE roles SET name=$2, description=$3 WHERE id=$1", id, name, description)
	return err
}

// SetRolePermissions replaces a role's permission set wholesale.
func SetRolePermissions(ctx context.Context, tx pgx.Tx, roleID string, perms []string) error {
	if _, err := tx.Exec(ctx, "DELETE FROM role_permissions WHERE role_id = $1", roleID); err != nil {
		return err
	}
	return insertRolePermissions(ctx, tx, roleID, perms)
}

func insertRolePermissions(ctx context.Context, tx pgx.Tx, roleID string, perms []string) error {
	for _, p := range perms {
		if _, err := tx.Exec(ctx,
			"INSERT INTO role_permissions (role_id, permission) VALUES ($1,$2) ON CONFLICT DO NOTHING",
			roleID, p); err != nil {
			return err
		}
	}
	return nil
}

// DeleteRole removes a role. Callers must ensure it is neither protected nor
// still assigned to members (ON DELETE RESTRICT on users.role_id also guards).
func DeleteRole(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "DELETE FROM roles WHERE id = $1", id)
	return err
}
