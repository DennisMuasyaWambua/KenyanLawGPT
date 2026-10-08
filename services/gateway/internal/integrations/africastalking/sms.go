package africastalking

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/logging"
)

// Client sends SMS through Africa's Talking. With no credentials configured
// (local dev) it degrades to log-only mode so reminder flows stay testable.
type Client struct {
	cfg  *config.Config
	http *http.Client
}

func New(cfg *config.Config) *Client {
	return &Client{cfg: cfg, http: &http.Client{Timeout: 20 * time.Second}}
}

func (c *Client) Configured() bool { return c.cfg.ATUsername != "" && c.cfg.ATAPIKey != "" }

type SendResult struct {
	MessageID string
	Status    string
}

// NormalizePhone converts common Kenyan formats (0712…, 712…, 254712…,
// +254 712 …) to the E.164 form Africa's Talking requires. Numbers that already
// carry another country code are kept as-is (digits with a leading "+").
func NormalizePhone(raw string) string {
	var digits strings.Builder
	for _, r := range raw {
		if r >= '0' && r <= '9' {
			digits.WriteRune(r)
		}
	}
	d := digits.String()
	switch {
	case d == "":
		return ""
	case strings.HasPrefix(d, "254"):
		return "+" + d
	case strings.HasPrefix(d, "0") && len(d) == 10:
		return "+254" + d[1:]
	case len(d) == 9 && (d[0] == '7' || d[0] == '1'):
		return "+254" + d
	}
	return "+" + d
}

// atSuccess reports whether an AT recipient statusCode means the message was
// accepted: 100 Processed, 101 Sent, 102 Queued. Everything else is a failure
// (InvalidPhoneNumber, InsufficientBalance, UserInBlacklist, …).
func atSuccess(code int) bool { return code >= 100 && code <= 102 }

func (c *Client) Send(ctx context.Context, to, message string) (*SendResult, error) {
	if !c.Configured() {
		logging.L(ctx).Info("SMS (log-only mode)", "to", to, "message", message)
		return &SendResult{MessageID: "dev-" + fmt.Sprint(time.Now().UnixNano()), Status: "sent"}, nil
	}
	phone := NormalizePhone(to)
	if phone == "" {
		return nil, fmt.Errorf("africastalking: invalid phone number %q", to)
	}
	form := url.Values{}
	form.Set("username", c.cfg.ATUsername)
	form.Set("to", phone)
	form.Set("message", message)
	if c.cfg.ATSenderID != "" {
		form.Set("from", c.cfg.ATSenderID)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.cfg.ATBaseURL+"/version1/messaging", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("apiKey", c.cfg.ATAPIKey)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("africastalking: http %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var body struct {
		SMSMessageData struct {
			Message    string `json:"Message"`
			Recipients []struct {
				StatusCode int    `json:"statusCode"`
				Status     string `json:"status"`
				MessageID  string `json:"messageId"`
			} `json:"Recipients"`
		} `json:"SMSMessageData"`
	}
	if err := json.Unmarshal(raw, &body); err != nil {
		return nil, fmt.Errorf("africastalking: unreadable response: %w", err)
	}
	if len(body.SMSMessageData.Recipients) == 0 {
		return nil, fmt.Errorf("africastalking: no recipients in response (%s)", body.SMSMessageData.Message)
	}
	r := body.SMSMessageData.Recipients[0]
	if !atSuccess(r.StatusCode) {
		return nil, fmt.Errorf("africastalking: %s (code %d)", r.Status, r.StatusCode)
	}
	return &SendResult{MessageID: r.MessageID, Status: "sent"}, nil
}
