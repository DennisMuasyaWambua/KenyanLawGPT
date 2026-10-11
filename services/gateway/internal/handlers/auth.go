package handlers

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/integrations/google"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/services"
)

// firmSignup is what a law firm owner fills in on the public signup page.
type firmSignup struct {
	FirmName        string `json:"firm_name" binding:"required"`
	Slug            string `json:"slug"` // workspace address; derived from the firm name when empty
	RegNumber       string `json:"reg_number"`
	Phone           string `json:"phone"`
	DataResidencyKE *bool  `json:"data_residency_ke"`
}

func (f *firmSignup) provisionInput() *services.ProvisionInput {
	slug := strings.ToLower(strings.TrimSpace(f.Slug))
	if slug == "" {
		slug = services.SlugFromName(f.FirmName)
	}
	residency := true
	if f.DataResidencyKE != nil {
		residency = *f.DataResidencyKE
	}
	// Plan is never taken from the public request: every self-signup starts on
	// the starter plan; upgrades go through the platform admin.
	return &services.ProvisionInput{
		FirmName: strings.TrimSpace(f.FirmName), Slug: slug, Plan: "starter",
		RegNumber: strings.TrimSpace(f.RegNumber), Phone: f.Phone, DataResidencyKE: residency,
	}
}

// Signup lets a law firm owner create their firm's workspace: it provisions the
// tenant (schema, default designation roles, owner as Managing Partner), emails
// the owner their sign-in details, and signs them straight in so the onboarding
// wizard can take over. Runs outside tenant context.
func (s *Server) Signup(c *gin.Context) {
	if !s.Cfg.PublicSignupEnabled {
		c.JSON(http.StatusForbidden, gin.H{"error": "self-service sign-up is closed — contact us to set up your firm"})
		return
	}
	var in struct {
		firmSignup
		OwnerName     string `json:"owner_name" binding:"required"`
		OwnerEmail    string `json:"owner_email" binding:"required,email"`
		OwnerPassword string `json:"owner_password" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	prov := in.provisionInput()
	prov.OwnerName, prov.OwnerEmail, prov.OwnerPassword = strings.TrimSpace(in.OwnerName), in.OwnerEmail, in.OwnerPassword
	s.provisionAndSignIn(c, prov)
}

func (s *Server) provisionAndSignIn(c *gin.Context, prov *services.ProvisionInput) {
	tenant, owner, err := services.ProvisionTenant(c.Request.Context(), s.DB, s.Cfg, prov)
	var verr *services.ValidationError
	if errors.As(err, &verr) {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": verr.Msg})
		return
	}
	if err != nil {
		logging.L(c.Request.Context()).Error("firm signup failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "could not create your firm — please try again"})
		return
	}
	s.sendWelcome(c, tenant, owner)
	// issueTokens resolves the tenant from the request context, which public
	// routes don't have; the freshly provisioned firm is the right one.
	c.Set(middleware.CtxTenant, tenant)
	var resp gin.H
	if err := s.DB.WithTenant(c.Request.Context(), tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
		var err error
		resp, err = s.issueTokens(c, tx, owner)
		return err
	}); err != nil {
		// The firm exists; the owner can still sign in normally.
		logging.L(c.Request.Context()).Error("signup token issue failed", "err", err)
		c.JSON(http.StatusCreated, gin.H{"tenant": gin.H{"slug": tenant.Slug, "name": tenant.Name}})
		return
	}
	c.JSON(http.StatusCreated, resp)
}

// sendWelcome emails the owner their workspace address — they need it (or
// the slug) to sign in again later. Best effort.
func (s *Server) sendWelcome(c *gin.Context, tenant *repository.Tenant, owner *repository.User) {
	loginURL := fmt.Sprintf("%s/login?firm=%s", strings.TrimRight(s.Cfg.AppBaseURL, "/"), tenant.Slug)
	body := fmt.Sprintf(
		"Welcome to Advocatus, %s.\n\nYour firm workspace for %s is ready.\n\n"+
			"Firm ID: %s\nSign in: %s\nEmail: %s\n\n"+
			"Next steps: review your firm's roles and permissions, then add your team — "+
			"each member is emailed a temporary password to sign in with.\n",
		owner.FullName, tenant.Name, tenant.Slug, loginURL, owner.Email)
	if err := s.Mail.Send(c.Request.Context(), owner.Email, "Your Advocatus workspace for "+tenant.Name, body); err != nil {
		logging.L(c.Request.Context()).Warn("welcome email failed", "tenant", tenant.Slug, "err", err)
	}
}

type loginInput struct {
	Email    string `json:"email" binding:"required"`
	Password string `json:"password" binding:"required"`
}

func (s *Server) setAuthCookies(c *gin.Context, access, refresh string) {
	secure := s.Cfg.Env == "prod"
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie("wakili_at", access, int(s.Cfg.AccessTTL.Seconds()), "/", "", secure, true)
	c.SetCookie("wakili_rt", refresh, int(s.Cfg.RefreshTTL.Seconds()), "/api/v1/auth", "", secure, true)
}

func (s *Server) issueTokens(c *gin.Context, tx pgx.Tx, user *repository.User) (gin.H, error) {
	tenant := s.tenant(c)
	roleID := ""
	if user.RoleID != nil {
		roleID = *user.RoleID
	}
	access, err := auth.IssueUserAccessToken(s.Cfg.JWTSecret, user.ID, tenant.ID, tenant.Slug, user.Role, roleID,
		user.MustChangePassword, s.Cfg.AccessTTL)
	if err != nil {
		return nil, err
	}
	rawRefresh, hash, err := auth.NewRefreshToken()
	if err != nil {
		return nil, err
	}
	if err := repository.StoreRefreshToken(c.Request.Context(), tx, uuid.NewString(), user.ID, hash,
		time.Now().Add(s.Cfg.RefreshTTL)); err != nil {
		return nil, err
	}
	s.setAuthCookies(c, access, rawRefresh)
	return gin.H{
		"access_token":  access,
		"refresh_token": rawRefresh,
		"user": gin.H{
			"id": user.ID, "email": user.Email, "full_name": user.FullName,
			"role": user.Role, "client_id": user.ClientID,
			"must_change_password": user.MustChangePassword,
		},
		"tenant": gin.H{"id": tenant.ID, "slug": tenant.Slug, "name": tenant.Name, "plan": tenant.Plan},
	}, nil
}

func (s *Server) Login(c *gin.Context) {
	var in loginInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	var resp gin.H
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		user, err := repository.UserByEmail(c.Request.Context(), tx, in.Email)
		if err == pgx.ErrNoRows || (err == nil && !auth.CheckPassword(user.PasswordHash, in.Password)) {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid email or password"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if user.Status != "active" {
			c.JSON(http.StatusForbidden, gin.H{"error": "account disabled"})
			return errHandled
		}
		if user.MustChangePassword && user.TempPasswordExpiresAt != nil && time.Now().After(*user.TempPasswordExpiresAt) {
			c.JSON(http.StatusForbidden, gin.H{"error": "your temporary password has expired — ask your firm administrator to resend your login"})
			return errHandled
		}
		if err := repository.TouchLastLogin(c.Request.Context(), tx, user.ID); err != nil {
			return err
		}
		resp, err = s.issueTokens(c, tx, user)
		return err
	})
	if ok && resp != nil {
		c.JSON(http.StatusOK, resp)
	}
}

// ChangePassword replaces the caller's password. It is the one action open to
// a temporary-password session; the reissued tokens no longer carry the flag.
func (s *Server) ChangePassword(c *gin.Context) {
	var in struct {
		CurrentPassword string `json:"current_password" binding:"required"`
		NewPassword     string `json:"new_password" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if len(in.NewPassword) < 8 {
		badRequest(c, "your new password must be at least 8 characters")
		return
	}
	if in.NewPassword == in.CurrentPassword {
		badRequest(c, "choose a password different from your current one")
		return
	}
	hash, err := auth.HashPassword(in.NewPassword)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}
	var resp gin.H
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		user, err := repository.UserByID(c.Request.Context(), tx, s.claims(c).UserID())
		if err != nil {
			return err
		}
		if !auth.CheckPassword(user.PasswordHash, in.CurrentPassword) {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "your current password is incorrect"})
			return errHandled
		}
		if err := repository.SetPassword(c.Request.Context(), tx, user.ID, hash); err != nil {
			return err
		}
		// Sign out other sessions (e.g. someone else who saw the emailed password).
		if err := repository.RevokeUserRefreshTokens(c.Request.Context(), tx, user.ID); err != nil {
			return err
		}
		user.MustChangePassword, user.TempPasswordExpiresAt = false, nil
		resp, err = s.issueTokens(c, tx, user)
		return err
	})
	if ok && resp != nil {
		c.JSON(http.StatusOK, resp)
	}
}

