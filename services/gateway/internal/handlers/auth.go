package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/integrations/google"
	"github.com/wakiliai/gateway/internal/repository"
)

// Signup is disabled. Firms are provisioned only via the super-admin control
// center; staff are onboarded by a Partner/Managing Partner. This prevents
// duplicate law firms from public self-registration.
func (s *Server) Signup(c *gin.Context) {
	c.JSON(http.StatusForbidden, gin.H{"error": "public sign-up is disabled — ask a partner to onboard you"})
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
	access, err := auth.IssueAccessTokenWithRole(s.Cfg.JWTSecret, user.ID, tenant.ID, tenant.Slug, user.Role, roleID, s.Cfg.AccessTTL)
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

// GoogleSignup is disabled for the same reason as Signup — no public firm
// self-registration.
func (s *Server) GoogleSignup(c *gin.Context) {
	c.JSON(http.StatusForbidden, gin.H{"error": "public sign-up is disabled — ask a partner to onboard you"})
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
		c.JSON(http.StatusOK, gin.H{"user": user, "permissions": perms, "tenant": gin.H{
			"id": tenant.ID, "slug": tenant.Slug, "name": tenant.Name, "plan": tenant.Plan,
			"data_residency_ke": tenant.DataResidencyKE,
		}})
	}
}

// errHandled signals that the handler already wrote a response; withTenant
// must not write another one. The transaction is rolled back, which is safe
// for these read-mostly paths.
var errHandled = &handledError{}

type handledError struct{}

func (*handledError) Error() string { return "handled" }
