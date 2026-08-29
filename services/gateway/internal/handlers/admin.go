package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/services"
)

// ---------------------------------------------------------------------------
// Super-admin control plane. Every handler here runs OUTSIDE tenant scope
// (registered on a route group without middleware.Tenant) and is gated by
// middleware.RequirePlatformAdmin. Mutating actions write platform_audit.
// ---------------------------------------------------------------------------

func (s *Server) setAdminCookies(c *gin.Context, access, refresh string) {
	secure := s.Cfg.Env == "prod"
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie("wakili_admin_at", access, int(s.Cfg.AccessTTL.Seconds()), "/api/v1/admin", "", secure, true)
	c.SetCookie("wakili_admin_rt", refresh, int(s.Cfg.RefreshTTL.Seconds()), "/api/v1/admin", "", secure, true)
}

func (s *Server) issueAdminTokens(c *gin.Context, admin *repository.PlatformAdmin) (gin.H, error) {
	access, err := auth.IssueAdminToken(s.Cfg.JWTSecret, admin.ID, admin.Email, s.Cfg.AccessTTL)
	if err != nil {
		return nil, err
	}
	raw, hash, err := auth.NewRefreshToken()
	if err != nil {
		return nil, err
	}
	if err := repository.StoreAdminRefreshToken(c.Request.Context(), s.DB.Pool,
		uuid.NewString(), admin.ID, hash, time.Now().Add(s.Cfg.RefreshTTL)); err != nil {
		return nil, err
	}
	s.setAdminCookies(c, access, raw)
	return gin.H{
		"access_token":  access,
		"refresh_token": raw,
		"admin":         gin.H{"id": admin.ID, "email": admin.Email, "full_name": admin.FullName},
	}, nil
}

// adminAudit records a mutating super-admin action (best effort).
func (s *Server) adminAudit(c *gin.Context, action, targetTenant string, detail gin.H) {
	e := &repository.PlatformAuditEntry{
		ID: uuid.NewString(), Action: action, TargetTenantID: targetTenant, IP: c.ClientIP(),
	}
	if cl := middleware.AdminFrom(c); cl != nil {
		e.AdminID = cl.AdminID
		e.AdminEmail = cl.Email
	}
	if detail != nil {
		if b, err := json.Marshal(detail); err == nil {
			e.Detail = b
		}
	}
	if err := repository.InsertPlatformAudit(c.Request.Context(), s.DB.Pool, e); err != nil {
		logging.L(c.Request.Context()).Error("platform audit insert failed", "err", err)
	}
}

// --- auth ---

