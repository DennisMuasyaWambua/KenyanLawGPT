package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
)

// UpdateFirm edits the firm's own profile (name, LSK registration number,
// phone). Gated by firm_settings.edit. The workspace address (slug) is fixed:
// it is how members sign in.
func (s *Server) UpdateFirm(c *gin.Context) {
	var in struct {
		Name      string `json:"name" binding:"required"`
		RegNumber string `json:"reg_number"`
		Phone     string `json:"phone"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	tenant := s.tenant(c)
	name := strings.TrimSpace(in.Name)
	if name == "" {
		badRequest(c, "firm name is required")
		return
	}
	ctx := c.Request.Context()
	if !strings.EqualFold(name, tenant.Name) {
		if exists, err := repository.TenantNameExists(ctx, s.DB.Pool, name); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
			return
		} else if exists {
			c.JSON(http.StatusConflict, gin.H{"error": "another firm is already registered under this name"})
			return
		}
	}
	if err := repository.UpdateTenantProfile(ctx, s.DB.Pool, tenant.ID, name,
		strings.TrimSpace(in.RegNumber), strings.TrimSpace(in.Phone)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
		return
	}
	middleware.InvalidateTenant(tenant.Slug)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// CompleteOnboarding marks the post-signup wizard finished (or skipped) so it
// stops opening on sign-in. Gated by firm_settings.edit.
func (s *Server) CompleteOnboarding(c *gin.Context) {
	tenant := s.tenant(c)
	if err := repository.CompleteTenantOnboarding(c.Request.Context(), s.DB.Pool, tenant.ID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
		return
	}
	middleware.InvalidateTenant(tenant.Slug)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// FirmInfo returns the public face of a firm — its name — for the sign-in page,
// which only knows the firm ID the visitor typed (public, tenant-scoped, like
// the invite lookup). Unknown IDs 404 in the tenant middleware.
func (s *Server) FirmInfo(c *gin.Context) {
	t := s.tenant(c)
	c.JSON(http.StatusOK, gin.H{"firm": gin.H{"name": t.Name, "slug": t.Slug}})
}
