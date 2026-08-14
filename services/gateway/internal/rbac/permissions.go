package rbac

// Permission catalog: a fixed, application-defined set of granular actions
// grouped by resource. This is the single source of truth — role_permissions
// rows store these keys as text and are validated against ValidPermission on
// write. Roles are firm-scoped (per tenant schema); permissions are global.

// Permission keys, grouped by resource.
const (
	PermMattersCreate  = "matters.create"
	PermMattersViewOwn = "matters.view_own"
	PermMattersViewAll = "matters.view_all"
	PermMattersEdit    = "matters.edit"
	PermMattersDelete  = "matters.delete"

	PermDocumentsUpload   = "documents.upload"
	PermDocumentsView     = "documents.view"
	PermDocumentsDownload = "documents.download"
	PermDocumentsDelete   = "documents.delete"

	PermResearchQuery  = "research.query"
	PermResearchReason = "research.reason"

	PermDraftingCreate = "drafting.create"

	PermClientsView         = "clients.view"
	PermClientsManage       = "clients.manage" // deprecated: kept for existing grants
	PermClientsCreate       = "clients.create"
	PermClientsEdit         = "clients.edit"
	PermClientsAdvanceStage = "clients.advance_stage"

	PermTasksCreate  = "tasks.create"
	PermTasksAssign  = "tasks.assign"
	PermTasksViewOwn = "tasks.view_own"
	PermTasksViewAll = "tasks.view_all"

	PermRecordingsCreate  = "recordings.create"
	PermRecordingsViewOwn = "recordings.view_own"
	PermRecordingsViewAll = "recordings.view_all"

	PermBillingView   = "billing.view"
	PermBillingManage = "billing.manage"

	PermCalendarViewShared   = "calendar.view_shared"
	PermCalendarCreateShared = "calendar.create_shared"
	PermCalendarEditShared   = "calendar.edit_shared"
	PermCalendarDeleteShared = "calendar.delete_shared"

	PermCommsView = "comms.view"
	PermCommsSend = "comms.send"

	PermUsersInvite      = "users.invite"
	PermUsersManageRoles = "users.manage_roles"
	PermUsersRemove      = "users.remove"
	PermUsersView        = "users.view"

	PermRolesManage = "roles.manage"

	PermFirmSettingsEdit = "firm_settings.edit"

	PermKDPAViewAudit = "kdpa.view_audit"
	PermKDPAExport    = "kdpa.export"
	PermKDPAErase     = "kdpa.erase"
)

// PermissionDef describes one catalog entry for the management UI.
type PermissionDef struct {
	Key      string `json:"key"`
	Resource string `json:"resource"`
	Action   string `json:"action"`
	Label    string `json:"label"`
}

// Catalog is the ordered permission catalog, grouped by resource. Order is
// stable so the UI renders consistently.
var Catalog = []PermissionDef{
	{PermMattersCreate, "matters", "create", "Create matters"},
	{PermMattersViewOwn, "matters", "view_own", "View own matters"},
	{PermMattersViewAll, "matters", "view_all", "View all firm matters"},
	{PermMattersEdit, "matters", "edit", "Edit matters"},
	{PermMattersDelete, "matters", "delete", "Delete matters"},

	{PermDocumentsUpload, "documents", "upload", "Upload documents"},
	{PermDocumentsView, "documents", "view", "View documents & drafts"},
	{PermDocumentsDownload, "documents", "download", "Download documents"},
	{PermDocumentsDelete, "documents", "delete", "Delete documents"},

	{PermResearchQuery, "research", "query", "Run legal research queries"},
	{PermResearchReason, "research", "reason", "Run deep-reasoning research"},

	{PermDraftingCreate, "drafting", "create", "Generate drafts"},

	{PermClientsView, "clients", "view", "View clients"},
	{PermClientsCreate, "clients", "create", "Create clients (intake)"},
	{PermClientsEdit, "clients", "edit", "Edit client details"},
	{PermClientsAdvanceStage, "clients", "advance_stage", "Advance clients through onboarding"},

	{PermTasksCreate, "tasks", "create", "Create, edit & delete tasks"},
	{PermTasksAssign, "tasks", "assign", "Assign tasks to other members"},
	{PermTasksViewOwn, "tasks", "view_own", "View own tasks"},
	{PermTasksViewAll, "tasks", "view_all", "View all firm tasks"},

	{PermRecordingsCreate, "recordings", "create", "Record & transcribe meetings"},
	{PermRecordingsViewOwn, "recordings", "view_own", "View own recordings"},
	{PermRecordingsViewAll, "recordings", "view_all", "View all firm recordings"},

	{PermBillingView, "billing", "view", "View time entries & invoices"},
	{PermBillingManage, "billing", "manage", "Create invoices & take payments"},

	{PermCalendarViewShared, "calendar", "view_shared", "View the shared firm calendar"},
	{PermCalendarCreateShared, "calendar", "create_shared", "Create shared events"},
	{PermCalendarEditShared, "calendar", "edit_shared", "Edit shared events"},
	{PermCalendarDeleteShared, "calendar", "delete_shared", "Delete shared events"},

	{PermCommsView, "comms", "view", "View messages"},
	{PermCommsSend, "comms", "send", "Send messages"},

	{PermUsersInvite, "users", "invite", "Invite & add firm members"},
	{PermUsersManageRoles, "users", "manage_roles", "Change members' roles"},
	{PermUsersRemove, "users", "remove", "Suspend or remove members"},
	{PermUsersView, "users", "view", "View firm members"},

	{PermRolesManage, "roles", "manage", "Create & edit roles and permissions"},

	{PermFirmSettingsEdit, "firm_settings", "edit", "Edit firm settings"},

	{PermKDPAViewAudit, "kdpa", "view_audit", "View the KDPA audit log"},
	{PermKDPAExport, "kdpa", "export", "Export a data subject's records"},
	{PermKDPAErase, "kdpa", "erase", "Erase a data subject's records"},
}

