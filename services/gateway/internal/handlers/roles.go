package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

// ListPermissions returns the fixed permission catalog for the management UI.
func (s *Server) ListPermissions(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"permissions": rbac.Catalog})
}

// ListRoleTemplates returns the suggested default roles for onboarding. These
// are pre-fills only — nothing is persisted until the owner creates a role.
func (s *Server) ListRoleTemplates(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"templates": rbac.DefaultTemplates})
}

// ListRoles returns the firm's roles with permissions and member counts.
func (s *Server) ListRoles(c *gin.Context) {
	var roles []repository.Role
	if s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.ListRoles(c.Request.Context(), tx)
		roles = r
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"roles": roles})
	}
}

// validatePermissions rejects any key not in the catalog and de-duplicates.
func validatePermissions(in []string) ([]string, string) {
	seen := map[string]bool{}
	out := make([]string, 0, len(in))
	for _, p := range in {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if !rbac.ValidPermission(p) {
			return nil, "unknown permission: " + p
		}
		if !seen[p] {
			seen[p] = true
			out = append(out, p)
		}
	}
	return out, ""
}

func (s *Server) CreateRole(c *gin.Context) {
	var in struct {
		Name        string   `json:"name" binding:"required"`
		Description string   `json:"description"`
		Permissions []string `json:"permissions"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	name := strings.TrimSpace(in.Name)
	if name == "" {
		badRequest(c, "name is required")
		return
	}
	perms, perr := validatePermissions(in.Permissions)
	if perr != "" {
		badRequest(c, perr)
		return
	}
	role := &repository.Role{ID: uuid.NewString(), Name: name, Description: in.Description, IsProtected: false}
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		if _, err := repository.RoleByName(c.Request.Context(), tx, name); err == nil {
			c.JSON(http.StatusConflict, gin.H{"error": "a role with this name already exists"})
			return errHandled
		} else if err != pgx.ErrNoRows {
			return err
		}
		return repository.CreateRole(c.Request.Context(), tx, role, perms)
	})
	if ok {
		role.Permissions = perms
		c.JSON(http.StatusCreated, gin.H{"role": role})
	}
}

func (s *Server) UpdateRole(c *gin.Context) {
	var in struct {
		Name        string   `json:"name" binding:"required"`
		Description string   `json:"description"`
		Permissions []string `json:"permissions"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	name := strings.TrimSpace(in.Name)
	if name == "" {
		badRequest(c, "name is required")
		return
	}
	perms, perr := validatePermissions(in.Permissions)
	if perr != "" {
		badRequest(c, perr)
		return
	}
	id := c.Param("id")
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		role, err := repository.GetRole(c.Request.Context(), tx, id)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "role not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if role.IsProtected {
			c.JSON(http.StatusForbidden, gin.H{"error": "the Owner role is protected and cannot be edited"})
			return errHandled
		}
		// Guard the unique-name constraint with a friendly message.
		if other, err := repository.RoleByName(c.Request.Context(), tx, name); err == nil && other.ID != id {
			c.JSON(http.StatusConflict, gin.H{"error": "a role with this name already exists"})
			return errHandled
		} else if err != nil && err != pgx.ErrNoRows {
			return err
		}
		if err := repository.UpdateRoleMeta(c.Request.Context(), tx, id, name, in.Description); err != nil {
			return err
		}
		return repository.SetRolePermissions(c.Request.Context(), tx, id, perms)
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

func (s *Server) DeleteRole(c *gin.Context) {
	id := c.Param("id")
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		role, err := repository.GetRole(c.Request.Context(), tx, id)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "role not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if role.IsProtected {
			c.JSON(http.StatusForbidden, gin.H{"error": "the Owner role is protected and cannot be deleted"})
			return errHandled
		}
		n, err := repository.RoleMemberCount(c.Request.Context(), tx, id)
		if err != nil {
			return err
		}
		if n > 0 {
			c.JSON(http.StatusConflict, gin.H{"error": "reassign this role's members before deleting it"})
			return errHandled
		}
		return repository.DeleteRole(c.Request.Context(), tx, id)
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}
