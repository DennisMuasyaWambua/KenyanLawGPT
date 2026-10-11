package handlers

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/integrations/email"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/repository"
)

// tempPasswordTTL is how long an emailed temporary password stays usable.
const tempPasswordTTL = 7 * 24 * time.Hour

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
// account (no role — client_id only). Gated by users.invite. Without a password
// the system generates a temporary one, emails it with sign-in instructions,
// and the user must replace it at first sign-in.
func (s *Server) CreateUser(c *gin.Context) {
	var in struct {
		Email    string  `json:"email" binding:"required,email"`
		FullName string  `json:"full_name" binding:"required"`
		Phone    string  `json:"phone"`
		RoleID   string  `json:"role_id"`   // required for firm members
		Password string  `json:"password"`  // optional: empty => emailed temporary password
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
	if in.Password != "" && len(in.Password) < 8 {
		badRequest(c, "password must be at least 8 characters (or leave it empty to email a temporary one)")
		return
	}
	temporary := in.Password == ""
	password := in.Password
	if temporary {
		var err error
		if password, err = auth.NewTemporaryPassword(); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "password generation failed"})
			return
		}
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	u := &repository.User{
		ID: uuid.NewString(), Email: strings.ToLower(strings.TrimSpace(in.Email)), FullName: strings.TrimSpace(in.FullName),
		Phone: strings.TrimSpace(in.Phone), Status: "active", ClientID: in.ClientID, PasswordHash: hash,
	}
	if temporary {
		exp := time.Now().Add(tempPasswordTTL)
		u.MustChangePassword, u.TempPasswordExpiresAt = true, &exp
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
		if _, err := repository.UserByEmail(c.Request.Context(), tx, u.Email); err == nil {
			c.JSON(http.StatusConflict, gin.H{"error": "someone with this email is already a member of your firm"})
			return errHandled
		} else if err != pgx.ErrNoRows {
			return err
		}
		return repository.InsertUser(c.Request.Context(), tx, u)
	}) {
		resp := gin.H{"user": u}
		if temporary {
			for k, v := range s.deliverTemporaryPassword(c, u, password) {
				resp[k] = v
			}
		}
		c.JSON(http.StatusCreated, resp)
	}
}

// ResendLogin issues a fresh temporary password (e.g. the first expired or the
// email went astray) and emails it. Gated by users.invite. Only the firm owner
// can reset the owner's account, and nobody resets their own here.
func (s *Server) ResendLogin(c *gin.Context) {
	targetID := c.Param("id")
	callerID := s.claims(c).UserID()
	if targetID == callerID {
		badRequest(c, "use “Change password” to change your own password")
		return
	}
	if owner := s.tenant(c).OwnerUserID; owner != nil && *owner == targetID {
		c.JSON(http.StatusForbidden, gin.H{"error": "the firm owner's login can't be reset by another member"})
		return
	}
	password, err := auth.NewTemporaryPassword()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "password generation failed"})
		return
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	var u *repository.User
	if !s.withTenant(c, func(tx pgx.Tx) error {
		got, err := repository.UserByID(c.Request.Context(), tx, targetID)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "member not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if got.Status != "active" {
			c.JSON(http.StatusConflict, gin.H{"error": "reactivate this member before resending their login"})
			return errHandled
		}
		u = got
		if err := repository.SetTemporaryPassword(c.Request.Context(), tx, u.ID, hash, time.Now().Add(tempPasswordTTL)); err != nil {
			return err
		}
		// Any session opened with the old password ends now.
		return repository.RevokeUserRefreshTokens(c.Request.Context(), tx, u.ID)
	}) {
		return
	}
	resp := gin.H{"ok": true}
	for k, v := range s.deliverTemporaryPassword(c, u, password) {
		resp[k] = v
	}
	c.JSON(http.StatusOK, resp)
}

// deliverTemporaryPassword emails sign-in instructions with the temporary
// password. When mail isn't configured (dev) or sending fails, the password is
// returned to the admin to pass on in person — the account is unusable otherwise,
// and it must be changed at first sign-in either way.
func (s *Server) deliverTemporaryPassword(c *gin.Context, u *repository.User, password string) gin.H {
	tenant := s.tenant(c)
	loginURL := fmt.Sprintf("%s/login?firm=%s", strings.TrimRight(s.Cfg.AppBaseURL, "/"), tenant.Slug)
	role := u.Role
	if role == "client" {
		role = "client portal user"
	}
	body := fmt.Sprintf(
		"Hello %s,\n\n%s has set up your account on Advocatus as %s.\n\n"+
			"Sign in: %s\nFirm ID: %s\nEmail: %s\nTemporary password: %s\n\n"+
			"You'll be asked to choose your own password when you first sign in. "+
			"This temporary password expires in 7 days.\n",
		u.FullName, tenant.Name, role, loginURL, tenant.Slug, u.Email, password)
	if !email.Delivers(s.Mail) {
		return gin.H{"credentials_emailed": false, "temp_password": password,
			"email_error": "email is not configured on this server"}
	}
	if err := s.Mail.Send(c.Request.Context(), u.Email, "Your sign-in details for "+tenant.Name, body); err != nil {
		logging.L(c.Request.Context()).Warn("temporary password email failed", "user", u.ID, "err", err)
		return gin.H{"credentials_emailed": false, "temp_password": password, "email_error": err.Error()}
	}
	return gin.H{"credentials_emailed": true}
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
