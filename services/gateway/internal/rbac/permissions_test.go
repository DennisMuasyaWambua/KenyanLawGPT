package rbac

import "testing"

func TestCatalogValidation(t *testing.T) {
	if !ValidPermission(PermMattersCreate) || !ValidPermission(PermCalendarViewShared) {
		t.Error("known permissions must validate")
	}
	if ValidPermission("matters.nope") || ValidPermission("") {
		t.Error("unknown permissions must not validate")
	}
	if len(AllPermissions()) != len(Catalog) {
		t.Error("AllPermissions must cover the whole catalog")
	}
}

func TestManagingPartnerTemplateHasEveryPermission(t *testing.T) {
	top := DefaultTemplates[0]
	if top.Name != "Managing Partner" || !top.Protected {
		t.Fatalf("first template must be the protected Managing Partner, got %+v", top)
	}
	if len(top.Permissions) != len(Catalog) {
		t.Fatalf("Managing Partner must hold all %d permissions, has %d", len(Catalog), len(top.Permissions))
	}
}

func TestTemplatesReferenceOnlyCatalogPermissions(t *testing.T) {
	for _, tpl := range DefaultTemplates {
		for _, p := range tpl.Permissions {
			if !ValidPermission(p) {
				t.Errorf("template %q references unknown permission %q", tpl.Name, p)
			}
		}
	}
}