// AllPermissions returns every permission key in catalog order.
func AllPermissions() []string {
	out := make([]string, len(Catalog))
	for i, p := range Catalog {
		out[i] = p.Key
	}
	return out
}

var permSet = func() map[string]bool {
	m := make(map[string]bool, len(Catalog))
	for _, p := range Catalog {
		m[p.Key] = true
	}
	return m
}()

// ValidPermission reports whether key is a known catalog permission.
func ValidPermission(key string) bool { return permSet[key] }

// RoleTemplate is a suggested starting role offered during onboarding. Only the
// Owner role is auto-created; the rest are pre-filled suggestions the owner can
// adopt and customize.
type RoleTemplate struct {
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Protected   bool     `json:"is_protected"`
	Permissions []string `json:"permissions"`
}

// DefaultTemplates are the suggested role presets. Owner is listed first and is
// the only one created automatically (with the full catalog).
var DefaultTemplates = []RoleTemplate{
	{
		Name: "Owner", Description: "Full access to the firm workspace",
		Protected: true, Permissions: AllPermissions(),
	},
	{
		Name: "Partner", Description: "Senior advocate — firm management",
		Permissions: []string{
			PermMattersCreate, PermMattersViewOwn, PermMattersViewAll, PermMattersEdit, PermMattersDelete,
			PermDocumentsUpload, PermDocumentsView, PermDocumentsDownload, PermDocumentsDelete,
			PermResearchQuery, PermResearchReason, PermDraftingCreate,
			PermClientsView, PermClientsCreate, PermClientsEdit, PermClientsAdvanceStage,
			PermBillingView, PermBillingManage,
			PermCalendarViewShared, PermCalendarCreateShared, PermCalendarEditShared, PermCalendarDeleteShared,
			PermCommsView, PermCommsSend,
			PermTasksCreate, PermTasksAssign, PermTasksViewOwn, PermTasksViewAll,
			PermRecordingsCreate, PermRecordingsViewOwn, PermRecordingsViewAll,
			PermUsersInvite, PermUsersView, PermRolesManage, PermKDPAViewAudit,
		},
	},
	{
		Name: "Associate", Description: "Advocate handling matters",
		Permissions: []string{
			PermMattersCreate, PermMattersViewOwn, PermMattersViewAll, PermMattersEdit,
			PermDocumentsUpload, PermDocumentsView, PermDocumentsDownload,
			PermResearchQuery, PermResearchReason, PermDraftingCreate,
			PermClientsView, PermClientsCreate, PermClientsEdit, PermClientsAdvanceStage,
			PermCalendarViewShared, PermCalendarCreateShared, PermCalendarEditShared,
			PermCommsView, PermCommsSend,
			PermTasksCreate, PermTasksViewOwn, PermTasksViewAll,
			PermRecordingsCreate, PermRecordingsViewOwn,
		},
	},
	{
		Name: "Paralegal", Description: "Support staff — limited access",
		Permissions: []string{
			PermMattersViewOwn,
			PermDocumentsUpload, PermDocumentsView,
			PermResearchQuery,
			PermClientsView,
			PermCalendarViewShared,
			PermCommsView,
			PermTasksViewOwn,
			PermRecordingsCreate, PermRecordingsViewOwn,
		},
	},
	{
		Name: "Billing Clerk", Description: "Finance & invoicing",
		Permissions: []string{
			PermBillingView, PermBillingManage,
			PermMattersViewAll, PermClientsView,
			PermCalendarViewShared,
		},
	},
}
