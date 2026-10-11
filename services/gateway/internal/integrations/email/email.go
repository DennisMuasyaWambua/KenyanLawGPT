package email

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"fmt"
	"mime"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/logging"
)

// Provider abstracts transactional email (same pattern as LLMProvider on the
// Python side): SMTP when configured, log-only in dev.
type Provider interface {
	Send(ctx context.Context, to, subject, body string) error
}

func New(cfg *config.Config) Provider {
	if cfg.SMTPHost != "" {
		return &smtpProvider{cfg: cfg}
	}
	return &logProvider{}
}

// smtpTimeout bounds the whole exchange. net/smtp.SendMail has no timeouts, so
// an unreachable relay would otherwise hang the request (or the reminder loop)
// indefinitely.
const smtpTimeout = 20 * time.Second

type smtpProvider struct{ cfg *config.Config }

// sanitizeHeader strips CR/LF so user-influenced values (subjects built from
// filenames, recipient addresses) cannot inject extra headers.
func sanitizeHeader(s string) string {
	return strings.NewReplacer("\r", " ", "\n", " ").Replace(s)
}

func randomID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// buildMessage renders an RFC 5322 message. The subject is RFC 2047-encoded
// (so non-ASCII such as "—" survives) and Date/Message-ID are set, which many
// relays require before they will accept or deliver a message.
func buildMessage(from, to, subject, body, host string, now time.Time) []byte {
	var b strings.Builder
	b.WriteString("From: " + sanitizeHeader(from) + "\r\n")
	b.WriteString("To: " + sanitizeHeader(to) + "\r\n")
	b.WriteString("Subject: " + mime.QEncoding.Encode("utf-8", sanitizeHeader(subject)) + "\r\n")
	b.WriteString("Date: " + now.Format(time.RFC1123Z) + "\r\n")
	b.WriteString("Message-ID: <" + randomID() + "@" + host + ">\r\n")
	b.WriteString("MIME-Version: 1.0\r\n")
	b.WriteString("Content-Type: text/plain; charset=utf-8\r\n")
	b.WriteString("Content-Transfer-Encoding: 8bit\r\n\r\n")
	// Normalise line endings to CRLF as SMTP requires.
	body = strings.ReplaceAll(strings.ReplaceAll(body, "\r\n", "\n"), "\n", "\r\n")
	b.WriteString(body + "\r\n")
	return []byte(b.String())
}

func (p *smtpProvider) Send(ctx context.Context, to, subject, body string) error {
	// EMAIL_FROM may be "Name <addr>"; the SMTP envelope needs the bare address.
	envFrom := p.cfg.EmailFrom
	if a, err := mail.ParseAddress(p.cfg.EmailFrom); err == nil {
		envFrom = a.Address
	}
	rcpt, err := mail.ParseAddress(to)
	if err != nil {
		return fmt.Errorf("invalid recipient address %q: %w", to, err)
	}
	msg := buildMessage(p.cfg.EmailFrom, rcpt.Address, subject, body, p.cfg.SMTPHost, time.Now())

	ctx, cancel := context.WithTimeout(ctx, smtpTimeout)
	defer cancel()
	addr := net.JoinHostPort(p.cfg.SMTPHost, p.cfg.SMTPPort)
	dialer := &net.Dialer{Timeout: smtpTimeout}
	tlsCfg := &tls.Config{ServerName: p.cfg.SMTPHost, MinVersion: tls.VersionTLS12}

	var conn net.Conn
	if p.cfg.SMTPPort == "465" { // implicit TLS (SMTPS) — SendMail cannot speak this
		conn, err = (&tls.Dialer{NetDialer: dialer, Config: tlsCfg}).DialContext(ctx, "tcp", addr)
	} else {
		conn, err = dialer.DialContext(ctx, "tcp", addr)
	}
	if err != nil {
		return fmt.Errorf("smtp connect %s: %w", addr, err)
	}
	if dl, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(dl)
	}
	c, err := smtp.NewClient(conn, p.cfg.SMTPHost)
	if err != nil {
		conn.Close()
		return fmt.Errorf("smtp handshake: %w", err)
	}
	defer c.Close()

	if p.cfg.SMTPPort != "465" {
		if ok, _ := c.Extension("STARTTLS"); ok {
			if err := c.StartTLS(tlsCfg); err != nil {
				return fmt.Errorf("smtp starttls: %w", err)
			}
		}
	}
	if p.cfg.SMTPUser != "" {
		auth := smtp.PlainAuth("", p.cfg.SMTPUser, p.cfg.SMTPPass, p.cfg.SMTPHost)
		if err := c.Auth(auth); err != nil {
			return fmt.Errorf("smtp auth: %w", err)
		}
	}
	if err := c.Mail(envFrom); err != nil {
		return fmt.Errorf("smtp MAIL FROM: %w", err)
	}
	if err := c.Rcpt(rcpt.Address); err != nil {
		return fmt.Errorf("smtp RCPT TO: %w", err)
	}
	w, err := c.Data()
	if err != nil {
		return fmt.Errorf("smtp DATA: %w", err)
	}
	if _, err := w.Write(msg); err != nil {
		return err
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("smtp send: %w", err)
	}
	return c.Quit()
}

// Delivers reports whether p actually sends mail. The dev log-only provider
// doesn't, so callers can surface credentials/links on screen instead.
func Delivers(p Provider) bool {
	_, logOnly := p.(*logProvider)
	return !logOnly
}

type logProvider struct{}

func (p *logProvider) Send(ctx context.Context, to, subject, body string) error {
	logging.L(ctx).Info("email (log-only mode)", "to", to, "subject", subject, "body", body)
	return nil
}
