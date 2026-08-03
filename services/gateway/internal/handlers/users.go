package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/rbac"
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

// CreateUser adds a firm member or a portal (client) account. Only owners may
// mint other owners; partners may create everyone else.
func (s *Server) CreateUser(c *gin.Context) {
	var in struct {
		Email    string  `json:"email" binding:"required,email"`
		FullName string  `json:"full_name" binding:"required"`
		Role     string  `json:"role" binding:"required"`
		Password string  `json:"password" binding:"required,min=8"`
		ClientID *string `json:"client_id"` // required when role=client
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if !rbac.Valid(in.Role) {
		badRequest(c, "invalid role")
		return
	}
	caller := s.claims(c).Role()
	if in.Role == rbac.RoleOwner && caller != rbac.RoleOwner {
		c.JSON(http.StatusForbidden, gin.H{"error": "only an owner can create owners"})
		return
	}
	if in.Role == rbac.RoleClient && in.ClientID == nil {
		badRequest(c, "client role requires client_id")
		return
	}
	hash, err := auth.HashPassword(in.Password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	u := &repository.User{
		ID: uuid.NewString(), Email: strings.ToLower(in.Email), FullName: in.FullName,
		Role: in.Role, Status: "active", ClientID: in.ClientID, PasswordHash: hash,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertUser(c.Request.Context(), tx, u)
	}) {
		c.JSON(http.StatusCreated, gin.H{"user": u})
	}
}

func (s *Server) UpdateUser(c *gin.Context) {
	var in struct {
		Role   string `json:"role" binding:"required"`
		Status string `json:"status" binding:"required,oneof=active disabled"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if !rbac.Valid(in.Role) {
		badRequest(c, "invalid role")
		return
	}
	if in.Role == rbac.RoleOwner && s.claims(c).Role() != rbac.RoleOwner {
		c.JSON(http.StatusForbidden, gin.H{"error": "only an owner can grant owner"})
		return
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.UpdateUser(c.Request.Context(), tx, c.Param("id"), in.Role, in.Status)
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

func (s *Server) PortalMatters(c *gin.Context) {
	var matters []repository.Matter
	if s.withTenant(c, func(tx pgx.Tx) error {
		clientID, err := s.portalClientID(c, tx)
		if err != nil {
			return err
		}
		matters, err = repository.ListMatters(c.Request.Context(), tx, "", "", clientID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"matters": matters})
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
