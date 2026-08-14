package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type Claims struct {
	UserID   string `json:"uid"`
	TenantID string `json:"tid"`
	Slug     string `json:"slug"`
	Role     string `json:"role"`          // denormalized role name (display / legacy)
	RoleID   string `json:"rid,omitempty"` // firm-scoped role id — source of truth for permissions
	jwt.RegisteredClaims
}

// IssueAccessToken keeps the legacy signature (no role id). Prefer
// IssueAccessTokenWithRole in production paths.
func IssueAccessToken(secret, userID, tenantID, slug, role string, ttl time.Duration) (string, error) {
	return IssueAccessTokenWithRole(secret, userID, tenantID, slug, role, "", ttl)
}

// IssueAccessTokenWithRole embeds the firm-scoped role id used by the permission
// middleware to resolve the caller's granted permissions.
func IssueAccessTokenWithRole(secret, userID, tenantID, slug, role, roleID string, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := &Claims{
		UserID: userID, TenantID: tenantID, Slug: slug, Role: role, RoleID: roleID,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    "wakiliai",
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func ParseAccessToken(secret, token string) (*Claims, error) {
	parsed, err := jwt.ParseWithClaims(token, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	claims, ok := parsed.Claims.(*Claims)
	if !ok || !parsed.Valid {
		return nil, errors.New("invalid token")
	}
	return claims, nil
}

// Refresh tokens are opaque random values; only a SHA-256 hash is persisted
// (tenant-schema refresh_tokens table), and they rotate on every use.
func NewRefreshToken() (raw string, hash string, err error) {
	buf := make([]byte, 32)
	if _, err = rand.Read(buf); err != nil {
		return "", "", err
	}
	raw = hex.EncodeToString(buf)
	return raw, HashRefreshToken(raw), nil
}

func HashRefreshToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}
