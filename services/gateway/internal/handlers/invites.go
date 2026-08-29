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
	"github.com/wakiliai/gateway/internal/integrations/google"
	"github.com/wakiliai/gateway/internal/repository"
)

const inviteTTL = 72 * time.Hour

// InviteUser creates a staff invite pre-assigned to exactly one role and emails
// an accept link. Gated by users.invite. Unlike CreateUser, the owner sets no
// password — the invitee sets their own (or links Google) when accepting.
func (s *Server) InviteUser(c *gin.Context) {
	var in struct {
		Email    string `json:"email" binding:"required,email"`
		FullName string `json:"full_name"`
		RoleID   string `json:"role_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	rawToken, tokenHash, err := auth.NewRefreshToken() // opaque token; only the hash is stored
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "token generation failed"})
		return
	}
	invitedBy := s.claims(c).UserID()
	inv := &repository.StaffInvite{
		ID: uuid.NewString(), Email: strings.ToLower(in.Email), FullName: in.FullName,
		InvitedBy: &invitedBy, ExpiresAt: time.Now().Add(inviteTTL),
	}
	if !s.withTenant(c, func(tx pgx.Tx) error {
		role, err := repository.GetRole(c.Request.Context(), tx, in.RoleID)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusBadRequest, gin.H{"error": "unknown role_id"})
			return errHandled
		}
		if err != nil {
			return err
		}
		inv.Role = role.Name
		inv.RoleID = &role.ID
		return repository.CreateInvite(c.Request.Context(), tx, inv, tokenHash)
	}) {
		return
	}
	tenant := s.tenant(c)
	acceptURL := fmt.Sprintf("%s/invite/%s?firm=%s", strings.TrimRight(s.Cfg.AppBaseURL, "/"), rawToken, tenant.Slug)
	body := fmt.Sprintf(
		"You've been invited to join %s on C. Karwitha & Co. Advocates as %s.\n\nAccept your invite and set up your account:\n%s\n\nThis link expires in 72 hours.",
		tenant.Name, inv.Role, acceptURL)
	if err := s.Mail.Send(c.Request.Context(), inv.Email, "You're invited to C. Karwitha & Co. Advocates", body); err != nil {
		// The invite is persisted; surface the link so onboarding isn't blocked by email.
		c.JSON(http.StatusCreated, gin.H{"invite": inv, "accept_url": acceptURL, "email_error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"invite": inv, "accept_url": acceptURL})
}

// GetInvite returns invite details for the accept page (public, tenant-scoped).
func (s *Server) GetInvite(c *gin.Context) {
	var inv *repository.StaffInvite
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		got, err := repository.InviteByTokenHash(c.Request.Context(), tx, auth.HashRefreshToken(c.Param("token")))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "invite invalid or expired"})
			return errHandled
		}
		inv = got
		return err
	})
	if ok && inv != nil {
		c.JSON(http.StatusOK, gin.H{"invite": gin.H{
			"email": inv.Email, "full_name": inv.FullName, "role": inv.Role,
		}, "firm": gin.H{"name": s.tenant(c).Name, "slug": s.tenant(c).Slug}})
	}
}

// AcceptInvite consumes an invite, creates the user (password or Google), and
// logs them in (public, tenant-scoped).
func (s *Server) AcceptInvite(c *gin.Context) {
	var in struct {
		FullName   string `json:"full_name"`
		Password   string `json:"password"`
		Credential string `json:"credential"` // Google id token (alternative to password)
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	// Verify Google (network call) before opening the DB transaction.
	var ident *google.Identity
	if in.Credential != "" {
		id, err := google.Verify(c.Request.Context(), in.Credential, s.Cfg.GoogleClientID)
		if err != nil || !id.EmailVerified {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid Google credential"})
			return
		}
		ident = id
	} else if len(in.Password) < 8 {
		badRequest(c, "password must be at least 8 characters (or sign up with Google)")
		return
	}

	tokenHash := auth.HashRefreshToken(c.Param("token"))
	var resp gin.H
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		inv, err := repository.InviteByTokenHash(c.Request.Context(), tx, tokenHash)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invite invalid or expired"})
			return errHandled
		}
		if err != nil {
			return err
		}
		fullName := in.FullName
		if fullName == "" {
			fullName = inv.FullName
		}
		u := &repository.User{
			ID: uuid.NewString(), Email: inv.Email, FullName: fullName,
			Role: inv.Role, RoleID: inv.RoleID, Status: "active", AuthProvider: "password",
		}
		if ident != nil {
			sub := ident.Sub
			u.GoogleSub = &sub
			u.AuthProvider = "google"
			if fullName == "" {
				u.FullName = ident.Name
			}
		} else {
			hash, err := auth.HashPassword(in.Password)
			if err != nil {
				return err
			}
			u.PasswordHash = hash
		}
		if err := repository.InsertUser(c.Request.Context(), tx, u); err != nil {
			c.JSON(http.StatusConflict, gin.H{"error": "an account with this email already exists"})
			return errHandled
		}
		if err := repository.MarkInviteAccepted(c.Request.Context(), tx, tokenHash); err != nil {
			return err
		}
		resp, err = s.issueTokens(c, tx, u)
		return err
	})
	if ok && resp != nil {
		c.JSON(http.StatusCreated, resp)
	}
}
