package africastalking

import (
	"context"
	"encoding/json"
	"fmt"
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

func (c *Client) Send(ctx context.Context, to, message string) (*SendResult, error) {
	if !c.Configured() {
		logging.L(ctx).Info("SMS (log-only mode)", "to", to, "message", message)
		return &SendResult{MessageID: "dev-" + fmt.Sprint(time.Now().UnixNano()), Status: "sent"}, nil
	}
	form := url.Values{}
	form.Set("username", c.cfg.ATUsername)
	form.Set("to", to)
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
	var body struct {
		SMSMessageData struct {
			Recipients []struct {
				Status    string `json:"status"`
				MessageID string `json:"messageId"`
			} `json:"Recipients"`
		} `json:"SMSMessageData"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	if len(body.SMSMessageData.Recipients) == 0 {
		return nil, fmt.Errorf("africastalking: no recipients in response")
	}
	r := body.SMSMessageData.Recipients[0]
	return &SendResult{MessageID: r.MessageID, Status: strings.ToLower(r.Status)}, nil
}
