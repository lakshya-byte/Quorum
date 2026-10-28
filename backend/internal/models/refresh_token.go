package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

type RefreshToken struct {
	ID        bson.ObjectID `bson:"_id,omitempty" json:"id"`
	UserID    bson.ObjectID `bson:"user_id" json:"userId"`
	TokenHash string        `bson:"token_hash" json:"-"`
	Revoked   bool          `bson:"revoked" json:"revoked"`
	CreatedAt time.Time     `bson:"created_at" json:"createdAt"`
	ExpiresAt time.Time     `bson:"expires_at" json:"expiresAt"`
}
