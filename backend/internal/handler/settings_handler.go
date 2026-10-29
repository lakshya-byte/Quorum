package handler

import (
	"errors"
	"net/http"
	"time"

	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/repository"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

// SettingsHandler serves /api/settings/slack, /api/slack/link-code and
// /api/notifications.
type SettingsHandler struct {
	slack         *service.SlackSettingsService
	notifications service.NotificationStore
	slackAppReady bool
}

func NewSettingsHandler(slack *service.SlackSettingsService, notifications service.NotificationStore, slackAppReady bool) *SettingsHandler {
	return &SettingsHandler{slack: slack, notifications: notifications, slackAppReady: slackAppReady}
}

func (h *SettingsHandler) slackError(c *gin.Context, err error) {
	switch {
	case errors.Is(err, service.ErrBadWebhook):
		apiError(c, http.StatusBadRequest, "bad_request", err.Error())
	case errors.Is(err, service.ErrNoWebhook):
		apiError(c, http.StatusConflict, "conflict", err.Error())
	case errors.Is(err, crypt.ErrNotConfigured):
		serviceError(c, err)
	default:
		apiError(c, http.StatusInternalServerError, "internal", "failed to update slack settings")
	}
}

// GetSlack: GET /api/settings/slack.
func (h *SettingsHandler) GetSlack(c *gin.Context) {
	v, err := h.slack.View(c.Request.Context(), uid(c), h.slackAppReady)
	if err != nil {
		h.slackError(c, err)
		return
	}
	c.JSON(http.StatusOK, v)
}

// PutSlack: PUT /api/settings/slack {webhookUrl}.
func (h *SettingsHandler) PutSlack(c *gin.Context) {
	var req struct {
		WebhookURL string `json:"webhookUrl" binding:"required,max=300"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", "webhookUrl is required")
		return
	}
	if err := h.slack.SetWebhook(c.Request.Context(), uid(c), req.WebhookURL); err != nil {
		h.slackError(c, err)
		return
	}
	h.GetSlack(c)
}

// DeleteSlack: DELETE /api/settings/slack.
func (h *SettingsHandler) DeleteSlack(c *gin.Context) {
	if err := h.slack.ClearWebhook(c.Request.Context(), uid(c)); err != nil {
		h.slackError(c, err)
		return
	}
	h.GetSlack(c)
}

// TestSlack: POST /api/settings/slack/test.
func (h *SettingsHandler) TestSlack(c *gin.Context) {
	if err := h.slack.Test(c.Request.Context(), uid(c)); err != nil {
		if errors.Is(err, service.ErrNoWebhook) {
			h.slackError(c, err)
			return
		}
		apiError(c, http.StatusBadGateway, "upstream_error", "Slack did not accept the test message: check the webhook URL")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// LinkCode: POST /api/slack/link-code -> {code, expiresAt}.
func (h *SettingsHandler) LinkCode(c *gin.Context) {
	code, exp, err := h.slack.NewLinkCode(c.Request.Context(), uid(c))
	if err != nil {
		apiError(c, http.StatusInternalServerError, "internal", "failed to create link code")
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": code, "expiresAt": exp.Format(time.RFC3339), "command": "/patchloop link " + code})
}

// Notifications: GET /api/notifications.
func (h *SettingsHandler) Notifications(c *gin.Context) {
	ns, err := h.notifications.ListByUser(c.Request.Context(), uid(c), 50)
	if err != nil {
		apiError(c, http.StatusInternalServerError, "internal", "failed to list notifications")
		return
	}
	unread := 0
	for _, n := range ns {
		if !n.Read {
			unread++
		}
	}
	c.JSON(http.StatusOK, gin.H{"notifications": ns, "unread": unread})
}

// MarkRead: POST /api/notifications/:id/read.
func (h *SettingsHandler) MarkRead(c *gin.Context) {
	if err := h.notifications.MarkRead(c.Request.Context(), uid(c), c.Param("id")); err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			apiError(c, http.StatusNotFound, "not_found", "notification not found")
			return
		}
		apiError(c, http.StatusInternalServerError, "internal", "failed to update notification")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
