package service

import (
	"context"
	"crypto/rand"
	"errors"
	"regexp"
	"strings"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/repository"
)

var (
	ErrBadWebhook = errors.New("webhook must look like https://hooks.slack.com/services/...")
	ErrNoWebhook  = errors.New("no slack webhook configured")
	ErrBadCode    = errors.New("that link code is invalid or expired: create a new one on the Integrations page")
)

var (
	slackWebhookPattern = regexp.MustCompile(`^https://hooks\.slack\.com/(services|workflows)/[A-Za-z0-9/_-]{8,200}$`)
	// DEV_MODE only: lets e2e tests point a "webhook" at a local capture server.
	loopbackWebhookPattern = regexp.MustCompile(`^http://(127\.0\.0\.1|localhost)(:[0-9]{2,5})?/[A-Za-z0-9/_-]{0,200}$`)
)

// SlackSettingsService owns the per-user Slack configuration: incoming
// webhook (encrypted), default repo and the Slack-user link.
type SlackSettingsService struct {
	store         SlackStore
	cipher        *crypt.Cipher
	notifier      *SlackNotifier
	allowLoopback bool
	now           func() time.Time
}

func NewSlackSettingsService(store SlackStore, cipher *crypt.Cipher, notifier *SlackNotifier, allowLoopback bool) *SlackSettingsService {
	return &SlackSettingsService{store: store, cipher: cipher, notifier: notifier, allowLoopback: allowLoopback, now: time.Now}
}

// ValidateWebhook accepts only Slack incoming-webhook URLs (SSRF guard: the
// backend will POST to whatever is stored here).
func (s *SlackSettingsService) ValidateWebhook(u string) error {
	if slackWebhookPattern.MatchString(u) || (s.allowLoopback && loopbackWebhookPattern.MatchString(u)) {
		return nil
	}
	return ErrBadWebhook
}

// MaskWebhook never reveals more than the last 4 characters.
func MaskWebhook(u string) string {
	if len(u) < 8 {
		return "…"
	}
	return "https://hooks.slack.com/…" + u[len(u)-4:]
}

type SlackSettingsView struct {
	Configured       bool   `json:"configured"`
	WebhookURLMasked string `json:"webhookUrlMasked"`
	Linked           bool   `json:"linked"`
	DefaultRepo      string `json:"defaultRepo"`
	AppConfigured    bool   `json:"appConfigured"`
}

func (s *SlackSettingsService) View(ctx context.Context, userID string, appConfigured bool) (*SlackSettingsView, error) {
	v := &SlackSettingsView{AppConfigured: appConfigured}
	set, err := s.store.GetSettings(ctx, userID)
	if err != nil && !errors.Is(err, repository.ErrNotFound) {
		return nil, err
	}
	if set != nil {
		v.DefaultRepo = set.DefaultRepo
		if set.EncWebhook != "" {
			if hook, err := s.cipher.Open(set.EncWebhook); err == nil {
				v.Configured, v.WebhookURLMasked = true, MaskWebhook(hook)
			}
		}
	}
	if _, err := s.store.SlackForUser(ctx, userID); err == nil {
		v.Linked = true
	}
	return v, nil
}

func (s *SlackSettingsService) settings(ctx context.Context, userID string) (*models.SlackSettings, error) {
	set, err := s.store.GetSettings(ctx, userID)
	if errors.Is(err, repository.ErrNotFound) {
		return &models.SlackSettings{UserID: userID}, nil
	}
	return set, err
}

func (s *SlackSettingsService) SetWebhook(ctx context.Context, userID, webhook string) error {
	webhook = strings.TrimSpace(webhook)
	if err := s.ValidateWebhook(webhook); err != nil {
		return err
	}
	enc, err := s.cipher.Seal(webhook)
	if err != nil {
		return err
	}
	set, err := s.settings(ctx, userID)
	if err != nil {
		return err
	}
	set.EncWebhook = enc
	return s.store.PutSettings(ctx, set)
}

func (s *SlackSettingsService) ClearWebhook(ctx context.Context, userID string) error {
	return s.store.DeleteWebhook(ctx, userID)
}

// Webhook returns the decrypted webhook or "" (used when posting completions).
func (s *SlackSettingsService) Webhook(ctx context.Context, userID string) string {
	set, err := s.store.GetSettings(ctx, userID)
	if err != nil || set.EncWebhook == "" {
		return ""
	}
	hook, err := s.cipher.Open(set.EncWebhook)
	if err != nil {
		return ""
	}
	return hook
}

// Test sends a test card to the user's webhook.
func (s *SlackSettingsService) Test(ctx context.Context, userID string) error {
	hook := s.Webhook(ctx, userID)
	if hook == "" {
		return ErrNoWebhook
	}
	_, err := s.notifier.PostTo(ctx, hook, map[string]any{
		"text": "PatchLoop test message: Slack notifications are working.",
		"blocks": []map[string]any{
			{"type": "header", "text": map[string]any{"type": "plain_text", "text": "PatchLoop is connected"}},
			{"type": "section", "text": map[string]any{"type": "mrkdwn", "text": "You will get a message here when a fix is ready. Agents never merge: a human reviews every pull request."}},
		},
	})
	return err
}

func (s *SlackSettingsService) DefaultRepo(ctx context.Context, userID string) string {
	set, err := s.store.GetSettings(ctx, userID)
	if err != nil {
		return ""
	}
	return set.DefaultRepo
}

func (s *SlackSettingsService) SetDefaultRepo(ctx context.Context, userID, repo string) error {
	set, err := s.settings(ctx, userID)
	if err != nil {
		return err
	}
	set.DefaultRepo = repo
	return s.store.PutSettings(ctx, set)
}

const codeAlphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

// NewLinkCode creates a one-time code valid for 10 minutes.
func (s *SlackSettingsService) NewLinkCode(ctx context.Context, userID string) (string, time.Time, error) {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		return "", time.Time{}, err
	}
	for i := range b {
		b[i] = codeAlphabet[int(b[i])%len(codeAlphabet)]
	}
	exp := s.now().Add(10 * time.Minute).UTC()
	code := string(b)
	if err := s.store.PutCode(ctx, &models.SlackLinkCode{Code: code, UserID: userID, ExpiresAt: exp}); err != nil {
		return "", time.Time{}, err
	}
	return code, exp, nil
}

// Link consumes a code and ties slackUserID to its PatchLoop user.
func (s *SlackSettingsService) Link(ctx context.Context, slackUserID, code string) error {
	userID, err := s.store.TakeCode(ctx, strings.ToUpper(strings.TrimSpace(code)), s.now())
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return ErrBadCode
		}
		return err
	}
	return s.store.PutLink(ctx, &models.SlackLink{SlackUserID: slackUserID, UserID: userID})
}

// UserFor maps a Slack user id to a PatchLoop user ("" when unlinked).
func (s *SlackSettingsService) UserFor(ctx context.Context, slackUserID string) string {
	u, err := s.store.UserForSlack(ctx, slackUserID)
	if err != nil {
		return ""
	}
	return u
}
