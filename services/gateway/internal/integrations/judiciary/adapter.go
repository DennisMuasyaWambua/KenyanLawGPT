package judiciary

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/wakiliai/gateway/internal/config"
)

// The Kenya Judiciary has no stable public API, so case-status lookup is a
// pluggable Adapter. Callers depend only on this interface; implementations
// can be swapped without touching handler code.
type CaseStatus struct {
	CaseNumber  string    `json:"case_number"`
	Court       string    `json:"court"`
	Status      string    `json:"status"`
	NextHearing string    `json:"next_hearing"`
	LastOrder   string    `json:"last_order"`
	RetrievedAt time.Time `json:"retrieved_at"`
	FromCache   bool      `json:"from_cache"`
}

type Adapter interface {
	Lookup(ctx context.Context, caseNumber string) (*CaseStatus, error)
}

// New picks the concrete implementation: a scraper against the configured
// portal when JUDICIARY_BASE_URL is set, otherwise a deterministic mock so
// the feature is demoable offline.
func New(cfg *config.Config, rdb *redis.Client) Adapter {
	if cfg.JudiciaryBaseURL != "" {
		return &PortalAdapter{base: cfg.JudiciaryBaseURL, http: &http.Client{Timeout: 20 * time.Second}, rdb: rdb}
	}
	return &MockAdapter{}
}

// PortalAdapter scrapes/queries the e-filing case-search endpoint and caches
// the last-known status in Redis; when the source is down it degrades
// gracefully to the cached value with FromCache=true.
type PortalAdapter struct {
	base string
	http *http.Client
	rdb  *redis.Client
}

func cacheKey(caseNumber string) string {
	sum := sha256.Sum256([]byte(caseNumber))
	return "judiciary:" + hex.EncodeToString(sum[:8])
}

func (p *PortalAdapter) Lookup(ctx context.Context, caseNumber string) (*CaseStatus, error) {
	status, err := p.fetch(ctx, caseNumber)
	if err == nil {
		if buf, mErr := json.Marshal(status); mErr == nil {
			p.rdb.Set(ctx, cacheKey(caseNumber), buf, 24*time.Hour)
		}
		return status, nil
	}
	// Source unavailable — serve last-known-status if we have one.
	if raw, cErr := p.rdb.Get(ctx, cacheKey(caseNumber)).Bytes(); cErr == nil {
		var cached CaseStatus
		if json.Unmarshal(raw, &cached) == nil {
			cached.FromCache = true
			return &cached, nil
		}
	}
	return nil, fmt.Errorf("judiciary lookup failed and no cached status: %w", err)
}

func (p *PortalAdapter) fetch(ctx context.Context, caseNumber string) (*CaseStatus, error) {
	u := p.base + "/case-search?case_number=" + url.QueryEscape(caseNumber)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	resp, err := p.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("portal status %d", resp.StatusCode)
	}
	var body struct {
		CaseNumber  string `json:"case_number"`
		Court       string `json:"court"`
		Status      string `json:"status"`
		NextHearing string `json:"next_hearing"`
		LastOrder   string `json:"last_order"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	return &CaseStatus{
		CaseNumber:  body.CaseNumber,
		Court:       body.Court,
		Status:      body.Status,
		NextHearing: body.NextHearing,
		LastOrder:   body.LastOrder,
		RetrievedAt: time.Now(),
	}, nil
}

// MockAdapter returns deterministic pseudo-status derived from the case
// number hash — stable across calls, clearly marked as mock data.
type MockAdapter struct{}

var mockStatuses = []string{"Pending Directions", "Hearing Scheduled", "Judgment Reserved", "Part Heard", "Mention"}

func (m *MockAdapter) Lookup(_ context.Context, caseNumber string) (*CaseStatus, error) {
	sum := sha256.Sum256([]byte(caseNumber))
	idx := int(sum[0]) % len(mockStatuses)
	next := time.Now().AddDate(0, 0, 7+int(sum[1])%21)
	return &CaseStatus{
		CaseNumber:  caseNumber,
		Court:       "Milimani Law Courts (mock)",
		Status:      mockStatuses[idx] + " [MOCK — set JUDICIARY_BASE_URL for live lookups]",
		NextHearing: next.Format("2006-01-02"),
		LastOrder:   "Parties to file submissions within 14 days",
		RetrievedAt: time.Now(),
	}, nil
}
