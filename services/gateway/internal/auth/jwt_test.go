package auth

import (
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
