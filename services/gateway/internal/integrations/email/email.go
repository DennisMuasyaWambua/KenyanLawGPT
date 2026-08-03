package email

import (
	"context"
	"fmt"
	"net/smtp"

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

type smtpProvider struct{ cfg *config.Config }

func (p *smtpProvider) Send(_ context.Context, to, subject, body string) error {
	addr := p.cfg.SMTPHost + ":" + p.cfg.SMTPPort
	msg := []byte(fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n%s\r\n",
		p.cfg.EmailFrom, to, subject, body))
	var auth smtp.Auth
	if p.cfg.SMTPUser != "" {
		auth = smtp.PlainAuth("", p.cfg.SMTPUser, p.cfg.SMTPPass, p.cfg.SMTPHost)
	}
	return smtp.SendMail(addr, auth, p.cfg.EmailFrom, []string{to}, msg)
}

type logProvider struct{}

func (p *logProvider) Send(ctx context.Context, to, subject, body string) error {
	logging.L(ctx).Info("email (log-only mode)", "to", to, "subject", subject, "body", body)
	return nil
}
