package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/metrics"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/rbac"
)

// Register wires the full route table with the middleware chain:
// request-id -> CORS -> metrics -> [tenant -> rate-limit -> auth -> member -> permission -> audit].
func (s *Server) Register(r *gin.Engine) {
	r.Use(middleware.RequestID(), middleware.CORS(s.Cfg.CORSOrigins), metrics.HTTP())

	r.GET("/healthz", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok"}) })
	r.GET("/metrics", metrics.Handler())

	// Firm signup happens before a tenant exists.
	r.POST("/api/v1/signup", s.Signup)
	r.POST("/api/v1/signup/google", s.GoogleSignup)

	// Provider webhooks (no tenant subdomain, no JWT; idempotent handlers).
	wh := r.Group("/webhooks")
	wh.POST("/daraja/callback", s.DarajaCallback)
	wh.POST("/at/delivery", s.ATDelivery)

	// Platform super-admin control plane. Registered as a SEPARATE top-level
	// group so it does NOT inherit middleware.Tenant — these routes are
	// cross-tenant and resolve no firm. Auth is the distinct admin JWT.
	admin := r.Group("/api/v1/admin", middleware.RateLimit(s.RDB, s.Cfg.RateLimitPerMin))
	admin.POST("/login", s.AdminLogin)
	admin.POST("/refresh", s.AdminRefresh)
	adminPriv := admin.Group("", middleware.RequirePlatformAdmin(s.Cfg))
	adminPriv.POST("/logout", s.AdminLogout)
	adminPriv.GET("/me", s.AdminMe)
	adminPriv.GET("/stats", s.AdminPlatformStats)
	adminPriv.GET("/tenants", s.AdminListTenants)
	adminPriv.POST("/tenants", s.AdminCreateTenant)
	adminPriv.GET("/tenants/:id", s.AdminGetTenant)
	adminPriv.PATCH("/tenants/:id/status", s.AdminSetTenantStatus)
	adminPriv.PATCH("/tenants/:id/plan", s.AdminSetTenantPlan)
	adminPriv.DELETE("/tenants/:id", s.AdminDeleteTenant)
	adminPriv.POST("/tenants/:id/impersonate", s.AdminImpersonate)
	adminPriv.GET("/plans", s.AdminListPlans)
	adminPriv.GET("/audit", s.AdminAuditLog)
	adminPriv.GET("/admins", s.AdminListAdmins)
	adminPriv.POST("/admins", s.AdminCreateAdmin)
	adminPriv.DELETE("/admins/:id", s.AdminDeleteAdmin)

	api := r.Group("/api/v1", middleware.Tenant(s.DB, s.Cfg), middleware.RateLimit(s.RDB, s.Cfg.RateLimitPerMin))

	// Unauthenticated (tenant-scoped) auth endpoints.
	api.POST("/auth/login", s.Login)
	api.POST("/auth/google", s.GoogleLogin)
	api.POST("/auth/refresh", s.Refresh)
	api.GET("/auth/invite/:token", s.GetInvite)
	api.POST("/auth/invite/:token/accept", s.AcceptInvite)

	// Everything below requires a valid JWT bound to this tenant.
	priv := api.Group("", middleware.Auth(s.Cfg), middleware.Audit(s.DB))
	priv.GET("/auth/me", s.Me)
	priv.POST("/auth/logout", s.Logout)
	priv.GET("/notifications", s.ListNotifications)

	// Client portal — reachable by every role, scoped to own records.
	portal := priv.Group("/portal")
	portal.GET("/files", s.PortalFiles)
	portal.GET("/invoices", s.PortalInvoices)
	portal.GET("/messages", s.PortalMessages)

	// Firm-internal: any firm member (a user with a role); portal clients excluded.
	// Per-route granular gating uses RequirePermission (firm-scoped RBAC).
	perm := func(p string) gin.HandlerFunc { return middleware.RequirePermission(s.DB, p) }
	member := priv.Group("", middleware.RequireFirmMember())
	member.GET("/dashboard", s.Dashboard)

	member.GET("/files", perm(rbac.PermMattersViewOwn), s.ListFiles)
	member.POST("/files", perm(rbac.PermMattersCreate), s.CreateFile)
	member.GET("/files/:id", perm(rbac.PermMattersViewOwn), s.GetFile)
	member.PUT("/files/:id", perm(rbac.PermMattersEdit), s.UpdateFile)
	member.POST("/files/:id/events", perm(rbac.PermMattersEdit), s.AddFileEvent)
	member.POST("/files/:id/court-dates", perm(rbac.PermMattersEdit), s.AddCourtDate)
	member.POST("/files/:id/deadlines", perm(rbac.PermMattersEdit), s.AddDeadline)
	member.GET("/files/:id/judiciary", perm(rbac.PermMattersViewOwn), s.JudiciaryStatus)

	member.GET("/clients", perm(rbac.PermClientsView), s.ListClients)
	member.GET("/clients/:id", perm(rbac.PermClientsView), s.GetClient)
	member.POST("/clients", perm(rbac.PermClientsCreate), s.CreateClient)
	member.PATCH("/clients/:id", perm(rbac.PermClientsEdit), s.UpdateClient)
	member.POST("/clients/:id/conflict-check", perm(rbac.PermClientsAdvanceStage), s.ConflictCheck)
	member.POST("/clients/:id/advance", perm(rbac.PermClientsAdvanceStage), s.AdvanceClientStage)

	// Tasks — assignees can always update their own task's status (checked in the
	// handler), so PATCH gates on the broad view_own permission.
	member.GET("/tasks", perm(rbac.PermTasksViewOwn), s.ListTasks)
	member.POST("/tasks", perm(rbac.PermTasksCreate), s.CreateTask)
	member.PATCH("/tasks/:id", perm(rbac.PermTasksViewOwn), s.UpdateTask)
	member.DELETE("/tasks/:id", perm(rbac.PermTasksCreate), s.DeleteTask)
	member.GET("/files/:id/tasks", perm(rbac.PermTasksViewOwn), s.FileTasks)

	// Case-status dashboard — manager/owner oversight.
	member.GET("/dashboard/cases", perm(rbac.PermMattersViewAll), s.CaseDashboard)

	// Meeting recordings (consent-gated; transcribed/summarized by the AI worker).
	member.GET("/recordings", perm(rbac.PermRecordingsViewOwn), s.ListRecordings)
	member.POST("/recordings", perm(rbac.PermRecordingsCreate), s.CreateRecording)
	member.GET("/recordings/:id", perm(rbac.PermRecordingsViewOwn), s.GetRecording)
	member.POST("/recordings/:id/uploaded", perm(rbac.PermRecordingsCreate), s.MarkRecordingUploaded)
	member.GET("/files/:id/recordings", perm(rbac.PermRecordingsViewOwn), s.FileRecordings)

	// Calendar: the personal calendar is available to every member; shared-event
	// permissions (calendar.*_shared) are enforced inside the handlers so a
	// single event route can serve both personal and shared events.
	member.GET("/calendar/events", s.ListCalendarEvents)
	member.POST("/calendar/events", s.CreateCalendarEvent)
	member.PUT("/calendar/events/:id", s.UpdateCalendarEvent)
	member.DELETE("/calendar/events/:id", s.DeleteCalendarEvent)

	member.POST("/archives/presign", perm(rbac.PermDocumentsUpload), s.PresignUpload)
	member.GET("/archives", perm(rbac.PermDocumentsView), s.ListArchives)
	member.POST("/archives/:id/ingest", perm(rbac.PermDocumentsUpload), s.IngestDocument)
	member.GET("/archives/:id/download", perm(rbac.PermDocumentsDownload), s.DownloadArchive)
	member.GET("/drafts", perm(rbac.PermDocumentsView), s.ListDrafts)

	member.POST("/research/query", perm(rbac.PermResearchQuery), s.ResearchQuery)
	member.POST("/research/reason", perm(rbac.PermResearchReason), s.ResearchReason)
	member.POST("/drafting/stream", perm(rbac.PermDraftingCreate), s.DraftStream)

	member.GET("/messages", perm(rbac.PermCommsView), s.ListMessages)
	member.POST("/messages/send", perm(rbac.PermCommsSend), s.SendMessage)

	member.GET("/time-entries", perm(rbac.PermBillingView), s.ListTimeEntries)
	member.POST("/time-entries", perm(rbac.PermBillingView), s.CreateTimeEntry)
	member.GET("/invoices", perm(rbac.PermBillingView), s.ListInvoices)
	member.POST("/invoices", perm(rbac.PermBillingManage), s.CreateInvoice)
	member.GET("/invoices/:id", perm(rbac.PermBillingView), s.GetInvoice)
	member.POST("/invoices/:id/stk-push", perm(rbac.PermBillingManage), s.STKPush)

	member.POST("/kdpa/consents", s.LogConsent)
	member.GET("/kdpa/consents", s.ListConsents)

	// User & role management.
	member.GET("/users", perm(rbac.PermUsersView), s.ListUsers)
	member.POST("/users", perm(rbac.PermUsersInvite), s.CreateUser)
	member.POST("/users/invite", perm(rbac.PermUsersInvite), s.InviteUser)
	member.PATCH("/users/:id", perm(rbac.PermUsersRemove), s.UpdateUser)
	member.PATCH("/users/:id/role", perm(rbac.PermUsersManageRoles), s.ChangeUserRole)

	member.GET("/permissions", perm(rbac.PermRolesManage), s.ListPermissions)
	member.GET("/role-templates", perm(rbac.PermRolesManage), s.ListRoleTemplates)
	member.GET("/roles", perm(rbac.PermRolesManage), s.ListRoles)
	member.POST("/roles", perm(rbac.PermRolesManage), s.CreateRole)
	member.PATCH("/roles/:id", perm(rbac.PermRolesManage), s.UpdateRole)
	member.DELETE("/roles/:id", perm(rbac.PermRolesManage), s.DeleteRole)

	member.GET("/kdpa/export", perm(rbac.PermKDPAExport), s.ExportSubject)
	member.POST("/kdpa/erasure", perm(rbac.PermKDPAErase), s.EraseSubject)
	member.GET("/kdpa/audit", perm(rbac.PermKDPAViewAudit), s.AuditLog)
}
