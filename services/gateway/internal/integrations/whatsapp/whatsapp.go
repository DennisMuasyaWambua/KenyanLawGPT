// Package whatsapp sends business-initiated reminders via the Meta WhatsApp
// Cloud API. Messages outside the 24h customer-service window MUST use a
// pre-approved template, so Send delivers the configured template with the
// reminder text filled into body parameter {{1}}.
package whatsapp

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/wakiliai/gateway/internal/config"
)

type Client struct {
	baseURL  string
	version  string
	phoneID  string
	token    string
	template string
	lang     string
	http     *http.Client
}

func New(cfg *config.Config) *Client {
	return &Client{
		baseURL:  cfg.WhatsAppBaseURL,
		version:  cfg.WhatsAppAPIVersion,
		phoneID:  cfg.WhatsAppPhoneID,
		token:    cfg.WhatsAppToken,
		template: cfg.WhatsAppTemplate,
		lang:     cfg.WhatsAppLang,
		http:     &http.Client{Timeout: 10 * time.Second},
	}
}

// Enabled reports whether the provider has enough config to send. When false,
// callers fall back to SMS.
func (c *Client) Enabled() bool {
	return c != nil && c.phoneID != "" && c.token != "" && c.template != ""
}

// Send delivers `text` to `to` using the configured approved template.
func (c *Client) Send(ctx context.Context, to, text string) error {
	if !c.Enabled() {
		return fmt.Errorf("whatsapp not configured")
	}
	num := digitsOnly(to)
	if len(num) < 9 {
		return fmt.Errorf("invalid recipient phone")
	}
	payload := map[string]any{
		"messaging_product": "whatsapp",
		"to":                num,
		"type":              "template",
		"template": map[string]any{
			"name":     c.template,
			"language": map[string]string{"code": c.lang},
			"components": []any{map[string]any{
				"type":       "body",
				"parameters": []any{map[string]string{"type": "text", "text": text}},
			}},
		},
	}
	buf, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/%s/%s/messages", strings.TrimRight(c.baseURL, "/"), c.version, c.phoneID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(buf))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("whatsapp api %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
}

// digitsOnly strips '+', spaces and punctuation — Meta expects the number in
// international format with no leading '+'.
func digitsOnly(phone string) string {
	var sb strings.Builder
	for _, r := range phone {
		if r >= '0' && r <= '9' {
			sb.WriteRune(r)
		}
	}
	return sb.String()
}
