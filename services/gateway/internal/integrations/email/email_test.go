package email

import (
	"strings"
	"testing"
	"time"
)

func TestBuildMessageEncodesSubjectAndStripsInjection(t *testing.T) {
	msg := string(buildMessage("Firm <no-reply@firm.co.ke>", "a@b.co", "Meeting notes — x\r\nBcc: evil@x.com", "line1\nline2", "mail.firm.co.ke",
		time.Date(2026, 10, 8, 9, 0, 0, 0, time.UTC)))
	if !strings.Contains(msg, "Subject: =?utf-8?q?") {
		t.Errorf("non-ASCII subject must be RFC 2047 encoded:\n%s", msg)
	}
	if strings.Contains(msg, "\r\nBcc:") {
		t.Errorf("CRLF in subject must not inject a header:\n%s", msg)
	}
	for _, h := range []string{"Date: ", "Message-ID: <", "MIME-Version: 1.0"} {
		if !strings.Contains(msg, h) {
			t.Errorf("missing header %q", h)
		}
	}
	if !strings.Contains(msg, "line1\r\nline2\r\n") {
		t.Errorf("body must use CRLF line endings:\n%q", msg)
	}
}