// GoogleLogin authenticates an existing firm member with a Google ID token.
// Tenant-scoped (X-Tenant-Slug): the Google identity is matched to a user in
// this firm by google_sub, or by verified email on first use (then linked).
func (s *Server) GoogleLogin(c *gin.Context) {
	var in struct {
		Credential string `json:"credential" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	ident, err := google.Verify(c.Request.Context(), in.Credential, s.Cfg.GoogleClientID)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid Google credential"})
		return
	}
	if !ident.EmailVerified {
		c.JSON(http.StatusForbidden, gin.H{"error": "Google email is not verified"})
		return
	}
	var resp gin.H
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		user, err := repository.UserByGoogleSub(c.Request.Context(), tx, ident.Sub)
		if err == pgx.ErrNoRows {
			// First Google sign-in: match a pre-existing account by email and link it.
			user, err = repository.UserByEmail(c.Request.Context(), tx, ident.Email)
			if err == pgx.ErrNoRows {
				c.JSON(http.StatusUnauthorized, gin.H{"error": "no account for this Google user in this firm — ask an admin to invite you"})
				return errHandled
			}
			if err != nil {
				return err
			}
			if err := repository.LinkGoogleSub(c.Request.Context(), tx, user.ID, ident.Sub); err != nil {
				return err
			}
		} else if err != nil {
			return err
		}
		if user.Status != "active" {
			c.JSON(http.StatusForbidden, gin.H{"error": "account disabled"})
			return errHandled
		}
		if user.MustChangePassword {
			// Google proved who they are, so the emailed temporary password has
			// no further use — retire it rather than leave it valid in an inbox.
			if err := repository.DropTemporaryPassword(c.Request.Context(), tx, user.ID); err != nil {
				return err
			}
			user.MustChangePassword, user.TempPasswordExpiresAt, user.PasswordHash = false, nil, ""
		}
		if err := repository.TouchLastLogin(c.Request.Context(), tx, user.ID); err != nil {
			return err
		}
		resp, err = s.issueTokens(c, tx, user)
		return err
	})
	if ok && resp != nil {
		c.JSON(http.StatusOK, resp)
	}
}

// GoogleSignup is Signup for an owner who authenticates with Google (no
// password). The firm details are still required.
func (s *Server) GoogleSignup(c *gin.Context) {
	if !s.Cfg.PublicSignupEnabled {
		c.JSON(http.StatusForbidden, gin.H{"error": "self-service sign-up is closed — contact us to set up your firm"})
		return
	}
	var in struct {
		firmSignup
		Credential string `json:"credential" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	ident, err := google.Verify(c.Request.Context(), in.Credential, s.Cfg.GoogleClientID)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid Google credential"})
		return
	}
	if !ident.EmailVerified {
		c.JSON(http.StatusForbidden, gin.H{"error": "Google email is not verified"})
		return
	}
	prov := in.provisionInput()
	prov.OwnerName, prov.OwnerEmail, prov.GoogleSub = ident.Name, ident.Email, ident.Sub
	s.provisionAndSignIn(c, prov)
}

