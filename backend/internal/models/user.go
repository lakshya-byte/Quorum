package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

type User struct {
	ID            bson.ObjectID `bson:"_id,omitempty" json:"id"`
	Email         string        `bson:"email" json:"email"`
	ClerkID       string        `bson:"clerk_id,omitempty" json:"-"`
	PasswordHash  string        `bson:"password_hash" json:"-"`
	CompanyName   string        `bson:"company_name" json:"companyName"`
	EmailVerified bool          `bson:"email_verified" json:"emailVerified"`
	CreatedAt     time.Time     `bson:"created_at" json:"createdAt"`
	UpdatedAt     time.Time     `bson:"updated_at" json:"updatedAt"`
}
