package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
)

const CtxAdmin = "wakili.admin"

// RequirePlatformAdmin authenticates a super-admin (cross-tenant control
// plane). Unlike Auth, it does NOT resolve or require a tenant. It accepts the
// admin token from the Authorization header or the wakili_admin_at cookie and
// rejects ordinary tenant tokens (wrong issuer, checked in ParseAdminToken).
func RequirePlatformAdmin(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		var token string
		if h := c.GetHeader("Authorization"); strings.HasPrefix(h, "Bearer ") {
			token = strings.TrimPrefix(h, "Bearer ")
		} else if cookie, err := c.Cookie("wakili_admin_at"); err == nil {
			token = cookie
		}
		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing admin credentials"})
			return
		}
		claims, err := auth.ParseAdminToken(cfg.JWTSecret, token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid or expired admin token"})
			return
		}
		c.Set(CtxAdmin, claims)
		c.Next()
	}
}

func AdminFrom(c *gin.Context) *auth.AdminClaims {
	v, _ := c.Get(CtxAdmin)
	a, _ := v.(*auth.AdminClaims)
	return a
}
