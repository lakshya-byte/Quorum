package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

const (
	GitHubModeApp  = "app"
	GitHubModeDemo = "demo"
)

// GitHubConnection is one user's GitHub App link. The encrypted fields are
// AES-256-GCM ciphertext and are never serialised. The demo account has
// neither an installation nor tokens.
type GitHubConnection struct {
	UserID             string     `bson:"user_id" json:"-"`
	Mode               string     `bson:"mode" json:"mode"`
	Login              string     `bson:"login" json:"login"`
	AvatarURL          string     `bson:"avatar_url" json:"avatarUrl"`
	InstallationID     int64      `bson:"installation_id" json:"installationId"`
	EncUserToken       string     `bson:"enc_user_token,omitempty" json:"-"`
	EncRefreshToken    string     `bson:"enc_refresh_token,omitempty" json:"-"`
	UserTokenExpiresAt *time.Time `bson:"user_token_expires_at,omitempty" json:"-"`
	CreatedAt          time.Time  `bson:"created_at" json:"-"`
}

// SlackSettings holds a user's Slack preferences. The incoming webhook is a
// secret and is stored encrypted.
type SlackSettings struct {
	UserID      string    `bson:"user_id" json:"-"`
	EncWebhook  string    `bson:"enc_webhook,omitempty" json:"-"`
	DefaultRepo string    `bson:"default_repo,omitempty" json:"-"`
	UpdatedAt   time.Time `bson:"updated_at" json:"-"`
}

// SlackLink ties a Slack user to a PatchLoop user.
type SlackLink struct {
	SlackUserID string    `bson:"slack_user_id" json:"-"`
	UserID      string    `bson:"user_id" json:"-"`
	CreatedAt   time.Time `bson:"created_at" json:"-"`
}

// SlackLinkCode is a one-time code shown on the website.
type SlackLinkCode struct {
	Code      string    `bson:"code"`
	UserID    string    `bson:"user_id"`
	ExpiresAt time.Time `bson:"expires_at"`
}

// Notification is an in-app notification (PR opened, merged, failed).
type Notification struct {
	ID        bson.ObjectID `bson:"_id,omitempty" json:"id"`
	UserID    string        `bson:"user_id" json:"-"`
	Kind      string        `bson:"kind" json:"kind"` // pr_opened | pr_updated | merged | failed
	RunID     string        `bson:"run_id" json:"runId"`
	Title     string        `bson:"title" json:"title"`
	Body      string        `bson:"body" json:"body"`
	Read      bool          `bson:"read" json:"read"`
	CreatedAt time.Time     `bson:"created_at" json:"createdAt"`
}