func (s *Server) AdminLogin(c *gin.Context) {
	var in struct {
		Email    string `json:"email" binding:"required"`
		Password string `json:"password" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	admin, err := repository.PlatformAdminByEmail(c.Request.Context(), s.DB.Pool, in.Email)
	if err == pgx.ErrNoRows || (err == nil && !auth.CheckPassword(admin.PasswordHash, in.Password)) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid email or password"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "login failed"})
		return
	}
	if admin.Status != "active" {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin account disabled"})
		return
	}
	_ = repository.TouchPlatformAdminLogin(c.Request.Context(), s.DB.Pool, admin.ID)
	resp, err := s.issueAdminTokens(c, admin)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "token issue failed"})
		return
	}
	c.JSON(http.StatusOK, resp)
}

func (s *Server) AdminRefresh(c *gin.Context) {
	var in struct {
		RefreshToken string `json:"refresh_token"`
	}
	_ = c.ShouldBindJSON(&in)
	if in.RefreshToken == "" {
		if ck, err := c.Cookie("wakili_admin_rt"); err == nil {
			in.RefreshToken = ck
		}
	}
	if in.RefreshToken == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "missing refresh token"})
		return
	}
	adminID, err := repository.ConsumeAdminRefreshToken(c.Request.Context(), s.DB.Pool, auth.HashRefreshToken(in.RefreshToken))
	if err == pgx.ErrNoRows {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "refresh token invalid or already used"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "refresh failed"})
		return
	}
	admin, err := repository.PlatformAdminByID(c.Request.Context(), s.DB.Pool, adminID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "refresh failed"})
		return
	}
	resp, err := s.issueAdminTokens(c, admin)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "token issue failed"})
		return
	}
	c.JSON(http.StatusOK, resp)
}

func (s *Server) AdminLogout(c *gin.Context) {
	if cl := middleware.AdminFrom(c); cl != nil {
		_ = repository.RevokeAdminRefreshTokens(c.Request.Context(), s.DB.Pool, cl.AdminID)
	}
	s.setAdminCookies(c, "", "")
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) AdminMe(c *gin.Context) {
	cl := middleware.AdminFrom(c)
	admin, err := repository.PlatformAdminByID(c.Request.Context(), s.DB.Pool, cl.AdminID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "lookup failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"admin": admin})
}

// --- tenants ---

type tenantWithMetrics struct {
	repository.Tenant
	Metrics *repository.TenantMetrics `json:"metrics"`
}

func (s *Server) tenantMetrics(c *gin.Context, t *repository.Tenant) *repository.TenantMetrics {
	if t.Status == "deleted" {
		return nil
	}
	var m *repository.TenantMetrics
	_ = s.DB.WithTenant(c.Request.Context(), t.ID, t.SchemaName, func(tx pgx.Tx) error {
		got, err := repository.TenantCounts(c.Request.Context(), tx)
		if err == nil {
			m = got
		}
		return err
	})
	return m
}

func (s *Server) AdminListTenants(c *gin.Context) {
	tenants, err := repository.AllTenants(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "list failed"})
		return
	}
	out := make([]tenantWithMetrics, 0, len(tenants))
	for i := range tenants {
		t := tenants[i]
		out = append(out, tenantWithMetrics{Tenant: t, Metrics: s.tenantMetrics(c, &t)})
	}
	c.JSON(http.StatusOK, gin.H{"tenants": out})
}

func (s *Server) AdminGetTenant(c *gin.Context) {
	t, err := repository.TenantByID(c.Request.Context(), s.DB.Pool, c.Param("id"))
	if err == pgx.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "firm not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "lookup failed"})
		return
	}
	var owner *repository.User
	if t.Status != "deleted" && t.OwnerUserID != nil {
		_ = s.DB.WithTenant(c.Request.Context(), t.ID, t.SchemaName, func(tx pgx.Tx) error {
			if u, e := repository.UserByID(c.Request.Context(), tx, *t.OwnerUserID); e == nil {
				owner = u
			}
			return nil
		})
	}
	c.JSON(http.StatusOK, gin.H{"tenant": t, "metrics": s.tenantMetrics(c, t), "owner": owner})
}

func (s *Server) AdminCreateTenant(c *gin.Context) {
	var in services.ProvisionInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	tenant, owner, err := services.ProvisionTenant(c.Request.Context(), s.DB, s.Cfg, &in)
	if err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": err.Error()})
		return
	}
	s.adminAudit(c, "tenant.create", tenant.ID, gin.H{"slug": tenant.Slug, "owner_email": owner.Email})
	c.JSON(http.StatusCreated, gin.H{"tenant": tenant, "owner": gin.H{"id": owner.ID, "email": owner.Email}})
}

func (s *Server) AdminSetTenantStatus(c *gin.Context) {
	id := c.Param("id")
	var in struct {
		Status string `json:"status" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.Status != "active" && in.Status != "suspended" {
		badRequest(c, "status must be 'active' or 'suspended'")
		return
	}
	if err := repository.UpdateTenantStatus(c.Request.Context(), s.DB.Pool, id, in.Status); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "update failed"})
		return
	}
	s.adminAudit(c, "tenant.status", id, gin.H{"status": in.Status})
	c.JSON(http.StatusOK, gin.H{"ok": true, "status": in.Status})
}

