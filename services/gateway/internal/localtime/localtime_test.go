package localtime

import (
	"testing"
	"time"
)

func TestFormatUsesEAT(t *testing.T) {
	utc := time.Date(2026, 10, 8, 9, 0, 0, 0, time.UTC)
	if got, want := Format(utc, ""), "Thu 08 Oct 2026 12:00"; got != want {
		t.Errorf("Format = %q, want %q", got, want)
	}
}
