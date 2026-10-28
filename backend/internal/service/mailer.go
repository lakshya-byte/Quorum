package service

import (
	"fmt"

	"github.com/resend/resend-go/v2"
)

type Mailer struct {
	client *resend.Client
	from   string
}

func NewMailer(apiKey, from string) *Mailer {
	return &Mailer{client: resend.NewClient(apiKey), from: from}
}

func (m *Mailer) SendOTPEmail(to, code string) error {
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