func (s *Server) AdminSetTenantPlan(c *gin.Context) {
	id := c.Param("id")
	var in struct {
		Plan string `json:"plan" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	ok, err := repository.PlanExists(c.Request.Context(), s.DB.Pool, in.Plan)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "plan check failed"})
		return
	}
	if !ok {
		badRequest(c, "unknown plan")
		return
	}
	if err := repository.UpdateTenantPlan(c.Request.Context(), s.DB.Pool, id, in.Plan); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "update failed"})
		return
	}
	s.adminAudit(c, "tenant.plan", id, gin.H{"plan": in.Plan})
	c.JSON(http.StatusOK, gin.H{"ok": true, "plan": in.Plan})
}

// AdminDeleteTenant drops the firm's schema (irreversible) and its control row.
func (s *Server) AdminDeleteTenant(c *gin.Context) {
	id := c.Param("id")
	t, err := repository.TenantByID(c.Request.Context(), s.DB.Pool, id)
	if err == pgx.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "firm not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "lookup failed"})
		return
	}
	if db.ValidSchemaName(t.SchemaName) {
		if _, err := s.DB.Pool.Exec(c.Request.Context(),
			"DROP SCHEMA IF EXISTS "+pgx.Identifier{t.SchemaName}.Sanitize()+" CASCADE"); err != nil {
			logging.L(c.Request.Context()).Error("delete tenant: drop schema", "err", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "schema drop failed"})
			return
		}
	}
	if err := repository.DeleteTenant(c.Request.Context(), s.DB.Pool, id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete failed"})
		return
	}
	s.adminAudit(c, "tenant.delete", id, gin.H{"slug": t.Slug, "name": t.Name})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// AdminImpersonate mints a normal tenant session for the firm's owner so an
// admin can enter the firm workspace for support. Audited and time-boxed by the
// standard access-token TTL.
func (s *Server) AdminImpersonate(c *gin.Context) {
	t, err := repository.TenantByID(c.Request.Context(), s.DB.Pool, c.Param("id"))
	if err == pgx.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "firm not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "lookup failed"})
		return
	}
	if t.Status != "active" {
		c.JSON(http.StatusConflict, gin.H{"error": "firm is not active"})
		return
	}
	if t.OwnerUserID == nil {
		c.JSON(http.StatusConflict, gin.H{"error": "firm has no owner to impersonate"})
		return
	}
	var resp gin.H
	err = s.DB.WithTenant(c.Request.Context(), t.ID, t.SchemaName, func(tx pgx.Tx) error {
		user, err := repository.UserByID(c.Request.Context(), tx, *t.OwnerUserID)
		if err != nil {
			return err
		}
		roleID := ""
		if user.RoleID != nil {
			roleID = *user.RoleID
		}
		access, err := auth.IssueAccessTokenWithRole(s.Cfg.JWTSecret, user.ID, t.ID, t.Slug, user.Role, roleID, s.Cfg.AccessTTL)
		if err != nil {
			return err
		}
		raw, hash, err := auth.NewRefreshToken()
		if err != nil {
			return err
		}
		if err := repository.StoreRefreshToken(c.Request.Context(), tx, uuid.NewString(), user.ID, hash, time.Now().Add(s.Cfg.RefreshTTL)); err != nil {
			return err
		}
		resp = gin.H{
			"access_token":  access,
			"refresh_token": raw,
			"tenant":        gin.H{"id": t.ID, "slug": t.Slug, "name": t.Name, "plan": t.Plan},
			"user":          gin.H{"id": user.ID, "email": user.Email, "full_name": user.FullName, "role": user.Role},
		}
		return nil
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "impersonation failed"})
		return
	}
	s.adminAudit(c, "tenant.impersonate", t.ID, gin.H{"slug": t.Slug})
	c.JSON(http.StatusOK, resp)
}

// --- plans / stats / audit ---

func (s *Server) AdminListPlans(c *gin.Context) {
	plans, err := repository.ListPlans(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "list failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"plans": plans})
}

func (s *Server) AdminPlatformStats(c *gin.Context) {
	tenants, err := repository.AllTenants(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stats failed"})
		return
	}
	var stats struct {
		Firms        int   `json:"firms"`
		Active       int   `json:"active"`
		Suspended    int   `json:"suspended"`
		Users        int   `json:"users"`
		Files        int   `json:"files"`
		Archives     int   `json:"archives"`
		StorageBytes int64 `json:"storage_bytes"`
	}
	for i := range tenants {
		t := tenants[i]
		stats.Firms++
		switch t.Status {
		case "active":
			stats.Active++
		case "suspended":
			stats.Suspended++
		}
		if m := s.tenantMetrics(c, &t); m != nil {
			stats.Users += m.Users
			stats.Files += m.Files
			stats.Archives += m.Archives
			stats.StorageBytes += m.StorageBytes
		}
	}
	c.JSON(http.StatusOK, gin.H{"stats": stats})
}

func (s *Server) AdminAuditLog(c *gin.Context) {
	tenantID := c.Query("tenant_id")
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "200"))
	var rows []repository.AuditRow
	err := s.DB.WithPlatformAdmin(c.Request.Context(), func(tx pgx.Tx) error {
		r, e := repository.ListAuditLog(c.Request.Context(), tx, tenantID, limit)
		rows = r
		return e
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "audit read failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"entries": rows})
}

// --- platform admins ---

func (s *Server) AdminListAdmins(c *gin.Context) {
	admins, err := repository.ListPlatformAdmins(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "list failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"admins": admins})
}

func (s *Server) AdminCreateAdmin(c *gin.Context) {
	var in struct {
		Email    string `json:"email" binding:"required,email"`
		FullName string `json:"full_name"`
		Password string `json:"password" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if len(in.Password) < 8 {
		badRequest(c, "password must be at least 8 characters")
		return
	}
	hash, err := auth.HashPassword(in.Password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	admin := &repository.PlatformAdmin{ID: uuid.NewString(), Email: in.Email, FullName: in.FullName, PasswordHash: hash}
	if err := repository.InsertPlatformAdmin(c.Request.Context(), s.DB.Pool, admin); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "could not create admin (email already in use?)"})
		return
	}
	s.adminAudit(c, "admin.create", "", gin.H{"email": in.Email})
	c.JSON(http.StatusCreated, gin.H{"admin": gin.H{"id": admin.ID, "email": admin.Email, "full_name": admin.FullName}})
}

func (s *Server) AdminDeleteAdmin(c *gin.Context) {
	id := c.Param("id")
	if cl := middleware.AdminFrom(c); cl != nil && cl.AdminID == id {
		badRequest(c, "you cannot remove your own admin account")
		return
	}
	n, err := repository.CountPlatformAdmins(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete failed"})
		return
	}
	if n <= 1 {
		badRequest(c, "cannot remove the last platform admin")
		return
	}
	if err := repository.DeletePlatformAdmin(c.Request.Context(), s.DB.Pool, id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete failed"})
		return
	}
	s.adminAudit(c, "admin.delete", "", gin.H{"admin_id": id})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
