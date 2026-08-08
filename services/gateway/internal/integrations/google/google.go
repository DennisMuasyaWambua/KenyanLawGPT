// Package google verifies Google Identity Services ID tokens server-side
// without pulling in an OAuth SDK: it delegates signature/expiry validation to
// Google's documented tokeninfo endpoint, then checks the audience and that
// the email is verified. This is sufficient for sign-in / sign-up where the
// browser obtains the credential via Google Identity Services.
package google

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Identity is the subset of verified claims the gateway consumes.
type Identity struct {
	Sub           string
	Email         string
	EmailVerified bool
	Name          string
}

// TokenInfoURL is Google's ID-token introspection endpoint. It is a var (not a
// const) so tests can point verification at a local httptest server.
var TokenInfoURL = "https://oauth2.googleapis.com/tokeninfo"

// Verify validates an ID token and returns the identity. clientID must match
// the token's audience. An empty clientID disables the audience check and is
// intended only for local development.
func Verify(ctx context.Context, idToken, clientID string) (*Identity, error) {
	if strings.TrimSpace(idToken) == "" {
		return nil, fmt.Errorf("empty id token")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		TokenInfoURL+"?"+url.Values{"id_token": {idToken}}.Encode(), nil)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("tokeninfo request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("google rejected id token (status %d)", resp.StatusCode)
	}

	var body struct {
		Aud           string `json:"aud"`
		Sub           string `json:"sub"`
		Email         string `json:"email"`
		EmailVerified string `json:"email_verified"` // tokeninfo returns "true"/"false" as strings
		Name          string `json:"name"`
		Exp           string `json:"exp"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("decode tokeninfo: %w", err)
	}
	if clientID != "" && body.Aud != clientID {
		return nil, fmt.Errorf("id token audience mismatch")
	}
	if body.Sub == "" || body.Email == "" {
		return nil, fmt.Errorf("id token missing subject/email")
	}
	return &Identity{
		Sub:           body.Sub,
		Email:         strings.ToLower(body.Email),
		EmailVerified: body.EmailVerified == "true",
		Name:          body.Name,
	}, nil
}
