package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Platform super-admin tokens are a SEPARATE token type from tenant access
// tokens: a distinct issuer and claim shape. A tenant token can never satisfy
// ParseAdminToken (wrong issuer), and an admin token can never satisfy the
// tenant Auth middleware (it carries no tenant id). Same signing secret.
const adminIssuer = "wakiliai-admin"

type AdminClaims struct {
	AdminID string `json:"aid"`
	Email   string `json:"email"`
	jwt.RegisteredClaims
}

func IssueAdminToken(secret, adminID, email string, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := &AdminClaims{
		AdminID: adminID,
		Email:   email,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    adminIssuer,
			Subject:   adminID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func ParseAdminToken(secret, token string) (*AdminClaims, error) {
	parsed, err := jwt.ParseWithClaims(token, &AdminClaims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	claims, ok := parsed.Claims.(*AdminClaims)
	if !ok || !parsed.Valid || claims.Issuer != adminIssuer {
		return nil, errors.New("invalid admin token")
	}
	return claims, nil
}
