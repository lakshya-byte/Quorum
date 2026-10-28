package repository

import (
	"context"
	"errors"
	"time"

	"patchloop-backend/internal/models"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

type OTPRepository struct {
	col *mongo.Collection
}

func NewOTPRepository(db *mongo.Database) *OTPRepository {
	return &OTPRepository{col: db.Collection("otps")}
}

func (r *OTPRepository) Create(ctx context.Context, otp *models.OTP) error {
	otp.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, otp)
	if err != nil {
		return err
	}
	otp.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

// LatestForUser returns the most recently created, unexpired OTP for the
// given user + purpose.
func (r *OTPRepository) LatestForUser(ctx context.Context, userID bson.ObjectID, purpose models.OTPPurpose) (*models.OTP, error) {
	opts := options.FindOne().SetSort(bson.D{{Key: "created_at", Value: -1}})
	var otp models.OTP
	err := r.col.FindOne(ctx, bson.M{
		"user_id":    userID,
		"purpose":    purpose,
		"expires_at": bson.M{"$gt": time.Now().UTC()},
	}, opts).Decode(&otp)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &otp, nil
}

func (r *OTPRepository) IncrementAttempts(ctx context.Context, id bson.ObjectID) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$inc": bson.M{"attempts": 1}})
	return err
}

func (r *OTPRepository) DeleteByID(ctx context.Context, id bson.ObjectID) error {
	_, err := r.col.DeleteOne(ctx, bson.M{"_id": id})
	return err
}

func (r *OTPRepository) DeleteAllForUser(ctx context.Context, userID bson.ObjectID, purpose models.OTPPurpose) error {
	_, err := r.col.DeleteMany(ctx, bson.M{"user_id": userID, "purpose": purpose})
	return err
}
