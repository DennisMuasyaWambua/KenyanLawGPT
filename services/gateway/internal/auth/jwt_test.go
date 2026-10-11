package auth

import (
	"strings"
	"testing"
	"time"
)

func TestAccessTokenRoundTrip(t *testing.T) {
	secret := "test-secret"
	tok, err := IssueAccessToken(secret, "user-1", "tenant-1", "mwangi-advocates", "partner", time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	claims, err := ParseAccessToken(secret, tok)
	if err != nil {
		t.Fatal(err)
	}
	if claims.UserID != "user-1" || claims.TenantID != "tenant-1" || claims.Role != "partner" {
		t.Fatalf("claims mismatch: %+v", claims)
	}
}

func TestAccessTokenWrongSecret(t *testing.T) {
	tok, _ := IssueAccessToken("secret-a", "u", "t", "s", "owner", time.Minute)
	if _, err := ParseAccessToken("secret-b", tok); err == nil {
		t.Fatal("token verified with wrong secret")
	}
}

func TestAccessTokenExpired(t *testing.T) {
	tok, _ := IssueAccessToken("s", "u", "t", "s", "owner", -time.Minute)
	if _, err := ParseAccessToken("s", tok); err == nil {
		t.Fatal("expired token accepted")
	}
}

func TestRefreshTokenHashing(t *testing.T) {
	raw, hash, err := NewRefreshToken()
	if err != nil {
		t.Fatal(err)
	}
	if raw == hash {
		t.Fatal("raw token must not equal stored hash")
	}
	if HashRefreshToken(raw) != hash {
		t.Fatal("hash mismatch")
	}
}

func TestPasswordChangeClaimRoundTrip(t *testing.T) {
	tok, err := IssueUserAccessToken("s", "u", "t", "slug", "Associate", "r", true, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	cl, err := ParseAccessToken("s", tok)
	if err != nil || !cl.PasswordChange {
		t.Fatalf("flag lost: %+v %v", cl, err)
	}
	tok, _ = IssueAccessTokenWithRole("s", "u", "t", "slug", "Associate", "r", time.Minute)
	if cl, _ := ParseAccessToken("s", tok); cl.PasswordChange {
		t.Fatal("ordinary token must not carry the flag")
	}
}

func TestTemporaryPasswordShape(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 50; i++ {
		p, err := NewTemporaryPassword()
		if err != nil {
			t.Fatal(err)
		}
		if len(p) != 14 || p[4] != '-' || p[9] != '-' || strings.ContainsAny(p, "0O1lI") {
			t.Fatalf("bad temporary password %q", p)
		}
		if seen[p] {
			t.Fatalf("duplicate temporary password %q", p)
		}
		seen[p] = true
	}
}
