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
	portal.GET("/matters", s.PortalMatters)
	portal.GET("/invoices", s.PortalInvoices)
	portal.GET("/messages", s.PortalMessages)

	// Firm-internal: any firm member (a user with a role); portal clients excluded.
	// Per-route granular gating uses RequirePermission (firm-scoped RBAC).
	perm := func(p string) gin.HandlerFunc { return middleware.RequirePermission(s.DB, p) }
	member := priv.Group("", middleware.RequireFirmMember())
	member.GET("/dashboard", s.Dashboard)

	member.GET("/matters", perm(rbac.PermMattersViewOwn), s.ListMatters)
	member.POST("/matters", perm(rbac.PermMattersCreate), s.CreateMatter)
	member.GET("/matters/:id", perm(rbac.PermMattersViewOwn), s.GetMatter)
	member.PUT("/matters/:id", perm(rbac.PermMattersEdit), s.UpdateMatter)
	member.POST("/matters/:id/events", perm(rbac.PermMattersEdit), s.AddMatterEvent)
	member.POST("/matters/:id/court-dates", perm(rbac.PermMattersEdit), s.AddCourtDate)
	member.POST("/matters/:id/deadlines", perm(rbac.PermMattersEdit), s.AddDeadline)
	member.GET("/matters/:id/judiciary", perm(rbac.PermMattersViewOwn), s.JudiciaryStatus)

	member.GET("/clients", perm(rbac.PermClientsView), s.ListClients)
	member.POST("/clients", perm(rbac.PermClientsManage), s.CreateClient)

	// Calendar: the personal calendar is available to every member; shared-event
	// permissions (calendar.*_shared) are enforced inside the handlers so a
	// single event route can serve both personal and shared events.
	member.GET("/calendar/events", s.ListCalendarEvents)
	member.POST("/calendar/events", s.CreateCalendarEvent)
	member.PUT("/calendar/events/:id", s.UpdateCalendarEvent)
	member.DELETE("/calendar/events/:id", s.DeleteCalendarEvent)

	member.POST("/documents/presign", perm(rbac.PermDocumentsUpload), s.PresignUpload)
	member.GET("/documents", perm(rbac.PermDocumentsView), s.ListDocuments)
	member.POST("/documents/:id/ingest", perm(rbac.PermDocumentsUpload), s.IngestDocument)
	member.GET("/documents/:id/download", perm(rbac.PermDocumentsDownload), s.DownloadDocument)
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
