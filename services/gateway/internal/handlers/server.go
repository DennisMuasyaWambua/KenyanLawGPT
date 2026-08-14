package handlers

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/integrations/africastalking"
	"github.com/wakiliai/gateway/internal/integrations/email"
	"github.com/wakiliai/gateway/internal/integrations/judiciary"
	"github.com/wakiliai/gateway/internal/integrations/mpesa"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/storage"
)

type Server struct {
	DB        *db.DB
	Cfg       *config.Config
	RDB       *redis.Client
	AI        *grpcclient.AIClient
	Store     *storage.ObjectStore
	SMS       *africastalking.Client
	Mail      email.Provider
	Daraja    *mpesa.Daraja
	Judiciary judiciary.Adapter
}

// withTenant runs fn inside the authenticated tenant's schema transaction and
// converts errors into HTTP responses. Returns false when it already wrote an
// error response.
func (s *Server) withTenant(c *gin.Context, fn func(tx pgx.Tx) error) bool {
	tenant := middleware.TenantFrom(c)
	if tenant == nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "tenant not resolved"})
		return false
	}
	err := s.DB.WithTenant(c.Request.Context(), tenant.ID, tenant.SchemaName, fn)
	if err == nil {
		return true
	}
	if errors.Is(err, errHandled) {
		return false // handler already wrote the response
	}
	if errors.Is(err, pgx.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return false
	}
	logging.L(c.Request.Context()).Error("tenant tx failed", "err", err, "path", c.FullPath())
	c.JSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
	return false
}

func (s *Server) tenant(c *gin.Context) *repository.Tenant { return middleware.TenantFrom(c) }
func (s *Server) claims(c *gin.Context) *middlewareClaims  { return &middlewareClaims{c} }

// middlewareClaims is a tiny accessor wrapper to keep handlers terse.
type middlewareClaims struct{ c *gin.Context }

func (m *middlewareClaims) UserID() string {
	if cl := middleware.ClaimsFrom(m.c); cl != nil {
		return cl.UserID
	}
	return ""
}

func (m *middlewareClaims) Role() string {
	if cl := middleware.ClaimsFrom(m.c); cl != nil {
		return cl.Role
	}
	return ""
}

func (m *middlewareClaims) RoleID() string {
	if cl := middleware.ClaimsFrom(m.c); cl != nil {
		return cl.RoleID
	}
	return ""
}

// can reports whether the caller's role grants perm (firm-scoped RBAC). Used
// for conditional in-handler checks; route-level gating uses
// middleware.RequirePermission.
func (s *Server) can(c *gin.Context, perm string) bool {
	return middleware.HasPermission(c, s.DB, perm)
}

func badRequest(c *gin.Context, msg string) {
	c.JSON(http.StatusBadRequest, gin.H{"error": msg})
}
