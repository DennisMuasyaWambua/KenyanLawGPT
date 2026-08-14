package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/integrations/google"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

// These are handler-level tests for the validation and auth-failure paths of
// the new Google / invite / calendar flows — every path that returns *before*
// touching the database, which is exactly where the security checks live. The
// DB-backed happy paths need a live Postgres tenant schema and are out of scope
// for unit tests.

func testServer() *Server {
	return &Server{Cfg: &config.Config{
		GoogleClientID: "client-123", JWTSecret: "test-secret",
		AccessTTL: time.Minute, RefreshTTL: time.Hour, Env: "dev",
	}}
}

// stubGoogle points Google verification at a local server returning a canned
// tokeninfo payload, so no network call is made.
func stubGoogle(t *testing.T, status int, body string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	orig := google.TokenInfoURL
	google.TokenInfoURL = srv.URL
	t.Cleanup(func() { google.TokenInfoURL = orig; srv.Close() })
}

// call wires one handler behind a stand-in middleware that seeds the tenant and
// claims the real middleware chain would normally set.
func call(method, pattern, reqPath, body string, h gin.HandlerFunc,
	tenant *repository.Tenant, claims *auth.Claims) *httptest.ResponseRecorder {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		if tenant != nil {
			c.Set(middleware.CtxTenant, tenant)
		}
		if claims != nil {
			c.Set(middleware.CtxClaims, claims)
		}
	})
	r.Handle(method, pattern, h)
	req := httptest.NewRequest(method, reqPath, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func aTenant() *repository.Tenant {
	return &repository.Tenant{ID: "t1", Slug: "firm-a", Name: "Firm A", SchemaName: "tenant_x", Status: "active"}
}

// --- Google sign-in / sign-up ------------------------------------------------

func TestGoogleLoginMissingCredential(t *testing.T) {
	s := testServer()
	w := call(http.MethodPost, "/g", "/g", `{}`, s.GoogleLogin, aTenant(), nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestGoogleLoginInvalidCredential(t *testing.T) {
	stubGoogle(t, http.StatusOK, `{"aud":"someone-else","sub":"s","email":"a@b.com","email_verified":"true"}`)
	s := testServer()
	w := call(http.MethodPost, "/g", "/g", `{"credential":"x"}`, s.GoogleLogin, aTenant(), nil)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 on audience mismatch, got %d: %s", w.Code, w.Body.String())
	}
}

func TestGoogleLoginUnverifiedEmail(t *testing.T) {
	stubGoogle(t, http.StatusOK, `{"aud":"client-123","sub":"s","email":"a@b.com","email_verified":"false"}`)
	s := testServer()
	w := call(http.MethodPost, "/g", "/g", `{"credential":"x"}`, s.GoogleLogin, aTenant(), nil)
	if w.Code != http.StatusForbidden {
		t.Fatalf("want 403 on unverified email, got %d: %s", w.Code, w.Body.String())
	}
}

func TestGoogleSignupMissingCredential(t *testing.T) {
	s := testServer()
	w := call(http.MethodPost, "/gs", "/gs", `{}`, s.GoogleSignup, nil, nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestGoogleSignupUnverifiedEmail(t *testing.T) {
	stubGoogle(t, http.StatusOK, `{"aud":"client-123","sub":"s","email":"a@b.com","email_verified":"false"}`)
	s := testServer()
	w := call(http.MethodPost, "/gs", "/gs", `{"credential":"x"}`, s.GoogleSignup, nil, nil)
	if w.Code != http.StatusForbidden {
		t.Fatalf("want 403, got %d: %s", w.Code, w.Body.String())
	}
}

// --- Staff invites -----------------------------------------------------------

// Under RBAC an invite pre-assigns exactly one role_id; the request is rejected
// (before any DB work) when it's missing. Which roles a caller may assign is
// enforced by the users.invite permission on the route, not by role strings.
func TestInviteUserRequiresRoleID(t *testing.T) {
	s := testServer()
	claims := &auth.Claims{UserID: "u1", Role: rbac.RoleOwner}
	w := call(http.MethodPost, "/inv", "/inv", `{"email":"a@b.com"}`, s.InviteUser, aTenant(), claims)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 when role_id is missing, got %d: %s", w.Code, w.Body.String())
	}
}

func TestAcceptInviteShortPassword(t *testing.T) {
	s := testServer()
	w := call(http.MethodPost, "/i/:token/accept", "/i/tok/accept", `{"password":"short"}`,
		s.AcceptInvite, aTenant(), nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 on short password, got %d: %s", w.Code, w.Body.String())
	}
}

func TestAcceptInviteBadGoogleCredential(t *testing.T) {
	stubGoogle(t, http.StatusUnauthorized, `{"error":"invalid_token"}`)
	s := testServer()
	w := call(http.MethodPost, "/i/:token/accept", "/i/tok/accept", `{"credential":"x"}`,
		s.AcceptInvite, aTenant(), nil)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 on bad Google credential, got %d: %s", w.Code, w.Body.String())
	}
}

// --- Calendar ----------------------------------------------------------------

func TestCreateCalendarEventInvalidScope(t *testing.T) {
	s := testServer()
	claims := &auth.Claims{UserID: "u1", Role: rbac.RoleAssociate}
	body := `{"scope":"weekly","title":"Sync","start_at":"2026-01-01T09:00:00Z"}`
	w := call(http.MethodPost, "/ev", "/ev", body, s.CreateCalendarEvent, aTenant(), claims)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 on invalid scope, got %d: %s", w.Code, w.Body.String())
	}
}

func TestCreateCalendarEventMissingTitle(t *testing.T) {
	s := testServer()
	claims := &auth.Claims{UserID: "u1", Role: rbac.RoleAssociate}
	body := `{"scope":"personal","start_at":"2026-01-01T09:00:00Z"}`
	w := call(http.MethodPost, "/ev", "/ev", body, s.CreateCalendarEvent, aTenant(), claims)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 on missing title, got %d: %s", w.Code, w.Body.String())
	}
}

func TestUpdateCalendarEventInvalidBody(t *testing.T) {
	s := testServer()
	claims := &auth.Claims{UserID: "u1", Role: rbac.RoleAssociate}
	w := call(http.MethodPut, "/ev/:id", "/ev/e1", `{"scope":"personal"}`, // missing title/start_at
		s.UpdateCalendarEvent, aTenant(), claims)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 on invalid update body, got %d: %s", w.Code, w.Body.String())
	}
}

// --- parseTime helper --------------------------------------------------------

func TestParseTime(t *testing.T) {
	if _, ok := parseTime(""); ok {
		t.Error("empty should not parse")
	}
	if _, ok := parseTime("not-a-date"); ok {
		t.Error("garbage should not parse")
	}
	if _, ok := parseTime("2026-08-08"); !ok {
		t.Error("date form should parse")
	}
	if _, ok := parseTime("2026-08-08T10:30:00Z"); !ok {
		t.Error("RFC3339 should parse")
	}
}
