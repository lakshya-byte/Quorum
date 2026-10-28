package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

type OTPPurpose string

const (
	OTPPurposeSignupVerify OTPPurpose = "signup_verify"
)

type OTP struct {
	ID        bson.ObjectID `bson:"_id,omitempty" json:"id"`
	UserID    bson.ObjectID `bson:"user_id" json:"userId"`
	CodeHash  string        `bson:"code_hash" json:"-"`
	Purpose   OTPPurpose    `bson:"purpose" json:"purpose"`
	Attempts  int           `bson:"attempts" json:"attempts"`
	CreatedAt time.Time     `bson:"created_at" json:"createdAt"`
	ExpiresAt time.Time     `bson:"expires_at" json:"expiresAt"`
}
