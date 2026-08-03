package rbac

import "testing"

func TestRoleHierarchy(t *testing.T) {
	if !AtLeast(RoleOwner, RolePartner) {
		t.Error("owner should outrank partner")
	}
	if AtLeast(RoleParalegal, RoleAssociate) {
		t.Error("paralegal must not reach associate-gated routes")
	}
	if AtLeast(RoleClient, RoleParalegal) {
		t.Error("client must not reach staff routes")
	}
	if AtLeast("superadmin", RoleClient) || AtLeast(RoleOwner, "root") {
		t.Error("unknown roles must never pass")
	}
}

func TestIsStaff(t *testing.T) {
	for _, r := range []string{RoleOwner, RolePartner, RoleAssociate, RoleParalegal} {
		if !IsStaff(r) {
			t.Errorf("%s should be staff", r)
		}
	}
	if IsStaff(RoleClient) || IsStaff("") || IsStaff("admin") {
		t.Error("client/unknown roles must not be staff")
	}
}
