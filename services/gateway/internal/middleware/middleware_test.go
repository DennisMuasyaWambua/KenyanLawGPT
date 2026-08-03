package middleware_test

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

const (
	tenantA = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
	tenantB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
	secret  = "test-secret"
)

func testRouter(resolved *repository.Tenant, mws ...gin.HandlerFunc) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	chain := append([]gin.HandlerFunc{func(c *gin.Context) {
		c.Set(middleware.CtxTenant, resolved) // stand-in for the subdomain resolver
	}}, mws...)
	chain = append(chain, func(c *gin.Context) { c.String(http.StatusOK, "ok") })
	r.GET("/x", chain...)
	return r
}

func doGet(r *gin.Engine, token string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// The REST-path isolation guarantee: a perfectly valid JWT for tenant A must
// be rejected when presented on tenant B's (subdomain-resolved) context.
func TestAuthRejectsCrossTenantToken(t *testing.T) {
	cfg := &config.Config{JWTSecret: secret}
	tokenA, err := auth.IssueAccessToken(secret, "user-1", tenantA, "firm-a", rbac.RoleOwner, time.Minute)
	if err != nil {
		t.Fatal(err)
	}

	r := testRouter(&repository.Tenant{ID: tenantB, Slug: "firm-b", Status: "active"}, middleware.Auth(cfg))
	if w := doGet(r, tokenA); w.Code != http.StatusForbidden {
		t.Fatalf("cross-tenant token accepted: status %d body %s", w.Code, w.Body.String())
	}

	r = testRouter(&repository.Tenant{ID: tenantA, Slug: "firm-a", Status: "active"}, middleware.Auth(cfg))
	if w := doGet(r, tokenA); w.Code != http.StatusOK {
		t.Fatalf("same-tenant token rejected: status %d body %s", w.Code, w.Body.String())
	}
}

func TestAuthRejectsMissingOrGarbageToken(t *testing.T) {
	cfg := &config.Config{JWTSecret: secret}
	r := testRouter(&repository.Tenant{ID: tenantA, Slug: "firm-a", Status: "active"}, middleware.Auth(cfg))
	if w := doGet(r, ""); w.Code != http.StatusUnauthorized {
		t.Fatalf("missing token: got %d", w.Code)
	}
	if w := doGet(r, "not.a.jwt"); w.Code != http.StatusUnauthorized {
		t.Fatalf("garbage token: got %d", w.Code)
	}
}

func TestRBACMiddlewareGates(t *testing.T) {
	cfg := &config.Config{JWTSecret: secret}
	tenant := &repository.Tenant{ID: tenantA, Slug: "firm-a", Status: "active"}

	paralegal, _ := auth.IssueAccessToken(secret, "u", tenantA, "firm-a", rbac.RoleParalegal, time.Minute)
	client, _ := auth.IssueAccessToken(secret, "u", tenantA, "firm-a", rbac.RoleClient, time.Minute)
	partner, _ := auth.IssueAccessToken(secret, "u", tenantA, "firm-a", rbac.RolePartner, time.Minute)

	partnerGate := testRouter(tenant, middleware.Auth(cfg), middleware.RequireRole(rbac.RolePartner))
	if w := doGet(partnerGate, paralegal); w.Code != http.StatusForbidden {
		t.Fatalf("paralegal passed partner gate: %d", w.Code)
	}
	if w := doGet(partnerGate, partner); w.Code != http.StatusOK {
		t.Fatalf("partner blocked at partner gate: %d", w.Code)
	}

	staffGate := testRouter(tenant, middleware.Auth(cfg), middleware.RequireStaff())
	if w := doGet(staffGate, client); w.Code != http.StatusForbidden {
		t.Fatalf("portal client passed staff gate: %d", w.Code)
	}
	if w := doGet(staffGate, paralegal); w.Code != http.StatusOK {
		t.Fatalf("paralegal blocked at staff gate: %d", w.Code)
	}
}
