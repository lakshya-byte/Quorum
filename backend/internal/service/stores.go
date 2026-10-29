package service

import (
	"context"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/repository"
)

// RunStore persists runs. The Mongo implementation is repository.RunRepository;
// tests use an in-memory one.
type RunStore interface {
	Create(ctx context.Context, run *models.Run) error
	FindByID(ctx context.Context, id string) (*models.Run, error)
	ListByUser(ctx context.Context, userID string, limit int64) ([]models.Run, error)
	CountLiveSince(ctx context.Context, userID string, since time.Time) (int64, error)
	SetAgentRun(ctx context.Context, id string, agentRunID, mode, engine, traceID string) error
	SetStatus(ctx context.Context, id string, status string) error
	SetPR(ctx context.Context, id string, url string, number int, branch string) error
	SetMerged(ctx context.Context, id string, by string, at time.Time) error
	SetSlackSent(ctx context.Context, id string) error
	SetSlackRoot(ctx context.Context, id string, rootTS string) error
	FindBySlackThread(ctx context.Context, channel, threadTS string) (*models.Run, error)
	FindByPR(ctx context.Context, repo string, number int) (*models.Run, error)
	CountChildren(ctx context.Context, parentID string) (int64, error)
	Complete(ctx context.Context, agentRunID string, c repository.RunCompletion) (before, after *models.Run, err error)
}

// GitHubStore persists GitHub connections (one per user).
type GitHubStore interface {
	Get(ctx context.Context, userID string) (*models.GitHubConnection, error)
	Put(ctx context.Context, c *models.GitHubConnection) error
	Delete(ctx context.Context, userID string) error
	FindByInstallation(ctx context.Context, installationID int64) (*models.GitHubConnection, error)
	FindByLogin(ctx context.Context, login string) (*models.GitHubConnection, error)
}

// SlackStore persists Slack settings, user links and one-time link codes.
type SlackStore interface {
	GetSettings(ctx context.Context, userID string) (*models.SlackSettings, error)
	PutSettings(ctx context.Context, s *models.SlackSettings) error
	DeleteWebhook(ctx context.Context, userID string) error
	PutLink(ctx context.Context, l *models.SlackLink) error
	UserForSlack(ctx context.Context, slackUserID string) (string, error)
	SlackForUser(ctx context.Context, userID string) (string, error)
	PutCode(ctx context.Context, c *models.SlackLinkCode) error
	// TakeCode returns and deletes an unexpired code's owner.
	TakeCode(ctx context.Context, code string, now time.Time) (string, error)
}

// NotificationStore persists in-app notifications.
type NotificationStore interface {
	Create(ctx context.Context, n *models.Notification) error
	ListByUser(ctx context.Context, userID string, limit int64) ([]models.Notification, error)
	MarkRead(ctx context.Context, userID, id string) error
}

// DedupeStore remembers webhook delivery ids / Slack event ids.
// Seen records the key and reports whether it had been recorded before.
type DedupeStore interface {
	Seen(ctx context.Context, key string) (bool, error)
}
