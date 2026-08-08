package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/metrics"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/rbac"
)

// Register wires the full route table with the middleware chain:
// request-id -> CORS -> metrics -> [tenant -> rate-limit -> auth -> rbac -> audit].
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

	// Firm-internal: staff only (owner/partner/associate/paralegal).
	staff := priv.Group("", middleware.RequireStaff())
	staff.GET("/dashboard", s.Dashboard)

	staff.GET("/matters", s.ListMatters)
	staff.POST("/matters", s.CreateMatter)
	staff.GET("/matters/:id", s.GetMatter)
	staff.PUT("/matters/:id", s.UpdateMatter)
	staff.POST("/matters/:id/events", s.AddMatterEvent)
	staff.POST("/matters/:id/court-dates", s.AddCourtDate)
	staff.POST("/matters/:id/deadlines", s.AddDeadline)
	staff.GET("/matters/:id/judiciary", s.JudiciaryStatus)

	staff.GET("/clients", s.ListClients)
	staff.POST("/clients", s.CreateClient)

	staff.GET("/calendar/events", s.ListCalendarEvents)
	staff.POST("/calendar/events", s.CreateCalendarEvent)
	staff.PUT("/calendar/events/:id", s.UpdateCalendarEvent)
	staff.DELETE("/calendar/events/:id", s.DeleteCalendarEvent)

	staff.POST("/documents/presign", s.PresignUpload)
	staff.GET("/documents", s.ListDocuments)
	staff.POST("/documents/:id/ingest", s.IngestDocument)
	staff.GET("/documents/:id/download", s.DownloadDocument)
	staff.GET("/drafts", s.ListDrafts)

	staff.POST("/research/query", s.ResearchQuery)
	staff.POST("/research/reason", s.ResearchReason)
	staff.POST("/drafting/stream", s.DraftStream)

	staff.GET("/messages", s.ListMessages)
	staff.POST("/messages/send", s.SendMessage)

	staff.GET("/time-entries", s.ListTimeEntries)
	staff.POST("/time-entries", s.CreateTimeEntry)
	staff.GET("/invoices", s.ListInvoices)
	staff.POST("/invoices", s.CreateInvoice)
	staff.GET("/invoices/:id", s.GetInvoice)
	staff.POST("/invoices/:id/stk-push", s.STKPush)

	staff.POST("/kdpa/consents", s.LogConsent)
	staff.GET("/kdpa/consents", s.ListConsents)

	// Partner+ management surface.
	partner := priv.Group("", middleware.RequireRole(rbac.RolePartner))
	partner.GET("/users", s.ListUsers)
	partner.POST("/users", s.CreateUser)
	partner.POST("/users/invite", s.InviteUser)
	partner.PATCH("/users/:id", s.UpdateUser)
	partner.GET("/kdpa/export", s.ExportSubject)
	partner.POST("/kdpa/erasure", s.EraseSubject)
	partner.GET("/kdpa/audit", s.AuditLog)
}
