package auth

import (
	"crypto/rand"
	"math/big"
	"strings"

	"golang.org/x/crypto/bcrypt"
)

func HashPassword(pw string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(pw), bcrypt.DefaultCost)
	return string(b), err
}

func CheckPassword(hash, pw string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(pw)) == nil
}

// Look-alike characters (0/O, 1/l/I) are left out: temporary passwords are
// read off an email and typed by hand.
const tempAlphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"

// NewTemporaryPassword returns a random one-time password like "Kp7m-Qx4r-Ze9t"
// (~70 bits of entropy) for staff added by a firm admin.
func NewTemporaryPassword() (string, error) {
	groups := make([]string, 3)
	max := big.NewInt(int64(len(tempAlphabet)))
	for g := range groups {
		var b strings.Builder
		for i := 0; i < 4; i++ {
			n, err := rand.Int(rand.Reader, max)
			if err != nil {
				return "", err
			}
			b.WriteByte(tempAlphabet[n.Int64()])
		}
		groups[g] = b.String()
	}
	return strings.Join(groups, "-"), nil
}
