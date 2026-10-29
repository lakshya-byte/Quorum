package handler

import (
	"io"
	"log/slog"
	"net/http"
	"net/url"

	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

const maxWebhookBody = 2 << 20

// WebhookHandler serves the signature-protected public endpoints:
// POST /api/github/webhook and POST /slack/{commands,events,interactions}.
type WebhookHandler struct {
	gh    *service.GitHubWebhook
	slack *service.SlackApp
}

func NewWebhookHandler(gh *service.GitHubWebhook, slack *service.SlackApp) *WebhookHandler {
	return &WebhookHandler{gh: gh, slack: slack}
}

func readBody(c *gin.Context) ([]byte, bool) {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxWebhookBody)
	raw, err := io.ReadAll(c.Request.Body)
	if err != nil {
		apiError(c, http.StatusRequestEntityTooLarge, "bad_request", "request body too large")
		return nil, false
	}
	return raw, true
}

// GitHub: POST /api/github/webhook. Unsigned or badly signed deliveries are
// rejected; the signing secret must be configured or the endpoint is off.
func (h *WebhookHandler) GitHub(c *gin.Context) {
	if h.gh == nil || h.gh.Secret == "" {
		apiError(c, http.StatusServiceUnavailable, "not_configured", "github webhook not configured")
		return
	}
	raw, ok := readBody(c)
	if !ok {
		return
	}
	if !service.VerifyGitHubSignature(h.gh.Secret, raw, c.GetHeader("X-Hub-Signature-256")) {
		apiError(c, http.StatusUnauthorized, "unauthorized", "invalid signature")
		return
	}
	status, err := h.gh.Handle(c.Request.Context(), c.GetHeader("X-GitHub-Event"), c.GetHeader("X-GitHub-Delivery"), raw)
	if err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	c.JSON(http.StatusAccepted, gin.H{"status": status})
}

// slackBody reads and verifies a Slack request; it writes the error itself.
func (h *WebhookHandler) slackBody(c *gin.Context) ([]byte, bool) {
	if h.slack == nil || !h.slack.Enabled() {
		apiError(c, http.StatusServiceUnavailable, "not_configured", "slack app not configured")
		return nil, false
	}
	raw, ok := readBody(c)
	if !ok {
		return nil, false
	}
	if err := h.slack.Verify(c.GetHeader("X-Slack-Request-Timestamp"), c.GetHeader("X-Slack-Signature"), raw); err != nil {
		apiError(c, http.StatusUnauthorized, "unauthorized", err.Error())
		return nil, false
	}
	return raw, true
}

// SlackCommand: POST /slack/commands.
func (h *WebhookHandler) SlackCommand(c *gin.Context) {
	raw, ok := h.slackBody(c)
	if !ok {
		return
	}
	form, err := url.ParseQuery(string(raw))
	if err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", "bad form body")
		return
	}
	c.JSON(http.StatusOK, h.slack.HandleCommand(c.Request.Context(), service.SlackCommand{
		Command: form.Get("command"), Text: form.Get("text"), UserID: form.Get("user_id"), ChannelID: form.Get("channel_id"),
	}))
}

// SlackEvents: POST /slack/events.
func (h *WebhookHandler) SlackEvents(c *gin.Context) {
	raw, ok := h.slackBody(c)
	if !ok {
		return
	}
	challenge, err := h.slack.HandleEvent(c.Request.Context(), raw)
	if err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if challenge != "" {
		c.JSON(http.StatusOK, gin.H{"challenge": challenge})
		return
	}
	c.Status(http.StatusOK)
}

// SlackInteractions: POST /slack/interactions.
func (h *WebhookHandler) SlackInteractions(c *gin.Context) {
	raw, ok := h.slackBody(c)
	if !ok {
		return
	}
	form, err := url.ParseQuery(string(raw))
	if err != nil || form.Get("payload") == "" {
		apiError(c, http.StatusBadRequest, "bad_request", "missing payload")
		return
	}
	if err := h.slack.HandleInteraction(c.Request.Context(), []byte(form.Get("payload"))); err != nil {
		slog.Warn("slack interaction rejected", "error", err.Error())
		apiError(c, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	c.Status(http.StatusOK)
}