// Refresh rotates the refresh token: the presented token is atomically
// revoked and a fresh pair is issued.
func (s *Server) Refresh(c *gin.Context) {
	var in struct {
		RefreshToken string `json:"refresh_token"`
	}
	_ = c.ShouldBindJSON(&in)
	if in.RefreshToken == "" {
		if cookie, err := c.Cookie("wakili_rt"); err == nil {
			in.RefreshToken = cookie
		}
	}
	if in.RefreshToken == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "missing refresh token"})
		return
	}
	var resp gin.H
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		userID, err := repository.ConsumeRefreshToken(c.Request.Context(), tx, auth.HashRefreshToken(in.RefreshToken))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "refresh token invalid or already used"})
			return errHandled
		}
		if err != nil {
			return err
		}
		user, err := repository.UserByID(c.Request.Context(), tx, userID)
		if err != nil {
			return err
		}
		resp, err = s.issueTokens(c, tx, user)
		return err
	})
	if ok && resp != nil {
		c.JSON(http.StatusOK, resp)
	}
}

func (s *Server) Logout(c *gin.Context) {
	userID := s.claims(c).UserID()
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		return repository.RevokeUserRefreshTokens(c.Request.Context(), tx, userID)
	})
	if !ok {
		return
	}
	s.setAuthCookies(c, "", "")
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) Me(c *gin.Context) {
	userID := s.claims(c).UserID()
	var user *repository.User
	perms := []string{}
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		u, err := repository.UserByID(c.Request.Context(), tx, userID)
		if err != nil {
			return err
		}
		user = u
		if u.RoleID != nil {
			perms, err = repository.RolePermissions(c.Request.Context(), tx, *u.RoleID)
		}
		return err
	})
	if ok {
		tenant := s.tenant(c)
		// Read fresh, not from the 30 s tenant cache, so finishing onboarding
		// takes effect on the very next page load.
		if fresh, err := repository.TenantByID(c.Request.Context(), s.DB.Pool, tenant.ID); err == nil {
			tenant = fresh
		}
		isOwner := tenant.OwnerUserID != nil && *tenant.OwnerUserID == user.ID
		c.JSON(http.StatusOK, gin.H{"user": user, "permissions": perms, "tenant": gin.H{
			"id": tenant.ID, "slug": tenant.Slug, "name": tenant.Name, "plan": tenant.Plan,
			"data_residency_ke": tenant.DataResidencyKE, "reg_number": tenant.RegNumber, "phone": tenant.Phone,
			"onboarding_completed": tenant.OnboardingCompletedAt != nil, "is_owner": isOwner,
			"owner_user_id": tenant.OwnerUserID,
		}})
	}
}

// errHandled signals that the handler already wrote a response; withTenant
// must not write another one. The transaction is rolled back, which is safe
// for these read-mostly paths.
var errHandled = &handledError{}

type handledError struct{}

func (*handledError) Error() string { return "handled" }
