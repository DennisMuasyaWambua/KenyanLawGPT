package google

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// stubTokenInfo points TokenInfoURL at a server returning the given status and
// JSON body, restoring the original URL on cleanup.
func stubTokenInfo(t *testing.T, status int, body string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("id_token") == "" {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	orig := TokenInfoURL
	TokenInfoURL = srv.URL
	t.Cleanup(func() {
		TokenInfoURL = orig
		srv.Close()
	})
}

func TestVerifyValidToken(t *testing.T) {
	stubTokenInfo(t, http.StatusOK, `{
		"aud":"client-123","sub":"google-sub-1","email":"Jane@Firm.CO.KE",
		"email_verified":"true","name":"Jane Mwangi"}`)

	id, err := Verify(context.Background(), "any-token", "client-123")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id.Sub != "google-sub-1" {
		t.Errorf("sub = %q", id.Sub)
	}
	if id.Email != "jane@firm.co.ke" {
		t.Errorf("email not lowercased: %q", id.Email)
	}
	if !id.EmailVerified {
		t.Error("expected email_verified true")
	}
	if id.Name != "Jane Mwangi" {
		t.Errorf("name = %q", id.Name)
	}
}

func TestVerifyAudienceMismatch(t *testing.T) {
	stubTokenInfo(t, http.StatusOK, `{"aud":"someone-else","sub":"s","email":"a@b.com","email_verified":"true"}`)
	if _, err := Verify(context.Background(), "tok", "client-123"); err == nil {
		t.Fatal("expected audience mismatch error")
	}
}

func TestVerifyEmptyAudienceSkipsCheck(t *testing.T) {
	// An empty clientID disables the audience check (dev only).
	stubTokenInfo(t, http.StatusOK, `{"aud":"whatever","sub":"s","email":"a@b.com","email_verified":"true"}`)
	if _, err := Verify(context.Background(), "tok", ""); err != nil {
		t.Fatalf("expected no error with empty clientID, got %v", err)
	}
}

func TestVerifyUnverifiedEmailParsed(t *testing.T) {
	stubTokenInfo(t, http.StatusOK, `{"aud":"c","sub":"s","email":"a@b.com","email_verified":"false"}`)
	id, err := Verify(context.Background(), "tok", "c")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id.EmailVerified {
		t.Error("expected email_verified false")
	}
}

func TestVerifyRejectsNon200(t *testing.T) {
	stubTokenInfo(t, http.StatusUnauthorized, `{"error":"invalid_token"}`)
	if _, err := Verify(context.Background(), "tok", "c"); err == nil {
		t.Fatal("expected error on non-200 tokeninfo response")
	}
}

func TestVerifyRejectsMissingSubject(t *testing.T) {
	stubTokenInfo(t, http.StatusOK, `{"aud":"c","email":"a@b.com","email_verified":"true"}`)
	if _, err := Verify(context.Background(), "tok", "c"); err == nil {
		t.Fatal("expected error when subject missing")
	}
}

func TestVerifyEmptyToken(t *testing.T) {
	if _, err := Verify(context.Background(), "  ", "c"); err == nil {
		t.Fatal("expected error on empty token")
	}
}
