package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

const (
	CtxTenant = "wakili.tenant"
	CtxClaims = "wakili.claims"
	CtxTrace  = "wakili.trace"
)

// RequestID propagates a correlation id from the frontend (X-Request-ID) or
// mints one; it flows through logs and into the gRPC metadata to Python.
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		tid := c.GetHeader("X-Request-ID")
		if tid == "" {
			tid = uuid.NewString()
		}
		c.Set(CtxTrace, tid)
		c.Header("X-Request-ID", tid)
		c.Request = c.Request.WithContext(logging.WithTrace(c.Request.Context(), tid))
		c.Next()
	}
}

func TraceID(c *gin.Context) string {
	if v, ok := c.Get(CtxTrace); ok {
		return v.(string)
	}
	return ""
}

func CORS(origins []string) gin.HandlerFunc {
	allowed := map[string]bool{}
	for _, o := range origins {
		allowed[strings.TrimSpace(o)] = true
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if allowed[origin] || allowed["*"] {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Credentials", "true")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Tenant-Slug, X-Request-ID")
			c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

// tenantCache avoids a DB hit per request; entries expire after 30s so plan /
// status changes propagate quickly.
type tenantCache struct {
	mu sync.RWMutex
	m  map[string]tenantCacheEntry
}

type tenantCacheEntry struct {
	t   *repository.Tenant
	exp time.Time
}

var tcache = tenantCache{m: map[string]tenantCacheEntry{}}

// Tenant resolves the tenant from the X-Tenant-Slug header (set by the
// Next.js middleware from the subdomain) or, failing that, from the Host
// subdomain itself. The resolved row is the ONLY source of tenant identity —
// request bodies are never trusted for tenant_id.
func Tenant(database *db.DB, cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		slug := strings.ToLower(strings.TrimSpace(c.GetHeader("X-Tenant-Slug")))
		if slug == "" {
			host := c.Request.Host
			if h, _, ok := strings.Cut(host, ":"); ok {
				host = h
			}
			if strings.HasSuffix(host, "."+cfg.BaseDomain) {
				slug = strings.TrimSuffix(host, "."+cfg.BaseDomain)
			}
		}
		if slug == "" {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "tenant not specified"})
			return
		}

		tcache.mu.RLock()
		entry, ok := tcache.m[slug]
		tcache.mu.RUnlock()
		var tenant *repository.Tenant
		if ok && time.Now().Before(entry.exp) {
			tenant = entry.t
		} else {
			t, err := repository.TenantBySlug(c.Request.Context(), database.Pool, slug)
			if err == pgx.ErrNoRows {
				c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "unknown tenant"})
				return
			}
			if err != nil {
				c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "tenant lookup failed"})
				return
			}
			tenant = t
			tcache.mu.Lock()
			tcache.m[slug] = tenantCacheEntry{t: t, exp: time.Now().Add(30 * time.Second)}
			tcache.mu.Unlock()
		}
		if tenant.Status != "active" {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "tenant suspended"})
			return
		}
		c.Set(CtxTenant, tenant)
		c.Next()
	}
}

func TenantFrom(c *gin.Context) *repository.Tenant {
	v, _ := c.Get(CtxTenant)
	t, _ := v.(*repository.Tenant)
	return t
}

// Auth verifies the JWT and — critically — cross-checks the token's tenant
// claim against the tenant resolved from the subdomain. A valid token from
// tenant A presented on tenant B's subdomain is rejected.
func Auth(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		var token string
		if h := c.GetHeader("Authorization"); strings.HasPrefix(h, "Bearer ") {
			token = strings.TrimPrefix(h, "Bearer ")
		} else if cookie, err := c.Cookie("wakili_at"); err == nil {
			token = cookie
		}
		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing credentials"})
			return
		}
		claims, err := auth.ParseAccessToken(cfg.JWTSecret, token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid or expired token"})
			return
		}
		tenant := TenantFrom(c)
		if tenant == nil || claims.TenantID != tenant.ID {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "token does not belong to this tenant"})
			return
		}
		c.Set(CtxClaims, claims)
		c.Next()
	}
}

func ClaimsFrom(c *gin.Context) *auth.Claims {
	v, _ := c.Get(CtxClaims)
	cl, _ := v.(*auth.Claims)
	return cl
}

// RequireRole enforces a minimum role for the route group.
func RequireRole(min string) gin.HandlerFunc {
	return func(c *gin.Context) {
		cl := ClaimsFrom(c)
		if cl == nil || !rbac.AtLeast(cl.Role, min) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "insufficient role"})
			return
		}
		c.Next()
	}
}

// RequireStaff blocks portal (client) accounts from firm-internal routes.
func RequireStaff() gin.HandlerFunc {
	return func(c *gin.Context) {
		cl := ClaimsFrom(c)
		if cl == nil || !rbac.IsStaff(cl.Role) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "staff only"})
			return
		}
		c.Next()
	}
}

// RequireFirmMember admits any firm member (a user with a role) and blocks
// portal clients. Under RBAC a portal client has no role_id; the role-name
// fallback keeps pre-RBAC tokens working through their short TTL.
func RequireFirmMember() gin.HandlerFunc {
	return func(c *gin.Context) {
		cl := ClaimsFrom(c)
		if cl == nil || !isFirmMember(cl) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "firm members only"})
			return
		}
		c.Next()
	}
}

