package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/repository"
)

func (s *Server) ListUsers(c *gin.Context) {
	var users []repository.User
	if s.withTenant(c, func(tx pgx.Tx) error {
		u, err := repository.ListUsers(c.Request.Context(), tx)
		users = u
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"users": users})
	}
}

// CreateUser adds a firm member (assigned a role_id) or a portal (client)
// account (no role — client_id only). Gated by users.invite.
func (s *Server) CreateUser(c *gin.Context) {
	var in struct {
		Email    string  `json:"email" binding:"required,email"`
		FullName string  `json:"full_name" binding:"required"`
		RoleID   string  `json:"role_id"` // required for firm members
		Password string  `json:"password" binding:"required,min=8"`
		ClientID *string `json:"client_id"` // set => portal (client) account, no role
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.ClientID == nil && in.RoleID == "" {
		badRequest(c, "role_id is required for firm members (or set client_id for a portal account)")
		return
	}
	hash, err := auth.HashPassword(in.Password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	u := &repository.User{
		ID: uuid.NewString(), Email: strings.ToLower(in.Email), FullName: in.FullName,
		Status: "active", ClientID: in.ClientID, PasswordHash: hash,
	}
	if in.ClientID != nil {
		u.Role = "client" // portal account: no firm role
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		if in.RoleID != "" {
			role, err := repository.GetRole(c.Request.Context(), tx, in.RoleID)
			if err == pgx.ErrNoRows {
				c.JSON(http.StatusBadRequest, gin.H{"error": "unknown role_id"})
				return errHandled
			}
			if err != nil {
				return err
			}
			u.Role = role.Name
			u.RoleID = &role.ID
		}
		return repository.InsertUser(c.Request.Context(), tx, u)
	}) {
		c.JSON(http.StatusCreated, gin.H{"user": u})
	}
}

// UpdateUser changes a member's status (active/disabled). Gated by users.remove.
func (s *Server) UpdateUser(c *gin.Context) {
	var in struct {
		Status string `json:"status" binding:"required,oneof=active disabled"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.UpdateUserStatus(c.Request.Context(), tx, c.Param("id"), in.Status)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// ChangeUserRole reassigns a user's single role (replaces it entirely). Gated
// by users.manage_roles. The firm owner's role cannot be changed away from Owner.
func (s *Server) ChangeUserRole(c *gin.Context) {
	var in struct {
		RoleID string `json:"role_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	targetID := c.Param("id")
	if owner := s.tenant(c).OwnerUserID; owner != nil && *owner == targetID {
		// Guard against locking the firm out of its Owner.
		var isOwnerRole bool
		if !s.withTenant(c, func(tx pgx.Tx) error {
			role, err := repository.GetRole(c.Request.Context(), tx, in.RoleID)
			if err == nil {
				isOwnerRole = role.IsProtected
			} else if err != pgx.ErrNoRows {
				return err
			}
			return nil
		}) {
			return
		}
		if !isOwnerRole {
			c.JSON(http.StatusForbidden, gin.H{"error": "the firm owner must keep the Owner role"})
			return
		}
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		role, err := repository.GetRole(c.Request.Context(), tx, in.RoleID)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusBadRequest, gin.H{"error": "unknown role_id"})
			return errHandled
		}
		if err != nil {
			return err
		}
		return repository.UpdateUserRole(c.Request.Context(), tx, targetID, role.ID, role.Name)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// --- Client portal (role=client): strictly scoped to the caller's own
// client record via users.client_id. ---

func (s *Server) portalClientID(c *gin.Context, tx pgx.Tx) (string, error) {
	u, err := repository.UserByID(c.Request.Context(), tx, s.claims(c).UserID())
	if err != nil {
		return "", err
	}
	if u.ClientID == nil {
		c.JSON(http.StatusForbidden, gin.H{"error": "portal account is not linked to a client record"})
		return "", errHandled
	}
	return *u.ClientID, nil
}

func (s *Server) PortalFiles(c *gin.Context) {
	var files []repository.File
	if s.withTenant(c, func(tx pgx.Tx) error {
		clientID, err := s.portalClientID(c, tx)
		if err != nil {
			return err
		}
		files, err = repository.ListFiles(c.Request.Context(), tx, "", "", clientID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"files": files})
	}
}

func (s *Server) PortalInvoices(c *gin.Context) {
	var invoices []repository.Invoice
	if s.withTenant(c, func(tx pgx.Tx) error {
		clientID, err := s.portalClientID(c, tx)
		if err != nil {
			return err
		}
		invoices, err = repository.ListInvoices(c.Request.Context(), tx, clientID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"invoices": invoices})
	}
}

func (s *Server) PortalMessages(c *gin.Context) {
	var msgs []repository.Message
	if s.withTenant(c, func(tx pgx.Tx) error {
		clientID, err := s.portalClientID(c, tx)
		if err != nil {
			return err
		}
		msgs, err = repository.ListMessages(c.Request.Context(), tx, clientID, "")
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"messages": msgs})
	}
}
