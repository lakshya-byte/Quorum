package service

import (
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/resend/resend-go/v2"
)

type Mailer struct {
	client *resend.Client // nil when no API key (dev mode only)
	from   string

	// devMode keeps the last OTP per email in memory so integration tests
	// can read it through /internal/dev/otp. Never enabled by default.
	devMode bool
	mu      sync.Mutex
	lastOTP map[string]string
}

func NewMailer(apiKey, from string) *Mailer {
	return NewMailerWithOptions(apiKey, from, false)
}

// NewMailerWithOptions creates a mailer. In dev mode an empty apiKey is
// allowed: emails are not sent, only the code is kept in memory.
func NewMailerWithOptions(apiKey, from string, devMode bool) *Mailer {
	m := &Mailer{from: from, devMode: devMode}
	if apiKey != "" {
		m.client = resend.NewClient(apiKey)
	}
	if devMode {
		m.lastOTP = map[string]string{}
	}
	return m
}

// LastOTP returns the most recent code sent to email (dev mode only).
func (m *Mailer) LastOTP(email string) (string, bool) {
	if !m.devMode {
		return "", false
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	code, ok := m.lastOTP[strings.ToLower(email)]
	return code, ok
}

func (m *Mailer) SendOTPEmail(to, code string) error {
	if m.devMode {
		m.mu.Lock()
		m.lastOTP[strings.ToLower(to)] = code
		m.mu.Unlock()
		if m.client == nil {
			return nil
		}
	}
	if m.client == nil {
		return errors.New("mailer not configured")
	}

	html := fmt.Sprintf(`
		<div style="font-family: sans-serif; max-width: 420px; margin: 0 auto;">
			<h2 style="color: #10b981;">Verify your PatchLoop account</h2>
			<p>Your verification code is:</p>
			<p style="font-size: 32px; font-weight: 700; letter-spacing: 6px;">%s</p>
			<p style="color: #666; font-size: 13px;">This code expires in 10 minutes. If you didn't request this, you can ignore this email.</p>
		</div>
	`, code)

	params := &resend.SendEmailRequest{
		From:    m.from,
		To:      []string{to},
		Subject: "Your PatchLoop verification code",
		Html:    html,
	}

	_, err := m.client.Emails.Send(params)
	return err
}
