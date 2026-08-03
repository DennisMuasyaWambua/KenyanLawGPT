package mpesa

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/wakiliai/gateway/internal/config"
)

// Daraja implements Safaricom's M-Pesa Daraja API: OAuth token caching,
// STK push (Lipa na M-Pesa Online), and transaction status query for the
// reconciliation job.
type Daraja struct {
	cfg  *config.Config
	http *http.Client

	mu       sync.Mutex
	token    string
	tokenExp time.Time
}

func New(cfg *config.Config) *Daraja {
	return &Daraja{cfg: cfg, http: &http.Client{Timeout: 30 * time.Second}}
}

func (d *Daraja) Configured() bool {
	return d.cfg.DarajaConsumerKey != "" && d.cfg.DarajaConsumerSecret != "" && d.cfg.DarajaPasskey != ""
}

func (d *Daraja) accessToken(ctx context.Context) (string, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.token != "" && time.Now().Before(d.tokenExp) {
		return d.token, nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		d.cfg.DarajaBaseURL+"/oauth/v1/generate?grant_type=client_credentials", nil)
	if err != nil {
		return "", err
	}
	req.SetBasicAuth(d.cfg.DarajaConsumerKey, d.cfg.DarajaConsumerSecret)
	resp, err := d.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("daraja oauth: status %d", resp.StatusCode)
	}
	var body struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   string `json:"expires_in"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return "", err
	}
	d.token = body.AccessToken
	d.tokenExp = time.Now().Add(50 * time.Minute)
	return d.token, nil
}

type STKResponse struct {
	MerchantRequestID   string `json:"MerchantRequestID"`
	CheckoutRequestID   string `json:"CheckoutRequestID"`
	ResponseCode        string `json:"ResponseCode"`
	ResponseDescription string `json:"ResponseDescription"`
	CustomerMessage     string `json:"CustomerMessage"`
}

func (d *Daraja) password(ts string) string {
	return base64.StdEncoding.EncodeToString([]byte(d.cfg.DarajaShortCode + d.cfg.DarajaPasskey + ts))
}

// STKPush initiates a Lipa na M-Pesa Online payment prompt on the payer's
// phone. amount is whole KES (Daraja takes integers). callbackURL overrides
// the configured one so callers can attach tenant routing info.
func (d *Daraja) STKPush(ctx context.Context, phone string, amount int64, accountRef, description, callbackURL string) (*STKResponse, error) {
	token, err := d.accessToken(ctx)
	if err != nil {
		return nil, err
	}
	if callbackURL == "" {
		callbackURL = d.cfg.DarajaCallbackURL
	}
	ts := time.Now().Format("20060102150405")
	payload := map[string]any{
		"BusinessShortCode": d.cfg.DarajaShortCode,
		"Password":          d.password(ts),
		"Timestamp":         ts,
		"TransactionType":   "CustomerPayBillOnline",
		"Amount":            amount,
		"PartyA":            phone,
		"PartyB":            d.cfg.DarajaShortCode,
		"PhoneNumber":       phone,
		"CallBackURL":       callbackURL,
		"AccountReference":  accountRef,
		"TransactionDesc":   description,
	}
	return d.post(ctx, token, "/mpesa/stkpush/v1/processrequest", payload)
}

// QueryStatus checks a pending STK push (reconciliation path).
func (d *Daraja) QueryStatus(ctx context.Context, checkoutRequestID string) (*STKResponse, error) {
	token, err := d.accessToken(ctx)
	if err != nil {
		return nil, err
	}
	ts := time.Now().Format("20060102150405")
	payload := map[string]any{
		"BusinessShortCode": d.cfg.DarajaShortCode,
		"Password":          d.password(ts),
		"Timestamp":         ts,
		"CheckoutRequestID": checkoutRequestID,
	}
	return d.post(ctx, token, "/mpesa/stkpushquery/v1/query", payload)
}

func (d *Daraja) post(ctx context.Context, token, path string, payload map[string]any) (*STKResponse, error) {
	buf, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, d.cfg.DarajaBaseURL+path, bytes.NewReader(buf))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := d.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out STKResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("daraja %s: decode: %w", path, err)
	}
	return &out, nil
}

// --- Callback payload (webhook) ---

type CallbackEnvelope struct {
	Body struct {
		StkCallback struct {
			MerchantRequestID string `json:"MerchantRequestID"`
			CheckoutRequestID string `json:"CheckoutRequestID"`
			ResultCode        int    `json:"ResultCode"`
			ResultDesc        string `json:"ResultDesc"`
			CallbackMetadata  struct {
				Item []struct {
					Name  string `json:"Name"`
					Value any    `json:"Value"`
				} `json:"Item"`
			} `json:"CallbackMetadata"`
		} `json:"stkCallback"`
	} `json:"Body"`
}

// Receipt extracts the MpesaReceiptNumber from callback metadata.
func (e *CallbackEnvelope) Receipt() string {
	for _, item := range e.Body.StkCallback.CallbackMetadata.Item {
		if item.Name == "MpesaReceiptNumber" {
			if s, ok := item.Value.(string); ok {
				return s
			}
		}
	}
	return ""
}
