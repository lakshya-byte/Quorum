package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

// ApiToken is a personal access token for the CLI. Only the sha256 hash of
// the token is stored; Prefix is the first characters, for display.
type ApiToken struct {
	ID         bson.ObjectID `bson:"_id,omitempty" json:"id"`
	UserID     bson.ObjectID `bson:"user_id" json:"userId"`
	Name       string        `bson:"name" json:"name"`
	TokenHash  string        `bson:"token_hash" json:"-"`
	Prefix     string        `bson:"prefix" json:"prefix"`
	CreatedAt  time.Time     `bson:"created_at" json:"createdAt"`
	LastUsedAt *time.Time    `bson:"last_used_at" json:"lastUsedAt"`
}
