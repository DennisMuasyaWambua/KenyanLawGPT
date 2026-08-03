package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/services"
)

// Signup provisions a new firm (tenant) — the one endpoint that runs outside
// tenant context.
func (s *Server) Signup(c *gin.Context) {
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
	c.JSON(http.StatusCreated, gin.H{"tenant": tenant, "owner": gin.H{"id": owner.ID, "email": owner.Email}})
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
	access, err := auth.IssueAccessToken(s.Cfg.JWTSecret, user.ID, tenant.ID, tenant.Slug, user.Role, s.Cfg.AccessTTL)
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
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		u, err := repository.UserByID(c.Request.Context(), tx, userID)
		user = u
		return err
	})
	if ok {
		tenant := s.tenant(c)
		c.JSON(http.StatusOK, gin.H{"user": user, "tenant": gin.H{
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
