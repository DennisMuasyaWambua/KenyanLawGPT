package rbac

// Roles, ordered by privilege. "client" is portal-only and is additionally
// scoped to their own matters at the query layer.
const (
	RoleOwner     = "owner"
	RolePartner   = "partner"
	RoleAssociate = "associate"
	RoleParalegal = "paralegal"
	RoleClient    = "client"
)

var rank = map[string]int{
	RoleOwner:     5,
	RolePartner:   4,
	RoleAssociate: 3,
	RoleParalegal: 2,
	RoleClient:    1,
}

func Valid(role string) bool { _, ok := rank[role]; return ok }

// AtLeast reports whether role has privilege >= min.
func AtLeast(role, min string) bool {
	r, ok := rank[role]
	m, ok2 := rank[min]
	return ok && ok2 && r >= m
}

// IsStaff excludes portal clients from firm-internal endpoints.
func IsStaff(role string) bool { return Valid(role) && role != RoleClient }