func isFirmMember(cl *auth.Claims) bool {
	if cl.RoleID != "" {
		return true
	}
	return cl.Role != "" && cl.Role != rbac.RoleClient // legacy token fallback
}

// --- Permission checks (firm-scoped RBAC) -----------------------------------

// permCache memoizes a role's permission set for a short window so role edits
// take effect within seconds without re-issuing tokens or hitting the DB every
// request. Mirrors the tenant cache above.
type permCacheEntry struct {
	perms map[string]bool
	exp   time.Time
}

var (
	permMu    sync.RWMutex
	permCache = map[string]permCacheEntry{}
)

const permCacheTTL = 30 * time.Second

// resolvePermissions loads (and caches) the granted permission set for the
// caller's role in this tenant. Legacy tokens without a role id fall back to
// resolving the user's role_id from the DB, so the switch self-heals.
func resolvePermissions(c *gin.Context, database *db.DB) (map[string]bool, error) {
	cl := ClaimsFrom(c)
	tenant := TenantFrom(c)
	if cl == nil || tenant == nil {
		return map[string]bool{}, nil
	}
	key := tenant.ID + "|r:" + cl.RoleID
	if cl.RoleID == "" {
		key = tenant.ID + "|u:" + cl.UserID
	}
	permMu.RLock()
	entry, ok := permCache[key]
	permMu.RUnlock()
	if ok && time.Now().Before(entry.exp) {
		return entry.perms, nil
	}

	var perms []string
	err := database.WithTenant(c.Request.Context(), tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
		roleID := cl.RoleID
		if roleID == "" {
			u, err := repository.UserByID(c.Request.Context(), tx, cl.UserID)
			if err != nil {
				return err
			}
			if u.RoleID != nil {
				roleID = *u.RoleID
			}
		}
		if roleID == "" { // portal client / no role assigned
			return nil
		}
		p, err := repository.RolePermissions(c.Request.Context(), tx, roleID)
		perms = p
		return err
	})
	if err != nil {
		return nil, err
	}
	set := make(map[string]bool, len(perms))
	for _, p := range perms {
		set[p] = true
	}
	permMu.Lock()
	permCache[key] = permCacheEntry{perms: set, exp: time.Now().Add(permCacheTTL)}
	permMu.Unlock()
	return set, nil
}

// HasPermission reports whether the caller's role grants perm. Handlers use it
// for conditional logic (e.g. widening a query, or gating a shared vs personal
// branch) without a dedicated route gate.
func HasPermission(c *gin.Context, database *db.DB, perm string) bool {
	set, err := resolvePermissions(c, database)
	if err != nil {
		logging.L(c.Request.Context()).Error("permission resolve failed", "err", err, "perm", perm)
		return false
	}
	return set[perm]
}

// RequirePermission gates a route on a single catalog permission.
func RequirePermission(database *db.DB, perm string) gin.HandlerFunc {
	return func(c *gin.Context) {
		set, err := resolvePermissions(c, database)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "permission check failed"})
			return
		}
		if !set[perm] {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "missing permission: " + perm})
			return
		}
		c.Next()
	}
}

// RateLimit is a per-tenant sliding window using Redis INCR/EXPIRE.
func RateLimit(rdb *redis.Client, perMin int) gin.HandlerFunc {
	return func(c *gin.Context) {
		tenant := TenantFrom(c)
		key := "rl:global"
		if tenant != nil {
			key = "rl:" + tenant.ID
		}
		key += ":" + time.Now().Format("200601021504")
		n, err := rdb.Incr(c.Request.Context(), key).Result()
		if err == nil {
			if n == 1 {
				rdb.Expire(c.Request.Context(), key, 90*time.Second)
			}
			if n > int64(perMin) {
				c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "rate limit exceeded"})
				return
			}
		}
		c.Next()
	}
}

// Audit writes a structured who/what/when/tenant record for every mutating
// request (KDPA accountability). It runs after the handler so the response
// status is known, and inserts under the tenant's app.tenant_id so the RLS
// policy on public.audit_log holds.
func Audit(database *db.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()
		switch c.Request.Method {
		case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		default:
			return
		}
		tenant := TenantFrom(c)
		if tenant == nil {
			return
		}
		var userID *string
		if cl := ClaimsFrom(c); cl != nil {
			uid := cl.UserID
			userID = &uid
		}
		entry := &repository.AuditEntry{
			ID:       uuid.NewString(),
			TenantID: tenant.ID,
			UserID:   userID,
			Action:   c.Request.Method + " " + c.FullPath(),
			Resource: c.Request.URL.Path,
			Status:   c.Writer.Status(),
			IP:       c.ClientIP(),
			TraceID:  TraceID(c),
		}
		if detail, err := json.Marshal(gin.H{"query": c.Request.URL.RawQuery}); err == nil {
			entry.Detail = detail
		}
		go func() {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := database.WithPublic(ctx, tenant.ID, func(tx pgx.Tx) error {
				return repository.InsertAudit(ctx, tx, entry)
			}); err != nil {
				logging.L(ctx).Error("audit insert failed", "err", err)
			}
		}()
	}
}
