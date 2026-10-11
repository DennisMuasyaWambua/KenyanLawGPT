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

func TestSignupClosedWhenDisabled(t *testing.T) {
	s := testServer() // PublicSignupEnabled defaults to false here
	for name, h := range map[string]gin.HandlerFunc{"password": s.Signup, "google": s.GoogleSignup} {
		w := call(http.MethodPost, "/s", "/s", `{}`, h, nil, nil)
		if w.Code != http.StatusForbidden {
			t.Fatalf("%s signup with PUBLIC_SIGNUP_ENABLED=false: want 403, got %d: %s", name, w.Code, w.Body.String())
		}
	}
}

func TestSignupRequiresFirmAndOwnerDetails(t *testing.T) {
	s := testServer()
	s.Cfg.PublicSignupEnabled = true
	for _, body := range []string{
		`{}`,
		`{"owner_name":"A","owner_email":"a@b.co","owner_password":"longenough"}`,                     // no firm
		`{"firm_name":"Mwangi Advocates","owner_name":"A","owner_password":"longenough"}`,             // no email
		`{"firm_name":"Mwangi Advocates","owner_name":"A","owner_email":"nope","owner_password":"x"}`, // bad email
	} {
		w := call(http.MethodPost, "/s", "/s", body, s.Signup, nil, nil)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("body %s: want 400 before any provisioning, got %d: %s", body, w.Code, w.Body.String())
		}
	}
}

func TestSignupNeverTakesPlanFromRequest(t *testing.T) {
	in := firmSignup{FirmName: "Mwangi & Co. Advocates"}
	got := in.provisionInput()
	if got.Plan != "starter" || got.Slug != "mwangi-co-advocates" || !got.DataResidencyKE {
		t.Fatalf("unexpected provision input: %+v", got)
	}
}

func TestGoogleSignupUnverifiedEmail(t *testing.T) {
	stubGoogle(t, http.StatusOK, `{"aud":"client-123","sub":"s","email":"a@b.com","email_verified":"false"}`)
	s := testServer()
	s.Cfg.PublicSignupEnabled = true
	w := call(http.MethodPost, "/gs", "/gs", `{"credential":"x","firm_name":"Firm"}`, s.GoogleSignup, nil, nil)
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

// --- Temporary passwords / first-login change ---------------------------------

func TestChangePasswordValidation(t *testing.T) {
	s := testServer()
	claims := &auth.Claims{UserID: "u1", TenantID: "t1"}
	for _, body := range []string{
		`{"current_password":"Kp7m-Qx4r-Ze9t"}`,
		`{"current_password":"Kp7m-Qx4r-Ze9t","new_password":"short"}`,
		`{"current_password":"Kp7m-Qx4r-Ze9t","new_password":"Kp7m-Qx4r-Ze9t"}`,
	} {
		w := call(http.MethodPost, "/cp", "/cp", body, s.ChangePassword, aTenant(), claims)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("body %s: want 400, got %d: %s", body, w.Code, w.Body.String())
		}
	}
}

func TestResendLoginGuards(t *testing.T) {
	s := testServer()
	owner := "owner-1"
	tenant := aTenant()
	tenant.OwnerUserID = &owner
	// Nobody resets their own password here, and nobody but the owner resets the owner.
	w := call(http.MethodPost, "/u/:id", "/u/u1", `{}`, s.ResendLogin, tenant, &auth.Claims{UserID: "u1"})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("self reset: want 400, got %d", w.Code)
	}
	w = call(http.MethodPost, "/u/:id", "/u/owner-1", `{}`, s.ResendLogin, tenant, &auth.Claims{UserID: "u2"})
	if w.Code != http.StatusForbidden {
		t.Fatalf("owner reset by partner: want 403, got %d", w.Code)
	}
}

func TestCreateUserRejectsShortExplicitPassword(t *testing.T) {
	s := testServer()
	w := call(http.MethodPost, "/u", "/u", `{"email":"a@b.co","full_name":"A","role_id":"r","password":"short"}`,
		s.CreateUser, aTenant(), &auth.Claims{UserID: "u1"})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400, got %d: %s", w.Code, w.Body.String())
	}
}

// --- Speaker-labelled transcripts ---------------------------------------------

func TestSpeakerTranscriptUsesNamesAndMergesRenamedSpeakers(t *testing.T) {
	r := &repository.Recording{
		TranscriptSegments: []byte(`[{"speaker":1,"start":2,"end":4,"text":"Good morning."},
			{"speaker":2,"start":5,"end":6,"text":"Morning, wakili."},
			{"speaker":3,"start":6,"end":7,"text":"I brought the title deed."},
			{"speaker":1,"start":3700,"end":3702,"text":"Thank you."}]`),
		// The diarizer split the client into speakers 2 and 3; naming both merges them.
		SpeakerNames: []byte(`{"1":"Adv. Wanjiru","2":"Client","3":"Client"}`),
	}
	want := "[00:02] Adv. Wanjiru: Good morning.\n" +
		"[00:05] Client: Morning, wakili. I brought the title deed.\n" +
		"[1:01:40] Adv. Wanjiru: Thank you."
	if got := speakerTranscript(r); got != want {
		t.Fatalf("got:\n%s\nwant:\n%s", got, want)
	}
	if got := speakerTranscript(&repository.Recording{TranscriptSegments: []byte(`[]`)}); got != "" {
		t.Fatalf("no segments should render nothing, got %q", got)
	}
}

func TestSetRecordingSpeakersValidatesLabels(t *testing.T) {
	s := testServer()
	for _, body := range []string{`{"names":{"x":"A"}}`, `{"names":{"0":"A"}}`, `{"names":{"99":"A"}}`} {
		w := call(http.MethodPut, "/r/:id", "/r/1", body, s.SetRecordingSpeakers, aTenant(), &auth.Claims{UserID: "u1"})
		if w.Code != http.StatusBadRequest {
			t.Fatalf("body %s: want 400, got %d", body, w.Code)
		}
	}
}

func TestFirmInfoExposesOnlyNameAndSlug(t *testing.T) {
	s := testServer()
	owner := "u-owner"
	tenant := aTenant()
	tenant.OwnerUserID, tenant.RegNumber = &owner, "LSK/1"
	w := call(http.MethodGet, "/f", "/f", "", s.FirmInfo, tenant, nil)
	if w.Code != http.StatusOK || w.Body.String() != `{"firm":{"name":"Firm A","slug":"firm-a"}}` {
		t.Fatalf("got %d %s", w.Code, w.Body.String())
	}
}
